"""Tests for Phase 3 select-slides enhancements: --plan, --output, --record-usage, top-n strategy."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.config import load_settings
from ppt_lib.db import (
    PresentationRecord,
    SlideRecord,
    connect,
    init_db,
    insert_deal,
    upsert_presentation,
    upsert_slide,
)
from ppt_lib.selector import (
    SelectionReport,
    record_selection_usage,
    select_slides,
    select_slides_from_plan,
)


class StaticProvider:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector.astype(np.float32)
        self.model = "static"
        self.dimensions = int(self.vector.shape[0])

    def encode(self, text: str) -> np.ndarray:
        return self.vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


def _seed_slide(tmp_path: Path, title: str, role: str, *, industry: str = "retail") -> int:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / f"{title}.pptx",
            filename=f"{title}.pptx",
            project_name="project",
            slide_count=1,
            content_hash=title,
            file_size=100,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id,
            slide_index=0,
            title=title,
            text_content=f"{title} {industry} solution evidence",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    conn.execute("UPDATE slides SET narrative_role = ?, industry = ? WHERE id = ?", (role, industry, slide_id))
    conn.commit()
    conn.close()
    return int(slide_id)


# --- SelectionReport metadata ---

def test_selection_report_contains_metadata(tmp_path: Path, monkeypatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    report = select_slides(settings, roles=["opener"], brief="test query", max_per_role=1)

    assert report.query == "test query"
    assert report.options["roles"] == ["opener"]
    assert report.timestamp  # non-empty ISO string


# --- select_slides_from_plan ---

def test_select_slides_from_plan_simple_roles(tmp_path: Path, monkeypatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    _seed_slide(tmp_path, "case_a", "case")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    plan = {"roles": ["opener", "case"]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    report = select_slides_from_plan(settings, plan_path=plan_path, max_per_role=1)

    assert report.total_slides == 2
    assert report.gaps == []


def test_select_slides_from_plan_beats_format(tmp_path: Path, monkeypatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    plan = {"beats": [{"role": "opener", "brief": "introduction"}, {"role": "roi", "brief": "ROI evidence"}]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    report = select_slides_from_plan(settings, plan_path=plan_path, max_per_role=1)

    assert report.total_slides == 1
    assert "roi" in report.gaps


def test_select_slides_from_plan_invalid_format(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    plan_path = tmp_path / "bad.json"
    plan_path.write_text(json.dumps({"no_roles": True}), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain 'roles' or 'beats'"):
        select_slides_from_plan(settings, plan_path=plan_path)


# --- record_selection_usage ---

def test_record_selection_usage_writes_to_db(tmp_path: Path, monkeypatch) -> None:
    opener_id = _seed_slide(tmp_path, "opener_a", "opener")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    # Create a deal first
    conn = connect(settings.db_path)
    init_db(conn)
    deal_id = insert_deal(conn, deal_name="test-deal", outcome="pending")
    conn.commit()
    conn.close()

    report = select_slides(settings, roles=["opener"], max_per_role=1)
    assert report.total_slides == 1

    count = record_selection_usage(settings, report, deal_id=deal_id)
    assert count == 1

    # Verify in DB
    conn = connect(settings.db_path)
    row = conn.execute("SELECT slide_id, deal_id, position FROM slide_usage").fetchone()
    conn.close()
    assert row[0] == opener_id
    assert row[1] == deal_id
    assert row[2] == 1


# --- CLI --output flag ---

def test_cli_select_slides_output_file(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main
    from ppt_lib.selector import RoleSelection

    monkeypatch.setattr(
        "ppt_lib.cli.select_slides",
        lambda settings, **kwargs: SelectionReport(
            query="test", options={"roles": ["case"]},
            roles=[RoleSelection("case", [], True)],
            total_slides=0, gaps=["case"],
            timestamp="2026-05-25T00:00:00+00:00",
        ),
    )

    out_file = tmp_path / "output" / "selection.json"
    exit_code = main(["--home-dir", str(tmp_path), "select-slides", "--roles", "case", "--brief", "test", "--output", str(out_file)])

    assert exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["report"]["gaps"] == ["case"]


# --- CLI --plan flag ---

def test_cli_select_slides_plan_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main
    from ppt_lib.selector import RoleSelection

    monkeypatch.setattr(
        "ppt_lib.cli.select_slides_from_plan",
        lambda settings, **kwargs: SelectionReport(
            query="from plan", options={"roles": ["opener"]},
            roles=[RoleSelection("opener", [], True)],
            total_slides=0, gaps=["opener"],
            timestamp="2026-05-25T00:00:00+00:00",
        ),
    )

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({"roles": ["opener"]}), encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path), "select-slides", "--plan", str(plan_file), "--brief", "test"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["report"]["gaps"] == ["opener"]


# --- build-manifest top-n strategy ---

def test_cli_build_manifest_top_n_strategy(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main

    selection = {
        "report": {
            "roles": [
                {
                    "role": "case",
                    "slides": [
                        {"slide_id": 1, "source_file": "/a.pptx", "page_number": 1, "title": "Case A"},
                        {"slide_id": 2, "source_file": "/b.pptx", "page_number": 2, "title": "Case B"},
                        {"slide_id": 3, "source_file": "/c.pptx", "page_number": 3, "title": "Case C"},
                    ],
                    "gap": False,
                }
            ],
            "gaps": [],
        }
    }
    sel_file = tmp_path / "selection.json"
    sel_file.write_text(json.dumps(selection), encoding="utf-8")

    # top1-per-role: only 1 slide
    exit_code = main(["--home-dir", str(tmp_path), "build-manifest", "--selection", str(sel_file), "--strategy", "top1-per-role"])
    assert exit_code == 0
    payload1 = json.loads(capsys.readouterr().out)
    assert payload1["slide_count"] == 1

    # top-n: all 3 slides
    exit_code = main(["--home-dir", str(tmp_path), "build-manifest", "--selection", str(sel_file), "--strategy", "top-n"])
    assert exit_code == 0
    payload_n = json.loads(capsys.readouterr().out)
    assert payload_n["slide_count"] == 3

    # top2-per-role: first 2 slides
    exit_code = main(["--home-dir", str(tmp_path), "build-manifest", "--selection", str(sel_file), "--strategy", "top2-per-role"])
    assert exit_code == 0
    payload2 = json.loads(capsys.readouterr().out)
    assert payload2["slide_count"] == 2
