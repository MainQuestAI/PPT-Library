"""Focused tests for the Deck Master selection v2 bridge."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np

from ppt_lib.cli import main
from ppt_lib.contracts import get_registry
from ppt_lib.db import (
    PresentationRecord,
    ScreenshotRecord,
    SlideRecord,
    connect,
    init_db,
    insert_screenshot,
    sync_presentation_source_links,
    upsert_library_source,
    upsert_presentation,
    upsert_slide,
)
from ppt_lib.deck_master_bridge import (
    DeckMasterBridgeError,
    build_deck_master_selection_v2,
    write_selection_v2_atomic,
)
from ppt_lib.settings import Settings


class StaticProvider:
    dimensions = 1536

    def encode(self, text: str) -> np.ndarray:
        return np.ones(self.dimensions, dtype=np.float32)


def _seed_library(tmp_path: Path) -> tuple[Settings, int]:
    settings = Settings(home_dir=tmp_path, embedding_provider="fake", embedding_dimensions=1536)
    assert settings.db_path is not None
    source_root = tmp_path / "active-source"
    source_root.mkdir()
    deck_path = source_root / "deck.pptx"
    deck_path.write_bytes(b"synthetic deck")

    conn = connect(settings.db_path)
    init_db(conn)
    upsert_library_source(
        conn,
        str(source_root),
        source_type="library",
        metadata_json={"path": str(source_root)},
    )
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=deck_path,
            filename=deck_path.name,
            project_name="active-source",
            slide_count=1,
            content_hash="a" * 64,
            file_size=deck_path.stat().st_size,
            file_mtime=deck_path.stat().st_mtime,
        ),
    )
    sync_presentation_source_links(conn, presentation_id, deck_path)

    screenshot_path = tmp_path / "screenshots" / "slide.png"
    screenshot_path.parent.mkdir()
    screenshot_path.write_bytes(b"png")
    screenshot_hash = "b" * 64
    insert_screenshot(conn, ScreenshotRecord(screenshot_hash, screenshot_path, 100, 100))
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Opening",
            text_content="opening solution overview",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=screenshot_hash,
            source="vision_model",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    conn.execute("UPDATE slides SET narrative_role = ? WHERE id = ?", ("opener", slide_id))
    conn.commit()
    conn.close()
    return settings, slide_id


def _write_plan(path: Path, run_id: str = "run-001") -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "deck_master_ppt_library_bridge_plan.v1",
                "run_id": run_id,
                "requests": [
                    {
                        "beat_id": "beat-001",
                        "page_task_id": "page-001",
                        "query_trace_id": "trace-001",
                        "role_original": "solution_overview",
                        "role_strategy": "mapped",
                        "role_mapped": "opener",
                        "query": "opening solution overview",
                        "reuse_policy": "reuse_or_adapt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_selection_v2_is_valid_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    settings, slide_id = _seed_library(tmp_path)
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider())

    payload = build_deck_master_selection_v2(
        settings,
        plan_path=_write_plan(tmp_path / "bridge-plan.json"),
        run_id="run-001",
        max_per_role=3,
        ranking="classic",
        threshold=0.0,
    )

    assert payload["identity_scope"] == "ppt_library_database_lifecycle"
    assert get_registry().validate("deck-master-selection.v2", payload) == []
    candidate = payload["selections"][0]["candidates"][0]
    assert candidate["slide_id"] == slide_id
    assert candidate["candidate_origin"] == "ppt_library"

    output_path = tmp_path / "selection.json"
    assert write_selection_v2_atomic(output_path, payload) == "written"
    repeated = deepcopy(payload)
    repeated["generated_at"] = "later"
    assert write_selection_v2_atomic(output_path, repeated) == "unchanged"

    changed = deepcopy(payload)
    changed["gaps"] = ["beat-001"]
    try:
        write_selection_v2_atomic(output_path, changed)
    except DeckMasterBridgeError as exc:
        assert exc.code == "CONTRACT_IDEMPOTENCY_CONFLICT"
    else:
        raise AssertionError("changed payload must require explicit replacement")

    assert write_selection_v2_atomic(output_path, changed, replace_existing=True) == "replaced"


def test_cli_v2_writes_contract_and_reports_unchanged(tmp_path: Path, monkeypatch, capsys) -> None:
    _seed_library(tmp_path)
    (tmp_path / "config.yml").write_text(
        "embedding_provider: fake\nembedding_dimensions: 1536\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider())
    plan = _write_plan(tmp_path / "bridge-plan.json")
    output = tmp_path / "selection.json"
    args = [
        "--home-dir",
        str(tmp_path),
        "select-slides",
        "--contract",
        "deck-master.v2",
        "--run-id",
        "run-001",
        "--plan",
        str(plan),
        "--scope",
        "active",
        "--threshold",
        "0",
        "--output",
        str(output),
    ]

    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["write_status"] == "written"
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["write_status"] == "unchanged"
