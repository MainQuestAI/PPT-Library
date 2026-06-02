"""E2E tests for Phase 3: compose → assemble → ingest → search full loop."""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np

from ppt_lib.config import load_settings
from ppt_lib.db import (
    PresentationRecord,
    SlideRecord,
    connect,
    init_db,
    insert_deal,
    recompute_slide_stats,
    upsert_presentation,
    upsert_slide,
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


def _write_minimal_pptx(path: Path) -> Path:
    """Create a minimal valid pptx file with 1 slide."""
    with zipfile.ZipFile(path, "w") as archive:
        slide_ids = '<p:sldId id="256" r:id="rId1" />'
        pres_xml = (
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
            "</p:presentation>"
        )
        archive.writestr("ppt/presentation.xml", pres_xml)
        rels = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            'Target="slides/slide1.xml" />'
            "</Relationships>"
        )
        archive.writestr("ppt/_rels/presentation.xml.rels", rels)
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld />")
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", b"<Relationships />")
    return path


def _seed_with_real_pptx(tmp_path: Path) -> dict[str, int]:
    """Seed DB with slides backed by real pptx files."""
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)

    slide_ids = {}
    for title, role in [("opener_slide", "opener"), ("case_slide", "case"), ("solution_slide", "solution")]:
        pptx_path = tmp_path / f"{title}.pptx"
        _write_minimal_pptx(pptx_path)

        pres_id = upsert_presentation(
            conn,
            PresentationRecord(
                path=pptx_path,
                filename=f"{title}.pptx",
                project_name="project",
                slide_count=1,
                content_hash=title,
                file_size=pptx_path.stat().st_size,
                file_mtime=pptx_path.stat().st_mtime,
            ),
        )
        slide_id = upsert_slide(
            conn,
            SlideRecord(
                presentation_id=pres_id,
                slide_index=0,
                title=title,
                text_content=f"{title} retail digital transformation evidence",
                embedding=np.ones(1536, dtype=np.float32),
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
        conn.execute("UPDATE slides SET narrative_role = ?, industry = ? WHERE id = ?", (role, "retail", slide_id))
        slide_ids[role] = int(slide_id)

    conn.commit()
    conn.close()
    return slide_ids


# --- D1: compose → assemble → verify outputs ---

def test_e2e_compose_to_assemble(tmp_path: Path, monkeypatch) -> None:
    """E2E: compose --roles → assemble → output.pptx exists."""
    _seed_with_real_pptx(tmp_path)
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))
    # Patch screenshot rendering (no LibreOffice in test)
    monkeypatch.setattr("ppt_lib.assembler._render_screenshots", lambda *a, **kw: type("R", (), {"screenshot_count": 0, "warnings": []})())

    from ppt_lib.composer import compose
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")

    result = compose(
        settings,
        roles=["opener", "case"],
        brief="retail digital transformation",
        dry_run=False,
        overwrite=True,
    )

    assert result.assemble_report is not None
    assert result.assemble_report.status in ("completed", "completed_with_warnings", "passed")
    assert result.assemble_report.slide_count == 2
    assert result.assemble_report.output_path.exists()
    assert (result.run_dir / "selection-report.json").exists()
    assert (result.run_dir / "manifest.json").exists()


# --- D2: compose --deal-id → usage → recompute → win_rate ---

def test_e2e_compose_usage_loop(tmp_path: Path, monkeypatch) -> None:
    """E2E: compose --deal-id → select → usage written → recompute → cache updated."""
    slide_ids = _seed_with_real_pptx(tmp_path)
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))
    monkeypatch.setattr("ppt_lib.assembler._render_screenshots", lambda *a, **kw: type("R", (), {"screenshot_count": 0, "warnings": []})())

    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")

    # Create a deal
    conn = connect(settings.db_path)
    init_db(conn)
    deal_id = insert_deal(conn, deal_name="e2e-test-deal", outcome="won")
    conn.commit()
    conn.close()

    from ppt_lib.composer import compose
    result = compose(
        settings,
        roles=["opener", "case"],
        brief="retail",
        dry_run=False,
        overwrite=True,
        deal_id=deal_id,
    )

    assert result.assemble_report is not None

    # Verify usage was recorded
    conn = connect(settings.db_path)
    usage_rows = conn.execute("SELECT slide_id, deal_id FROM slide_usage").fetchall()
    assert len(usage_rows) >= 2  # opener + case

    # Recompute and verify cache fields updated
    recompute_slide_stats(conn)
    conn.commit()

    opener_id = slide_ids["opener"]
    row = conn.execute("SELECT won_count, reuse_count FROM slides WHERE id = ?", (opener_id,)).fetchone()
    conn.close()

    assert row is not None
    assert row[0] >= 1  # won_count >= 1 (deal outcome = won)
    assert row[1] >= 1  # reuse_count >= 1


# --- Verify compose two-step workflow (dry-run then confirm) ---

def test_e2e_compose_two_step(tmp_path: Path, monkeypatch) -> None:
    """E2E: compose --dry-run → review plan → compose --confirm."""
    _seed_with_real_pptx(tmp_path)
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))
    monkeypatch.setattr("ppt_lib.assembler._render_screenshots", lambda *a, **kw: type("R", (), {"screenshot_count": 0, "warnings": []})())

    from ppt_lib.composer import compose, compose_confirm
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")

    # Step 1: dry-run
    dry_result = compose(settings, roles=["opener", "solution"], brief="retail", dry_run=True)
    assert dry_result.dry_run is True
    assert dry_result.assemble_report is None
    plan_path = dry_result.run_dir / "narrative-plan.json"
    assert plan_path.exists()

    # Step 2: confirm
    confirm_result = compose_confirm(settings, plan_path=plan_path, overwrite=True)
    assert confirm_result.dry_run is False
    assert confirm_result.assemble_report is not None
    assert confirm_result.assemble_report.slide_count >= 1
