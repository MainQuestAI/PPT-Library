from __future__ import annotations

import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, Literal, Protocol, cast

from ppt_lib.indexer import ErrorRecord, IndexResult
from ppt_lib.settings import Settings

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - dependency is declared, fallback keeps import robust.
    FileSystemEvent = object  # type: ignore[misc,assignment]
    FileSystemEventHandler = object  # type: ignore[misc,assignment]
    Observer = None  # type: ignore[assignment]


@dataclass(frozen=True)
class WatchEvent:
    path: Path
    event_type: Literal["created", "modified", "moved"]
    detected_at: datetime


@dataclass
class _QueuedPath:
    path: Path
    last_seen: datetime
    stability_failures: int = 0


class _ObserverLike(Protocol):
    def schedule(self, event_handler: object, path: str, recursive: bool = True) -> object: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...
    def is_alive(self) -> bool: ...


class WatchRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WatchQueue:
    def __init__(self) -> None:
        self._items: dict[Path, _QueuedPath] = {}
        self._lock = threading.Lock()

    def add(self, path: Path, detected_at: datetime | None = None) -> None:
        normalized = _normalize_path(path)
        now = detected_at or datetime.now(UTC)
        with self._lock:
            item = self._items.get(normalized)
            if item:
                item.last_seen = now
                return
            self._items[normalized] = _QueuedPath(path=normalized, last_seen=now)

    def pop_all(self) -> list[Path]:
        with self._lock:
            items = [item.path for item in self._items.values()]
            self._items = {}
        return items

    def pop_ready(self, now: datetime, debounce_seconds: int, *, force: bool = False) -> list[_QueuedPath]:
        ready: list[_QueuedPath] = []
        with self._lock:
            for path, item in list(self._items.items()):
                elapsed = (now - item.last_seen).total_seconds()
                if force or elapsed >= debounce_seconds:
                    ready.append(item)
                    del self._items[path]
        return sorted(ready, key=lambda item: str(item.path))

    def requeue_unstable(self, item: _QueuedPath, detected_at: datetime | None = None) -> None:
        item.stability_failures += 1
        item.last_seen = detected_at or datetime.now(UTC)
        with self._lock:
            self._items[item.path] = item

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def is_pptx_candidate(path: Path) -> bool:
    name = path.name
    if name.startswith("~$") or name.startswith("."):
        return False
    return path.suffix.lower() == ".pptx"


def wait_until_file_stable(path: Path, interval_seconds: int = 2, attempts: int = 3) -> bool:
    previous: tuple[int, float] | None = None
    for _ in range(attempts):
        try:
            stat = path.stat()
        except OSError:
            return False
        current = (stat.st_size, stat.st_mtime)
        if previous == current:
            return True
        previous = current
        if interval_seconds:
            time.sleep(interval_seconds)
    return False


def process_events_once(
    queue: WatchQueue,
    index_callback: Callable[[Path], IndexResult | object],
) -> list[ErrorRecord]:
    errors: list[ErrorRecord] = []
    for path in queue.pop_all():
        try:
            result = index_callback(path)
            errors.extend(_index_result_errors(path, result))
        except Exception as exc:
            errors.append(
                ErrorRecord(
                    code="WATCH_INDEX_FAILED",
                    message=str(exc),
                    source_module="watch",
                    severity="warning",
                )
            )
    return errors


