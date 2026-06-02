from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.config import load_settings
from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide
from ppt_lib.selector import build_manifest_from_selection, select_slides, select_slides_from_plan


class StaticProvider:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector.astype(np.float32)
        self.model = "static"
        self.dimensions = int(self.vector.shape[0])

    def encode(self, text: str) -> np.ndarray:
        return self.vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


class KeywordProvider:
    model = "keyword"
    dimensions = 1536

    def encode(self, text: str) -> np.ndarray:
        vector = np.zeros(1536, dtype=np.float32)
        if "opener" in text or "introduction" in text:
            vector[0] = 1.0
        elif "roi" in text or "return" in text:
            vector[1] = 1.0
        else:
            vector[2] = 1.0
        return vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


def _seed_slide(
    tmp_path: Path,
    title: str,
    role: str,
    *,
    industry: str = "retail",
    slide_index: int = 0,
    embedding: np.ndarray | None = None,
    text_content: str | None = None,
) -> int:
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
            slide_index=slide_index,
            title=title,
            text_content=text_content or f"{title} {industry} solution evidence",
            embedding=(embedding if embedding is not None else np.ones(1536, dtype=np.float32)),
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


def test_select_slides_returns_per_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    _seed_slide(tmp_path, "opener_b", "opener")
    _seed_slide(tmp_path, "case_a", "case")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    report = select_slides(settings, roles=["opener", "case"], max_per_role=2)

    assert report.total_slides == 3
    assert report.gaps == []
    role_map = {selection.role: selection for selection in report.roles}
    assert len(role_map["opener"].slides) == 2
    assert len(role_map["case"].slides) == 1


def test_select_slides_detects_gaps_and_validates_roles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    report = select_slides(settings, roles=["opener", "roi"], max_per_role=1)

    assert report.total_slides == 1
    assert report.gaps == ["roi"]
    with pytest.raises(ValueError, match="Invalid narrative role"):
        select_slides(settings, roles=["invalid_role"])


def test_select_slides_filters_industry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(tmp_path, "retail_case", "case", industry="retail")
    _seed_slide(tmp_path, "finance_case", "case", industry="finance")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    report = select_slides(settings, roles=["case"], industry="retail", max_per_role=5)

    assert [slide.title for slide in report.roles[0].slides] == ["retail_case"]


def test_select_slides_industry_filter_considers_all_role_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(tmp_path, "finance_case_a", "case", industry="finance")
    _seed_slide(tmp_path, "finance_case_b", "case", industry="finance", slide_index=1)
    _seed_slide(tmp_path, "finance_case_c", "case", industry="finance", slide_index=2)
    _seed_slide(tmp_path, "retail_case", "case", industry="retail", slide_index=3)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    report = select_slides(settings, roles=["case"], industry="retail", max_per_role=3)

    assert report.gaps == []
    assert [slide.title for slide in report.roles[0].slides] == ["retail_case"]


def test_select_slides_from_plan_uses_each_beat_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(
        tmp_path,
        "opener_match",
        "opener",
        embedding=np.r_[1.0, np.zeros(1535)].astype(np.float32),
        text_content="opener introduction",
    )
    _seed_slide(
        tmp_path,
        "roi_match",
        "roi",
        embedding=np.r_[0.0, 1.0, np.zeros(1534)].astype(np.float32),
        text_content="roi return",
    )
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: KeywordProvider())
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "beats": [
                    {"role": "opener", "brief": "introduction"},
                    {"role": "roi", "brief": "return on investment"},
                ]
            }
        ),
        encoding="utf-8",
    )

    report = select_slides_from_plan(settings, plan_path=plan_path, threshold=0.8, max_per_role=1)

    assert report.gaps == []
    assert [selection.slides[0].title for selection in report.roles] == ["opener_match", "roi_match"]


def test_build_manifest_from_selection_uses_top_slide_per_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opener_id = _seed_slide(tmp_path, "opener_a", "opener")
    case_id = _seed_slide(tmp_path, "case_a", "case")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))
    report = select_slides(settings, roles=["opener", "case"], max_per_role=1)

    manifest = build_manifest_from_selection(
        report,
        run_name="auto-compose",
        output_path=str(tmp_path / "output.pptx"),
        overwrite=True,
    )

    assert manifest["run_name"] == "auto-compose"
    assert manifest["output"]["overwrite"] is True
    assert [slide["source_slide_id"] for slide in manifest["slides"]] == [opener_id, case_id]
    assert manifest["gaps"] == []


def test_build_manifest_topn_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: top2-per-role should select up to 2 slides per role."""
    _seed_slide(tmp_path, "opener_a", "opener")
    _seed_slide(tmp_path, "opener_b", "opener", slide_index=1)
    _seed_slide(tmp_path, "case_a", "case")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))
    report = select_slides(settings, roles=["opener", "case"], max_per_role=3)

    manifest = build_manifest_from_selection(report, strategy="top2-per-role", run_name="test")
    slides = manifest["slides"]
    assert len(slides) == 3  # 2 openers + 1 case


def test_build_manifest_topn_strategy_invalid() -> None:
    """D1: invalid strategy format raises ValueError."""
    from ppt_lib.selector import SelectionReport
    report = SelectionReport(query="x", options={}, roles=[], total_slides=0, gaps=[], timestamp="")
    with pytest.raises(ValueError, match="Unsupported strategy"):
        build_manifest_from_selection(report, strategy="random")


def test_build_manifest_top3_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: top3-per-role works."""
    _seed_slide(tmp_path, "opener_a", "opener")
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))
    report = select_slides(settings, roles=["opener"], max_per_role=3)

    # top3 but only 1 slide available — should not error
    manifest = build_manifest_from_selection(report, strategy="top3-per-role", run_name="test")
    assert len(manifest["slides"]) == 1


def test_build_manifest_top_n_strategy_keeps_all_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_slide(tmp_path, "opener_a", "opener")
    _seed_slide(tmp_path, "opener_b", "opener", slide_index=1)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))
    report = select_slides(settings, roles=["opener"], max_per_role=2)

    manifest = build_manifest_from_selection(report, strategy="top-n", run_name="test")

    assert len(manifest["slides"]) == 2
