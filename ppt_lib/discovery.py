from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ppt_lib.settings import Settings

IGNORED_DIR_NAMES = {".venv", ".pydeps", "node_modules", "__pycache__"}
IGNORED_FILE_PREFIXES = ("~$", ".~")
IGNORED_CACHE_MARKERS = (
    "/Library/Caches/",
    "/WXWork Files/Caches/",
    "/WeChat Files/All Users/Caches/",
)


class DiscoveryError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DiscoveredPresentation:
    path: Path
    project_name: str | None
    filename: str
    version_key: str | None
    file_size: int
    file_mtime: float
    selected: bool
    reason: str


def scan_presentations(root: Path, settings: Settings) -> list[DiscoveredPresentation]:
    root = root.expanduser().resolve(strict=False)
    if not root.exists():
        raise DiscoveryError(f"Discovery root not found: {root}", code="DISCOVERY_ROOT_NOT_FOUND")
    if not root.is_dir():
        raise DiscoveryError(f"Discovery root is not a directory: {root}", code="DISCOVERY_ROOT_NOT_FOUND")

    items: list[DiscoveredPresentation] = []
    for path in sorted(root.rglob("*")):
        if _is_ignored_path(root, path):
            continue
        if not path.is_file() or path.suffix.lower() != ".pptx":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        normalized_path = path.expanduser().resolve(strict=False)
        project_name = _project_name(root, normalized_path)
        items.append(
            DiscoveredPresentation(
                path=normalized_path,
                project_name=project_name,
                filename=path.name,
                version_key=_version_key(path.stem),
                file_size=stat.st_size,
                file_mtime=stat.st_mtime,
                selected=True,
                reason="candidate",
            )
        )
    return items


def _is_ignored_path(root: Path, path: Path) -> bool:
    if path.name.startswith(IGNORED_FILE_PREFIXES):
        return True
    if is_cache_path(path):
        return True
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(part in IGNORED_DIR_NAMES for part in relative.parts)


def is_cache_path(path: Path) -> bool:
    normalized = "/" + str(path.expanduser()).replace("\\", "/").lstrip("/")
    return any(marker in normalized for marker in IGNORED_CACHE_MARKERS)


def deduplicate_versions(items: list[DiscoveredPresentation]) -> list[DiscoveredPresentation]:
    groups: dict[tuple[str | None, str], list[DiscoveredPresentation]] = {}
    for item in items:
        groups.setdefault((item.project_name, _dedup_key(item.filename)), []).append(item)

    result: list[DiscoveredPresentation] = []
    for group in groups.values():
        winner = max(group, key=_dedup_rank)
        for item in group:
            if item.path == winner.path:
                result.append(_replace(item, selected=True, reason="selected"))
            else:
                result.append(_replace(item, selected=False, reason=f"superseded_by:{winner.filename}"))
    return sorted(result, key=lambda item: str(item.path))


def create_symlink_view(items: list[DiscoveredPresentation], settings: Settings) -> list[Path]:
    symlinks_dir = settings.symlinks_dir
    assert symlinks_dir is not None
    symlinks_dir.mkdir(parents=True, exist_ok=True)
    links: list[Path] = []
    used_names: set[str] = set()
    for item in items:
        if not item.selected:
            continue
        base_name = _safe_link_name(item)
        link_name = base_name
        if link_name in used_names or (symlinks_dir / link_name).exists() and (symlinks_dir / link_name).resolve() != item.path.resolve():
            digest = hashlib.sha256(str(item.path).encode("utf-8")).hexdigest()[:8]
            link_name = f"{Path(base_name).stem}__{digest}{Path(base_name).suffix}"
        used_names.add(link_name)
        link_path = symlinks_dir / link_name
        if link_path.exists() or link_path.is_symlink():
            if link_path.resolve() == item.path.resolve():
                links.append(link_path)
                continue
            link_path.unlink()
        os.symlink(item.path, link_path)
        links.append(link_path)
    return links


def _project_name(root: Path, path: Path) -> str | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.parent.name or None
    if len(relative.parts) <= 1:
        return None
    return relative.parts[0]


def _version_key(stem: str) -> str | None:
    match = re.search(r"(?:^|[_\-\s])(v\d+|final\d*)$", stem, flags=re.IGNORECASE)
    return match.group(1).lower() if match else None


def _version_number(version_key: str | None) -> int:
    if not version_key:
        return -1
    digits = re.findall(r"\d+", version_key)
    if digits:
        return int(digits[-1])
    if version_key.startswith("final"):
        return 10_000
    return 0


def _dedup_key(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"([_\-\s])(v\d+|final\d*)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"([_\-\s])[a-z]$", "", stem, flags=re.IGNORECASE)
    return stem


def _dedup_rank(item: DiscoveredPresentation) -> tuple[int, float, int, str]:
    return (_version_number(item.version_key), item.file_mtime, item.file_size, str(item.path))


def _replace(item: DiscoveredPresentation, **changes: object) -> DiscoveredPresentation:
    values = item.__dict__.copy()
    values.update(changes)
    return DiscoveredPresentation(**values)


def _safe_link_name(item: DiscoveredPresentation) -> str:
    prefix = item.project_name or "ungrouped"
    return f"{prefix}__{item.filename}"