class PptxEventHandler(FileSystemEventHandler):
    def __init__(self, queue: WatchQueue) -> None:
        super().__init__()
        self.queue = queue

    def on_created(self, event: FileSystemEvent) -> None:
        self._record_event(Path(str(event.src_path)))

    def on_modified(self, event: FileSystemEvent) -> None:
        self._record_event(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        destination = getattr(event, "dest_path", "")
        self._record_event(Path(str(destination or event.src_path)))

    def _record_event(self, path: Path) -> None:
        if is_pptx_candidate(path):
            self.queue.add(path)


class WatchService:
    def __init__(
        self,
        root: Path,
        settings: Settings,
        index_callback: Callable[[Path], IndexResult | object],
        *,
        queue: WatchQueue | None = None,
        observer_factory: Callable[[], _ObserverLike] | None = None,
        stop_event: threading.Event | None = None,
        poll_interval_seconds: float = 0.5,
        max_stability_failures: int = 3,
        max_observer_restarts: int = 1,
    ) -> None:
        self.root = root
        self.settings = settings
        self.index_callback = index_callback
        self.queue = queue or WatchQueue()
        self.observer_factory = observer_factory or self._default_observer_factory
        self.stop_event = stop_event or threading.Event()
        self.poll_interval_seconds = poll_interval_seconds
        self.max_stability_failures = max_stability_failures
        self.max_observer_restarts = max_observer_restarts
        self.errors: list[ErrorRecord] = []
        self._observer: _ObserverLike | None = None
        self._restarts_used = 0
        self._old_sigint_handler: signal.Handlers | Callable[[int, FrameType | None], Any] | int | None = None

    def run(self) -> list[ErrorRecord]:
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(self.root)

        self._install_sigint_handler()
        try:
            self._enqueue_existing_files()
            self._observer = self._start_observer()
            while not self.stop_event.is_set():
                self.process_ready()
                if self._observer and not self._observer.is_alive():
                    self._handle_observer_stopped()
                self.stop_event.wait(self.poll_interval_seconds)
            self.process_ready(force=True)
            return self.errors
        finally:
            self._stop_observer()
            self._restore_sigint_handler()

    def process_ready(self, *, force: bool = False) -> list[ErrorRecord]:
        now = datetime.now(UTC)
        ready = self.queue.pop_ready(now, self.settings.watch_debounce_seconds, force=force)
        if len(ready) >= 50:
            print(f"ppt-lib watch: processing {len(ready)} files", file=sys.stderr)

        batch_errors: list[ErrorRecord] = []
        for item in ready:
            if not wait_until_file_stable(item.path):
                if item.stability_failures + 1 >= self.max_stability_failures:
                    batch_errors.append(
                        ErrorRecord(
                            code="WATCH_FILE_UNSTABLE",
                            message=f"File did not stabilize: {item.path}",
                            source_module="watch",
                            severity="warning",
                        )
                    )
                    continue
                self.queue.requeue_unstable(item)
                continue
            try:
                result = self.index_callback(item.path)
                batch_errors.extend(_index_result_errors(item.path, result))
            except Exception as exc:
                batch_errors.append(
                    ErrorRecord(
                        code="WATCH_INDEX_FAILED",
                        message=str(exc),
                        source_module="watch",
                        severity="warning",
                    )
                )
        self.errors.extend(batch_errors)
        return batch_errors

    def _enqueue_existing_files(self) -> None:
        for path in sorted(self.root.rglob("*.pptx")):
            if is_pptx_candidate(path):
                self.queue.add(path)

    def _start_observer(self) -> _ObserverLike:
        observer = self.observer_factory()
        observer.schedule(PptxEventHandler(self.queue), str(self.root), recursive=True)
        observer.start()
        return observer

    def _handle_observer_stopped(self) -> None:
        if self._restarts_used < self.max_observer_restarts:
            self._restarts_used += 1
            self.errors.append(
                ErrorRecord(
                    code="WATCH_OBSERVER_RESTARTED",
                    message="Watch observer stopped and was restarted.",
                    source_module="watch",
                    severity="warning",
                )
            )
            self._stop_observer()
            self._observer = self._start_observer()
            return
        raise WatchRuntimeError("WATCH_OBSERVER_STOPPED", "Watch observer stopped after restart attempt.")

    def _stop_observer(self) -> None:
        if not self._observer:
            return
        self._observer.stop()
        self._observer.join(timeout=5)

    def _default_observer_factory(self) -> _ObserverLike:
        if Observer is None:
            raise WatchRuntimeError("WATCHDOG_MISSING", "watchdog dependency is not available.")
        return cast(_ObserverLike, Observer())

    def _install_sigint_handler(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._old_sigint_handler = signal.getsignal(signal.SIGINT)

        def handle_sigint(signum: int, frame: FrameType | None) -> None:
            self.stop_event.set()

        signal.signal(signal.SIGINT, handle_sigint)

    def _restore_sigint_handler(self) -> None:
        if self._old_sigint_handler is not None and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._old_sigint_handler)


def watch_directory(
    root: Path,
    settings: Settings,
    index_callback: Callable[[Path], IndexResult | object],
) -> list[ErrorRecord]:
    return WatchService(root, settings, index_callback).run()


def now_event(path: Path, event_type: Literal["created", "modified", "moved"]) -> WatchEvent:
    return WatchEvent(path=path, event_type=event_type, detected_at=datetime.now(UTC))


def _normalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _index_result_errors(path: Path, result: object) -> list[ErrorRecord]:
    if not isinstance(result, IndexResult):
        return []
    if result.status != "failed" and not result.errors:
        return []
    messages = [item.message for item in result.errors] or [f"Index returned status '{result.status}'."]
    return [
        ErrorRecord(
            code="WATCH_INDEX_FAILED",
            message=f"{path}: {message}",
            source_module="watch",
            severity="warning",
        )
        for message in messages
    ]
