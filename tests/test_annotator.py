"""Tests for ppt_lib.annotator module."""

from __future__ import annotations

import json
from unittest.mock import patch as mock_patch

import pytest

from ppt_lib.annotator import (
    AnnotationResult,
    annotate_batch,
    build_annotation_prompt,
    load_unannotated_slides,
    parse_annotation_response,
    write_annotations,
)
from ppt_lib.db import connect, init_db
from ppt_lib.settings import Settings


@pytest.fixture()
def db_with_slides(tmp_path):
    """Create a DB with some test slides."""
    db_path = tmp_path / "index.db"
    conn = connect(db_path)
    init_db(conn)
    # Insert a presentation
    conn.execute(
        "INSERT INTO presentations (id, path, filename, content_hash, slide_count) VALUES (1, '/test.pptx', 'test.pptx', 'abc123', 3)"
    )
    # Insert slides without annotations
    for i in range(1, 4):
        conn.execute(
            """
            INSERT INTO slides (id, presentation_id, slide_index, text_content, source, metadata_json)
            VALUES (?, 1, ?, ?, 'text_extraction', ?)
            """,
            (i, i, f"Slide {i} about retail digital transformation", json.dumps({"vision_description": f"A diagram showing step {i}"})),
        )
    conn.commit()
    return conn, db_path


def test_build_annotation_prompt_includes_content():
    prompt = build_annotation_prompt("Hello World", "A greeting slide")
    assert "Hello World" in prompt
    assert "A greeting slide" in prompt
    assert "narrative_role" in prompt
    assert "industry" in prompt


def test_build_annotation_prompt_truncates_long_content():
    long_text = "x" * 5000
    prompt = build_annotation_prompt(long_text)
    assert "...(truncated)" in prompt
    assert len(prompt) < 10000


def test_parse_annotation_response_valid_json():
    resp = '{"narrative_role": "opener", "industry": "retail", "scenario": "pitch"}'
    result = parse_annotation_response(resp)
    assert result["narrative_role"] == "opener"
    assert result["industry"] == "retail"
    assert result["scenario"] == "pitch"


def test_parse_annotation_response_with_markdown_block():
    resp = '```json\n{"narrative_role": "solution", "industry": "technology", "scenario": "proposal"}\n```'
    result = parse_annotation_response(resp)
    assert result["narrative_role"] == "solution"
    assert result["industry"] == "technology"


def test_parse_annotation_response_invalid_values_fallback():
    resp = '{"narrative_role": "unknown_role", "industry": "unknown_ind", "scenario": "unknown_scen"}'
    result = parse_annotation_response(resp)
    assert result["narrative_role"] == "appendix"  # fallback
    assert result["industry"] == "cross_industry"  # fallback
    assert result["scenario"] == "general"  # fallback


def test_parse_annotation_response_invalid_json():
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_annotation_response("not json at all")


def test_load_unannotated_slides(db_with_slides):
    conn, _ = db_with_slides
    slides = load_unannotated_slides(conn)
    assert len(slides) == 3
    assert slides[0]["slide_id"] == 1
    assert "retail" in slides[0]["text_content"]
    assert "diagram" in slides[0]["vision_description"]


def test_load_unannotated_slides_skips_annotated(db_with_slides):
    conn, _ = db_with_slides
    conn.execute("UPDATE slides SET narrative_role = 'opener' WHERE id = 1")
    conn.commit()
    slides = load_unannotated_slides(conn)
    assert len(slides) == 2
    assert all(s["slide_id"] != 1 for s in slides)


def test_load_unannotated_slides_force(db_with_slides):
    conn, _ = db_with_slides
    conn.execute("UPDATE slides SET narrative_role = 'opener' WHERE id = 1")
    conn.commit()
    slides = load_unannotated_slides(conn, force=True)
    assert len(slides) == 3


def test_load_unannotated_slides_limit(db_with_slides):
    conn, _ = db_with_slides
    slides = load_unannotated_slides(conn, limit=2)
    assert len(slides) == 2


