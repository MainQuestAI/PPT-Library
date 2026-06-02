from __future__ import annotations

from pathlib import Path

import pytest

from ppt_lib.config import load_settings
from ppt_lib.discovery import (
    DiscoveryError,
    create_symlink_view,
    deduplicate_versions,
    scan_presentations,
)


def touch(path: Path, content: bytes = b"pptx") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_scan_empty_dir(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")
    (tmp_path / "source").mkdir()

    assert scan_presentations(tmp_path / "source", settings) == []


def test_scan_missing_dir_raises(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    with pytest.raises(DiscoveryError) as exc:
        scan_presentations(tmp_path / "missing", settings)

    assert exc.value.code == "DISCOVERY_ROOT_NOT_FOUND"


def test_scan_mixed_files_only_pptx(tmp_path: Path) -> None:
    root = tmp_path / "source"
    touch(root / "alpha" / "deck.pptx")
    touch(root / "alpha" / "notes.txt")
    touch(root / "alpha" / "legacy.ppt")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    items = scan_presentations(root, settings)

    assert [item.filename for item in items] == ["deck.pptx"]
    assert items[0].project_name == "alpha"
    assert items[0].path.is_absolute()


def test_scan_skips_office_locks_and_dependency_dirs(tmp_path: Path) -> None:
    root = tmp_path / "source"
    touch(root / "alpha" / "deck.pptx")
    touch(root / "alpha" / "~$deck.pptx")
    touch(root / "alpha" / ".~deck.pptx")
    touch(root / "node_modules" / "vendor.pptx")
    touch(root / ".venv" / "cached.pptx")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    items = scan_presentations(root, settings)

    assert [item.filename for item in items] == ["deck.pptx"]


def test_scan_skips_cache_dirs(tmp_path: Path) -> None:
    root = tmp_path / "source"
    touch(root / "alpha" / "deck.pptx")
    touch(root / "WXWork Files" / "Caches" / "WXWork Files" / "Caches" / "Files" / "cached.pptx")
    touch(root / "Library" / "Caches" / "cached.pptx")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    items = scan_presentations(root, settings)

    assert [item.filename for item in items] == ["deck.pptx"]


def test_dedup_v_number_prefers_highest(tmp_path: Path) -> None:
    root = tmp_path / "source"
    v1 = touch(root / "alpha" / "pitch_v1.pptx", b"v1")
    v3 = touch(root / "alpha" / "pitch_v3.pptx", b"v3")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    items = deduplicate_versions(scan_presentations(root, settings))

    selected = [item for item in items if item.selected]
    assert selected[0].path == v3
    assert any(item.path == v1 and item.selected is False for item in items)


def test_dedup_mtime_fallback(tmp_path: Path) -> None:
    root = tmp_path / "source"
    old = touch(root / "alpha" / "pitch_a.pptx", b"a")
    new = touch(root / "alpha" / "pitch_b.pptx", b"b")
    old.touch()
    new.touch()
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    items = deduplicate_versions(scan_presentations(root, settings))

    assert [item.path for item in items if item.selected] == [new]


def test_symlink_collision_adds_hash(tmp_path: Path) -> None:
    root = tmp_path / "source"
    first = touch(root / "alpha" / "deck.pptx", b"first")
    second = touch(root / "beta" / "deck.pptx", b"second")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")
    items = scan_presentations(root, settings)
    items = [item.__class__(**{**item.__dict__, "project_name": "same"}) for item in items]

    links = create_symlink_view(items, settings)

    assert len(links) == 2
    assert links[0].exists()
    assert links[1].exists()
    assert len({link.name for link in links}) == 2
    assert {link.resolve() for link in links} == {first.resolve(), second.resolve()}


def test_create_symlink_view_only_selected(tmp_path: Path) -> None:
    root = tmp_path / "source"
    touch(root / "alpha" / "pitch_v1.pptx", b"v1")
    selected = touch(root / "alpha" / "pitch_v2.pptx", b"v2")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    links = create_symlink_view(deduplicate_versions(scan_presentations(root, settings)), settings)

    assert len(links) == 1
    assert links[0].resolve() == selected.resolve()
