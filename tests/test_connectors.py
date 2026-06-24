"""Tests for connector SDK (v1.9-G / v2.0-E)."""

from __future__ import annotations

from pathlib import Path

from ppt_lib.connectors import (
    ChangeEntry,
    ChangeType,
    ConnectorConfig,
    ConnectorRegistry,
    LocalFileSystemConnector,
    SourceItem,
    SyncResult,
)


class TestConnectorConfig:
    def test_to_json(self):
        cfg = ConnectorConfig("c1", "local_fs", "Test", settings={"path": "/tmp"})
        j = cfg.to_json()
        assert j["connector_id"] == "c1"
        assert j["connector_type"] == "local_fs"
        assert "path" in j["settings_keys"]


class TestSourceItem:
    def test_to_json(self):
        item = SourceItem("id1", "/path/to/file.pptx", "file.pptx", 1024, "abc123", "2026-01-01")
        j = item.to_json()
        assert j["name"] == "file.pptx"
        assert j["size_bytes"] == 1024


class TestChangeEntry:
    def test_to_json(self):
        item = SourceItem("id1", "/path", "file.pptx", 1024, "hash", "now")
        entry = ChangeEntry(ChangeType.ADDED, item, detected_at="now")
        j = entry.to_json()
        assert j["change_type"] == "added"
        assert "item" in j


class TestSyncResult:
    def test_success(self):
        r = SyncResult("c1", "start", "end", 10, [], "cursor1")
        assert r.success is True

    def test_failure(self):
        r = SyncResult("c1", "start", "end", 0, [], "", errors=["err"])
        assert r.success is False

    def test_to_json(self):
        r = SyncResult("c1", "start", "end", 10, [], "cursor1")
        j = r.to_json()
        assert j["items_discovered"] == 10


class TestLocalFileSystemConnector:
    def test_test_connection(self, tmp_path: Path):
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        assert conn.test_connection() is True

    def test_test_connection_missing_dir(self, tmp_path: Path):
        conn = LocalFileSystemConnector("c1", str(tmp_path / "nonexistent"))
        assert conn.test_connection() is False

    def test_discover_empty(self, tmp_path: Path):
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        items, cursor = conn.discover()
        assert len(items) == 0
        assert cursor != ""

    def test_discover_with_pptx(self, tmp_path: Path):
        (tmp_path / "test.pptx").write_bytes(b"PK fake pptx")
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        items, cursor = conn.discover()
        assert len(items) == 1
        assert items[0].name == "test.pptx"
        assert items[0].size_bytes > 0

    def test_discover_filters_extensions(self, tmp_path: Path):
        (tmp_path / "test.pptx").write_bytes(b"PK")
        (tmp_path / "test.txt").write_bytes(b"hello")
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        items, _ = conn.discover()
        assert len(items) == 1
        assert items[0].name == "test.pptx"

    def test_discover_respects_limit(self, tmp_path: Path):
        for i in range(5):
            (tmp_path / f"test{i}.pptx").write_bytes(f"content{i}".encode())
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        items, _ = conn.discover(limit=3)
        assert len(items) == 3

    def test_get_changes(self, tmp_path: Path):
        (tmp_path / "test.pptx").write_bytes(b"PK")
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        changes = conn.get_changes("1970-01-01T00:00:00")
        assert len(changes) >= 1
        assert changes[0].change_type == ChangeType.ADDED

    def test_fetch_content(self, tmp_path: Path):
        content = b"PK fake pptx content"
        (tmp_path / "test.pptx").write_bytes(content)
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        items, _ = conn.discover()
        fetched = conn.fetch_content(items[0])
        assert fetched == content

    def test_config(self, tmp_path: Path):
        conn = LocalFileSystemConnector("c1", str(tmp_path), name="My FS")
        cfg = conn.config()
        assert cfg.connector_id == "c1"
        assert cfg.name == "My FS"
        assert cfg.connector_type == "local_fs"


class TestConnectorRegistry:
    def test_register_and_list(self, tmp_path: Path):
        registry = ConnectorRegistry()
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        registry.register(conn)
        configs = registry.list_connectors()
        assert len(configs) == 1
        assert configs[0].connector_id == "c1"

    def test_get(self, tmp_path: Path):
        registry = ConnectorRegistry()
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        registry.register(conn)
        found = registry.get("c1")
        assert found is not None

    def test_get_missing(self):
        registry = ConnectorRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister(self, tmp_path: Path):
        registry = ConnectorRegistry()
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        registry.register(conn)
        assert registry.unregister("c1") is True
        assert registry.get("c1") is None

    def test_unregister_missing(self):
        registry = ConnectorRegistry()
        assert registry.unregister("nonexistent") is False

    def test_sync_all(self, tmp_path: Path):
        (tmp_path / "test.pptx").write_bytes(b"PK")
        registry = ConnectorRegistry()
        registry.register(LocalFileSystemConnector("c1", str(tmp_path)))
        results = registry.sync_all()
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].items_discovered >= 1

    def test_sync_all_skips_disabled(self, tmp_path: Path):
        registry = ConnectorRegistry()
        conn = LocalFileSystemConnector("c1", str(tmp_path))
        # Manually disable by replacing config
        conn._config = ConnectorConfig(
            "c1", "local_fs", "Test", enabled=False,
        )
        registry.register(conn)
        results = registry.sync_all()
        assert len(results) == 0
