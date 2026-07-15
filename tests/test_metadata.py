from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide
from ppt_lib.metadata import import_metadata_jsonl


def test_import_metadata_refreshes_fts_fields(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.db")
    init_db(conn)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="hash",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Case",
            text_content="customer evidence",
            embedding=np.ones(3, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    metadata_path = tmp_path / "metadata.jsonl"
    metadata_path.write_text(
        json.dumps(
            {
                "slide_id": slide_id,
                "industry": "retail",
                "scenario": "renewal",
                "narrative_role": "case",
                "quality_rating": 4,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_metadata_jsonl(conn, metadata_path)

    assert result == {"imported": 1, "skipped": 0, "updated_slide_ids": [slide_id]}
    fts_row = conn.execute(
        "SELECT narrative_role, industry, scenario FROM slides_fts WHERE legacy_slide_id = ?",
        (str(slide_id),),
    ).fetchone()
    assert fts_row == ("case", "retail", "renewal")
