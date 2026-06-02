from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ppt_lib.watch import (
    PptxEventHandler,
    WatchQueue,
    WatchService,
    is_pptx_candidate,
    process_events_once,
    wait_until_file_stable,
)


def test_non_pptx_ignored(tmp_path: Path) -> None:
    assert is_pptx_candidate(tmp_path / "notes.txt") is False
    assert is_pptx_candidate(tmp_path / "deck.pptx") is True


def test_temp_files_ignored(tmp_path: Path) -> None:
    assert is_pptx_candidate(tmp_path / "~$deck.pptx") is False
    assert is_pptx_candidate(tmp_path / ".deck.pptx") is False


def test_queue_deduplicates_same_path(tmp_path: Path) -> None:
    queue = WatchQueue()
    path = tmp_path / "deck.pptx"

    queue.add(path)
    queue.add(path)

    assert queue.pop_all() == [path]


def test_debounce_double_save_single_trigger(tmp_path: Path) -> None:
    queue = WatchQueue()
    path = tmp_path / "deck.pptx"
    first = datetime(2026, 5, 22, tzinfo=UTC)

    queue.add(path, first)
    queue.add(path, first + timedelta(seconds=4))

    assert queue.pop_ready(first + timedelta(seconds=5), debounce_seconds=5) == []
    assert [item.path for item in queue.pop_ready(first + timedelta(seconds=9), debounce_seconds=5)] == [path]


def test_process_events_once_continues_after_failure(tmp_path: Path) -> None:
    good = tmp_path / "good.pptx"
    bad = tmp_path / "bad.pptx"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")
    queue = WatchQueue()
    queue.add(bad)
    queue.add(good)
    processed: list[Path] = []

    def callback(path: Path) -> None:
        processed.append(path)
        if path == bad:
            raise RuntimeError("failed")

    errors = process_events_once(queue, callback)

    assert processed == [bad, good]
    assert errors[0].code == "WATCH_INDEX_FAILED"


def test_wait_until_file_stable_success(tmp_path: Path) -> None:
    path = tmp_path / "deck.pptx"
    path.write_bytes(b"stable")

    assert wait_until_file_stable(path, interval_seconds=0, attempts=2) is True


def test_wait_until_file_stable_missing_file(tmp_path: Path) -> None:
    assert wait_until_file_stable(tmp_path / "missing.pptx", interval_seconds=0, attempts=2) is False


def test_event_handler_queues_pptx_created(tmp_path: Path) -> None:
    queue = WatchQueue()
    handler = PptxEventHandler(queue)
    path = tmp_path / "deck.pptx"

    class Event:
        src_path = str(path)

    handler.on_created(Event())

    assert queue.pop_all() == [path]


def test_watch_service_indexes_existing_file_once(tmp_path: Path, monkeypatch) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"deck")
    stop_event = threading.Event()
    processed: list[Path] = []

    class FakeObserver:
        def schedule(self, event_handler, path, recursive=True):
            return None

        def start(self):
            return None

        def stop(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            stop_event.set()
            return True

    monkeypatch.setattr("ppt_lib.watch.wait_until_file_stable", lambda path: True)

    service = WatchService(
        tmp_path,
        settings=type("Settings", (), {"watch_debounce_seconds": 0})(),
        index_callback=lambda path: processed.append(path),
        observer_factory=FakeObserver,
        stop_event=stop_event,
        poll_interval_seconds=0,
    )

    errors = service.run()

    assert errors == []
    assert processed == [deck]


def test_watch_service_observer_restart_once(tmp_path: Path) -> None:
    stop_event = threading.Event()
    starts = 0

    class FakeObserver:
        def schedule(self, event_handler, path, recursive=True):
            return None

        def start(self):
            nonlocal starts
            starts += 1
            return None

        def stop(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            if starts >= 2:
                stop_event.set()
                return True
            return False

    service = WatchService(
        tmp_path,
        settings=type("Settings", (), {"watch_debounce_seconds": 0})(),
        index_callback=lambda path: None,
        observer_factory=FakeObserver,
        stop_event=stop_event,
        poll_interval_seconds=0,
    )

    errors = service.run()

    assert starts == 2
    assert errors[0].code == "WATCH_OBSERVER_RESTARTED"


def test_watch_service_unstable_file_records_warning(tmp_path: Path, monkeypatch) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"deck")
    stop_event = threading.Event()

    class FakeObserver:
        def schedule(self, event_handler, path, recursive=True):
            return None

        def start(self):
            return None

        def stop(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            stop_event.set()
            return True

    monkeypatch.setattr("ppt_lib.watch.wait_until_file_stable", lambda path: False)
    service = WatchService(
        tmp_path,
        settings=type("Settings", (), {"watch_debounce_seconds": 0})(),
        index_callback=lambda path: None,
        observer_factory=FakeObserver,
        stop_event=stop_event,
        poll_interval_seconds=0,
        max_stability_failures=1,
    )

    errors = service.run()

    assert errors[0].code == "WATCH_FILE_UNSTABLE"
