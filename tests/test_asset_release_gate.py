"""Tests for asset intelligence release gate (v1.7-H)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ppt_lib.asset_release_gate import (
    AssetIntelligenceGate,
    export_asset_pack,
    import_asset_pack,
    run_asset_intelligence_gate,
)
from ppt_lib.asset_schema import create_asset_schema_tables
from ppt_lib.db import connect, init_db


def _create_full_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE presentations (id INTEGER PRIMARY KEY, path TEXT, filename TEXT)")
    conn.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY, presentation_id INTEGER, text_content TEXT)")
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT, slide_revision_id TEXT,
            legacy_slide_id INTEGER, identity_status TEXT,
            algorithm_version TEXT, created_at TEXT, updated_at TEXT,
            PRIMARY KEY (canonical_asset_id, slide_revision_id)
        )"""
    )
    create_asset_schema_tables(conn)
    return conn


class TestAssetIntelligenceGate:
    def test_gate_with_tables(self):
        conn = _create_full_db()
        gate = run_asset_intelligence_gate(conn)
        assert isinstance(gate, AssetIntelligenceGate)
        assert gate.pass_count >= 5

    def test_gate_to_json(self):
        conn = _create_full_db()
        gate = run_asset_intelligence_gate(conn)
        j = gate.to_json()
        assert "passed" in j
        assert "checks" in j

    def test_gate_minimal_db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY, text_content TEXT)")
        gate = run_asset_intelligence_gate(conn)
        assert isinstance(gate, AssetIntelligenceGate)
        # Some checks should fail without full schema
        assert gate.fail_count > 0

    def test_gate_accepts_real_v6_asset_role_tables(self, tmp_path: Path):
        conn = connect(tmp_path / "index.db")
        init_db(conn)

        gate = run_asset_intelligence_gate(conn)

        role_check = next(check for check in gate.checks if check["name"] == "asset_roles_separated")
        assert role_check["passed"] is True


class TestExportAssetPack:
    def test_export_dry_run(self):
        conn = _create_full_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'text')")
        result = export_asset_pack(conn, Path("/tmp/test.json"), dry_run=True)
        assert result["dry_run"] is True
        assert "tables" in result

    def test_export_to_file(self, tmp_path: Path):
        conn = _create_full_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'text')")
        conn.execute(
            "INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1, 'resolved', 'v1', 'now', 'now')"
        )
        output = tmp_path / "pack.json"
        export_asset_pack(conn, output)
        assert output.is_file()
        pack = json.loads(output.read_text())
        assert pack["tables"]["asset_identity_map"]["count"] == 1

    def test_export_empty_db(self, tmp_path: Path):
        conn = _create_full_db()
        output = tmp_path / "empty.json"
        result = export_asset_pack(conn, output)
        assert result["total_rows"] == 0


class TestImportAssetPack:
    def test_round_trip(self, tmp_path: Path):
        # Export from source
        conn_src = _create_full_db()
        conn_src.execute(
            "INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1, 'resolved', 'v1', 'now', 'now')"
        )
        pack_path = tmp_path / "pack.json"
        export_asset_pack(conn_src, pack_path)

        # Import into target
        conn_dst = _create_full_db()
        result = import_asset_pack(conn_dst, pack_path)
        assert result["tables"]["asset_identity_map"] == 1

        cursor = conn_dst.cursor()
        cursor.execute("SELECT COUNT(*) FROM asset_identity_map")
        assert cursor.fetchone()[0] == 1

    def test_import_dry_run(self, tmp_path: Path):
        conn_src = _create_full_db()
        conn_src.execute(
            "INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1, 'resolved', 'v1', 'now', 'now')"
        )
        pack_path = tmp_path / "pack.json"
        export_asset_pack(conn_src, pack_path)

        conn_dst = _create_full_db()
        result = import_asset_pack(conn_dst, pack_path, dry_run=True)
        assert result["dry_run"] is True

        cursor = conn_dst.cursor()
        cursor.execute("SELECT COUNT(*) FROM asset_identity_map")
        assert cursor.fetchone()[0] == 0

    def test_import_missing_tables(self, tmp_path: Path):
        pack_data = {
            "schema_version": "1.0",
            "tables": {
                "nonexistent_table": {"columns": ["a"], "rows": [[1]]},
            },
        }
        pack_path = tmp_path / "bad.json"
        pack_path.write_text(json.dumps(pack_data))

        conn = _create_full_db()
        result = import_asset_pack(conn, pack_path)
        assert result["tables"]["nonexistent_table"] == 0
