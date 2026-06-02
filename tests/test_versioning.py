from __future__ import annotations

from pathlib import Path

import numpy as np

from ppt_lib.config import load_settings
from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide
from ppt_lib.versioning import enrich_pending_decks, get_version_status, inspect_deck_family, recompute_deck_versions


def seed_deck(
    tmp_path: Path,
    filename: str,
    *,
    mtime: float,
    texts: list[str] | None = None,
    project_name: str = "星河商学院",
) -> int:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    texts = texts or ["星河商学院 数字化转型方案", "业务架构与内容中台方案", "下一步共创计划"]
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / project_name / filename,
            filename=filename,
            project_name=project_name,
            slide_count=len(texts),
            content_hash=filename,
            file_size=100 + len(filename),
            file_mtime=mtime,
        ),
    )
    for index, text in enumerate(texts):
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=index,
                title=text if index == 0 else None,
                text_content=text,
                embedding=np.r_[1.0, np.zeros(1535)].astype(np.float32),
                screenshot_hash=f"{filename}-{index}" if index == 1 else None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
    return presentation_id


def test_recompute_groups_many_project_versions_into_one_family(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    for index in range(1, 31):
        seed_deck(tmp_path, f"星河商学院数字化方案_v{index}.pptx", mtime=float(index))
    result = recompute_deck_versions(conn)

    assert result.presentation_count == 30
    assert result.family_count == 1
    assert result.representative_count == 1
    family_id = conn.execute("SELECT id FROM deck_families").fetchone()[0]
    family = inspect_deck_family(conn, family_id)
    assert family is not None
    assert len(family["versions"]) == 30
    assert family["versions"][0]["filename"] == "星河商学院数字化方案_v30.pptx"


def test_representative_version_prefers_final_over_later_draft(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    final_id = seed_deck(tmp_path, "星河商学院数字化方案_终稿.pptx", mtime=1.0)
    seed_deck(tmp_path, "星河商学院数字化方案_草稿_20240510.pptx", mtime=9_999.0)

    recompute_deck_versions(conn)

    representative = conn.execute(
        "SELECT presentation_id FROM presentation_versions WHERE is_representative = 1"
    ).fetchone()[0]
    assert representative == final_id


def test_recompute_dry_run_does_not_write_version_tables(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    seed_deck(tmp_path, "星河商学院数字化方案_20240510.pptx", mtime=1.0)

    result = recompute_deck_versions(conn, dry_run=True)
    status = get_version_status(conn)

    assert result.dry_run is True
    assert status.family_count == 0
    assert status.presentation_version_count == 0


def test_enrich_pending_decks_writes_deck_insight_and_slide_importance(tmp_path: Path) -> None:
    seed_deck(tmp_path, "星河商学院数字化方案_final.pptx", mtime=1.0)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")

    result = enrich_pending_decks(settings, limit=1)

    conn = connect(settings.db_path)
    init_db(conn)
    assert result.processed == 1
    assert conn.execute("SELECT COUNT(*) FROM deck_insights").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slide_importance").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM slide_importance WHERE needs_visual = 1").fetchone()[0] >= 1
