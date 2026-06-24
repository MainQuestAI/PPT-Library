"""Tests for local API server (v1.8-B)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ppt_lib.api_server import APIConfig, create_api_app
from ppt_lib.asset_schema import create_asset_schema_tables


def _create_test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            text_content TEXT,
            title TEXT,
            metadata_json TEXT DEFAULT '{}',
            slide_revision_id TEXT,
            canonical_asset_id TEXT
        )"""
    )
    conn.execute("CREATE TABLE presentations (id INTEGER PRIMARY KEY, path TEXT, filename TEXT)")
    conn.execute("CREATE TABLE embeddings (slide_id INTEGER, presentation_id INTEGER, embedding BLOB)")
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT, slide_revision_id TEXT, legacy_slide_id INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE feedback_events (
            event_id TEXT PRIMARY KEY, asset_id TEXT, event_type TEXT,
            reason TEXT, context_json TEXT, created_at TEXT
        )"""
    )
    conn.execute("""CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)""")
    conn.execute("INSERT INTO _meta VALUES ('schema_version', '5')")
    conn.execute("INSERT INTO slides VALUES (1, 1, 'architecture diagram', 'T1', '{}', NULL, NULL)")
    conn.execute("INSERT INTO presentations VALUES (1, '/test.pptx', 'test.pptx')")
    create_asset_schema_tables(conn)
    conn.execute("INSERT INTO slide_assets VALUES ('a1', 'slide', 'now', 'now', '{}')")
    conn.commit()
    conn.close()
    return db_path


class TestAPIConfig:
    def test_default_config(self):
        config = APIConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8899
        assert len(config.secret_key) > 0

    def test_custom_config(self):
        config = APIConfig(host="0.0.0.0", port=9000, debug=True)
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.debug is True

    def test_auto_secret(self):
        c1 = APIConfig()
        c2 = APIConfig()
        assert c1.secret_key != c2.secret_key


try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestAPIEndpoints:
    def test_health(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_status(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_search(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/search?q=architecture")
        assert response.status_code == 200

    def test_search_empty_query(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/search")
        assert response.status_code == 400

    def test_list_assets(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_asset(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets/a1")
        assert response.status_code == 200

    def test_get_asset_not_found(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets/nonexistent")
        assert response.status_code == 404

    def test_review_status(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/review/status")
        assert response.status_code == 200

    def test_envelope_format(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/status")
        data = response.json()
        assert "_meta" in data
        assert "success" in data
        assert "message" in data
        assert "_errors" in data