def test_write_annotations(db_with_slides):
    conn, _ = db_with_slides
    results = [
        AnnotationResult(slide_id=1, narrative_role="opener", industry="retail", scenario="pitch"),
        AnnotationResult(slide_id=2, narrative_role="case", industry="fmcg", scenario="proposal"),
    ]
    count = write_annotations(conn, results)
    assert count == 2

    row = conn.execute("SELECT narrative_role, industry, scenario FROM slides WHERE id = 1").fetchone()
    assert row == ("opener", "retail", "pitch")

    row2 = conn.execute("SELECT narrative_role, industry, scenario FROM slides WHERE id = 2").fetchone()
    assert row2 == ("case", "fmcg", "proposal")


def test_annotate_batch_dry_run(db_with_slides):
    conn, db_path = db_with_slides
    settings = Settings(home_dir=db_path.parent, db_path=db_path, embedding_provider="fake")

    mock_response = '{"narrative_role": "opener", "industry": "retail", "scenario": "pitch"}'

    with mock_patch("ppt_lib.annotator._call_lmstudio", return_value=mock_response):
        batch = annotate_batch(conn, settings, batch_size=3, provider="lmstudio", dry_run=True)

    assert len(batch.results) == 3
    assert batch.results[0].narrative_role == "opener"
    assert len(batch.errors) == 0

    # Verify DB NOT written (dry run)
    row = conn.execute("SELECT narrative_role FROM slides WHERE id = 1").fetchone()
    assert row[0] is None


def test_call_lmstudio_delegates_to_llm_client(db_with_slides):
    """D3: _call_lmstudio delegates to llm_client.call_lmstudio."""
    _, db_path = db_with_slides
    settings = Settings(home_dir=db_path.parent, db_path=db_path, embedding_provider="fake")

    mock_response = '{"narrative_role": "opener", "industry": "retail", "scenario": "pitch"}'

    with mock_patch("ppt_lib.llm_client.call_lmstudio", return_value=mock_response) as mock_fn:
        from ppt_lib.annotator import _call_lmstudio
        result = _call_lmstudio("test prompt", settings)

    mock_fn.assert_called_once_with("test prompt", settings)
    assert result == mock_response


def test_annotate_batch_writes_to_db(db_with_slides):
    conn, db_path = db_with_slides
    settings = Settings(home_dir=db_path.parent, db_path=db_path, embedding_provider="fake")

    mock_response = '{"narrative_role": "solution", "industry": "technology", "scenario": "proposal"}'

    with mock_patch("ppt_lib.annotator._call_lmstudio", return_value=mock_response):
        batch = annotate_batch(conn, settings, batch_size=3, provider="lmstudio", dry_run=False)

    assert len(batch.results) == 3

    # Verify DB written
    row = conn.execute("SELECT narrative_role, industry, scenario FROM slides WHERE id = 1").fetchone()
    assert row == ("solution", "technology", "proposal")


def test_annotate_batch_handles_provider_error(db_with_slides):
    conn, db_path = db_with_slides
    settings = Settings(home_dir=db_path.parent, db_path=db_path, embedding_provider="fake")

    def failing_llm(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    with mock_patch("ppt_lib.annotator._call_lmstudio", side_effect=failing_llm):
        with mock_patch("ppt_lib.annotator._call_llm", side_effect=failing_llm):
            batch = annotate_batch(conn, settings, batch_size=3, provider="auto", dry_run=True)

    # All should fail
    assert len(batch.results) == 0
    assert len(batch.errors) == 3


def test_cli_annotate_dry_run(tmp_path, monkeypatch, capsys):
    """Test CLI annotate --dry-run."""
    db_path = tmp_path / "index.db"
    conn = connect(db_path)
    init_db(conn)
    conn.execute("INSERT INTO presentations (id, path, filename, content_hash, slide_count) VALUES (1, '/t.pptx', 't.pptx', 'h', 1)")
    conn.execute(
        """
        INSERT INTO slides (id, presentation_id, slide_index, text_content, source)
        VALUES (1, 1, 1, 'test slide', 'text_extraction')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("PPT_LIBRARY_HOME", str(tmp_path))

    mock_response = '{"narrative_role": "case", "industry": "retail", "scenario": "pitch"}'
    with mock_patch("ppt_lib.annotator._call_lmstudio", return_value=mock_response):
        from ppt_lib.cli import main
        result = main(["annotate", "--dry-run", "--provider", "lmstudio", "--batch", "10"])

    # CLI should succeed
    assert result is None or result == 0
