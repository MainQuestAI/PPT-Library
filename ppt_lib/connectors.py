"""Connector SDK for external data source integration (v1.9-G / v2.0-E).

Defines the connector protocol for integrating external data sources
(file systems, NAS, cloud storage, enterprise systems).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class ChangeType(StrEnum):
    """Types of changes detected by a connector."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class ConnectorConfig:
    """Configuration for a connector instance."""

    connector_id: str
    connector_type: str
    name: str
    settings: dict[str, object] = field(default_factory=dict)
    enabled: bool = True
    sync_interval_seconds: int = 3600

    def to_json(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "connector_type": self.connector_type,
            "name": self.name,
            "enabled": self.enabled,
            "sync_interval_seconds": self.sync_interval_seconds,
            "settings_keys": sorted(self.settings.keys()),
        }


@dataclass(frozen=True)
class SourceItem:
    """An item discovered by a connector."""

    item_id: str
    path: str
    name: str
    size_bytes: int
    content_hash: str
    modified_at: str
    item_type: str = "file"  # file | directory | link
    metadata: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "modified_at": self.modified_at,
            "item_type": self.item_type,
        }


@dataclass(frozen=True)
class ChangeEntry:
    """A change detected since the last sync."""

    change_type: ChangeType
    item: SourceItem | None
    previous_path: str | None = None  # For renames
    detected_at: str = ""

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "change_type": self.change_type,
            "detected_at": self.detected_at,
        }
        if self.item:
            d["item"] = self.item.to_json()
        if self.previous_path:
            d["previous_path"] = self.previous_path
        return d


@dataclass(frozen=True)
class SyncResult:
    """Result of a sync operation."""

    connector_id: str
    started_at: str
    finished_at: str
    items_discovered: int
    changes: list[ChangeEntry]
    cursor: str
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_json(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "items_discovered": self.items_discovered,
            "changes_count": len(self.changes),
            "cursor": self.cursor,
            "success": self.success,
            "errors": self.errors,
        }


class Connector(ABC):
    """Abstract base class for data source connectors."""

    @abstractmethod
    def config(self) -> ConnectorConfig:
        """Return the connector configuration."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the connector can reach the data source."""

    @abstractmethod
    def discover(
        self,
        *,
        cursor: str | None = None,
        limit: int = 1000,
    ) -> tuple[list[SourceItem], str]:
        """Discover items from the data source.

        Returns (items, new_cursor).
        """

    @abstractmethod
    def get_changes(
        self,
        since_cursor: str,
    ) -> list[ChangeEntry]:
        """Get changes since the given cursor."""

    @abstractmethod
    def fetch_content(self, item: SourceItem) -> bytes:
        """Fetch the raw content of an item."""


class LocalFileSystemConnector(Connector):
    """Connector for local file system directories."""

    def __init__(
        self,
        connector_id: str,
        root_path: str,
        *,
        name: str = "Local FS",
        extensions: list[str] | None = None,
    ) -> None:
        self._config = ConnectorConfig(
            connector_id=connector_id,
            connector_type="local_fs",
            name=name,
            settings={"root_path": root_path, "extensions": extensions or [".pptx"]},
        )
        self._root = Path(root_path)
        self._extensions = set(extensions or [".pptx"])

    def config(self) -> ConnectorConfig:
        return self._config

    def test_connection(self) -> bool:
        return self._root.is_dir()

    def discover(
        self,
        *,
        cursor: str | None = None,
        limit: int = 1000,
    ) -> tuple[list[SourceItem], str]:
        items: list[SourceItem] = []
        cursor_time = cursor or "1970-01-01T00:00:00"

        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            # Security: skip symlinks to prevent path traversal outside root
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve()
                if not str(resolved).startswith(str(self._root.resolve())):
                    continue
            except (OSError, ValueError):
                continue
            if path.suffix.lower() not in self._extensions:
                continue
            if len(items) >= limit:
                break

            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            if modified <= cursor_time:
                continue

            content_hash = hashlib.sha256(
                str(stat.st_size).encode() + str(stat.st_mtime).encode()
            ).hexdigest()[:16]

            items.append(SourceItem(
                item_id=f"{self._config.connector_id}:{path.relative_to(self._root)}",
                path=str(path),
                name=path.name,
                size_bytes=stat.st_size,
                content_hash=content_hash,
                modified_at=modified,
            ))

        new_cursor = datetime.now(UTC).isoformat()
        return items, new_cursor

    def get_changes(self, since_cursor: str) -> list[ChangeEntry]:
        items, _ = self.discover(cursor=since_cursor)
        now = datetime.now(UTC).isoformat()
        return [
            ChangeEntry(
                change_type=ChangeType.ADDED,
                item=item,
                detected_at=now,
            )
            for item in items
        ]

    def fetch_content(self, item: SourceItem) -> bytes:
        return Path(item.path).read_bytes()


class ConnectorRegistry:
    """Registry for managing multiple connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        config = connector.config()
        self._connectors[config.connector_id] = connector

    def unregister(self, connector_id: str) -> bool:
        if connector_id in self._connectors:
            del self._connectors[connector_id]
            return True
        return False

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[ConnectorConfig]:
        return [c.config() for c in self._connectors.values()]

    def sync_all(self) -> list[SyncResult]:
        results: list[SyncResult] = []
        for connector in self._connectors.values():
            if not connector.config().enabled:
                continue
            started = datetime.now(UTC).isoformat()
            try:
                items, cursor = connector.discover()
                finished = datetime.now(UTC).isoformat()
                results.append(SyncResult(
                    connector_id=connector.config().connector_id,
                    started_at=started,
                    finished_at=finished,
                    items_discovered=len(items),
                    changes=[],
                    cursor=cursor,
                ))
            except Exception as exc:
                finished = datetime.now(UTC).isoformat()
                results.append(SyncResult(
                    connector_id=connector.config().connector_id,
                    started_at=started,
                    finished_at=finished,
                    items_discovered=0,
                    changes=[],
                    cursor="",
                    errors=[str(exc)],
                ))
        return results
