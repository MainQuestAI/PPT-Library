from __future__ import annotations

import json
from pathlib import Path

from ppt_lib.cli import main
from ppt_lib.config import load_settings
from ppt_lib.contracts import get_registry
from ppt_lib.db import (
    PresentationRecord,
    connect,
    get_schema_version,
    init_db,
    upsert_library_source,
    upsert_presentation,
)


def test_status_exposes_structured_readiness_and_active_corpus_schema(
    tmp_path: Path,
    capsys,
) -> None:
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "embedding_provider": "fake",
            "embedding_dimensions": 1536,
        },
        config_path=tmp_path / "config.yml",
    )
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    assert get_schema_version(conn) == 6
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'presentation_source_links'"
    ).fetchone()
    conn.close()

    assert main(["--home-dir", str(tmp_path), "status", "--output", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    readiness = payload["readiness"]
    assert readiness["schema_version"] == "ppt_library_readiness.v1"
    assert readiness["runtime_ready"] is True
    assert readiness["active_corpus"]["source_count"] == 0
    assert readiness["overall_status"] == "blocked"
    assert "ACTIVE_SOURCE_EMPTY" in readiness["reason_codes"]
    assert get_registry().validate("readiness.v1", readiness) == []


def test_existing_v6_database_backfills_source_links(tmp_path: Path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "fake"},
        config_path=tmp_path / "config.yml",
    )
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)

    library_root = tmp_path / "library"
    library_root.mkdir()
    upsert_library_source(
        conn,
        str(library_root),
        source_type="library",
        metadata_json={"path": str(library_root)},
    )
    upsert_presentation(
        conn,
        PresentationRecord(
            path=library_root / "deck.pptx",
            filename="deck.pptx",
            project_name="project",
            slide_count=1,
            content_hash="deck",
            file_size=1,
            file_mtime=1.0,
        ),
    )

    init_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM presentation_source_links").fetchone()[0] == 1
    conn.close()
