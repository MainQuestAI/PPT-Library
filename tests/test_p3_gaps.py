"""Tests for P3 Gaps: planner, fallback, diff-summary."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ppt_lib.planner import (
    DEFAULT_NARRATIVE_ROLES,
    _parse_roles_response,
    plan_narrative_roles,
)

# ─── _parse_roles_response unit tests ───────────────────────────────────────


def test_parse_pure_json():
    raw = '["opener", "problem", "solution"]'
    assert _parse_roles_response(raw) == ["opener", "problem", "solution"]


def test_parse_fenced_json():
    raw = '```json\n["opener", "case", "roi"]\n```'
    assert _parse_roles_response(raw) == ["opener", "case", "roi"]


def test_parse_with_extra_text():
    raw = 'Here is the result:\n["opener", "problem", "cta"]\nHope this helps!'
    assert _parse_roles_response(raw) == ["opener", "problem", "cta"]


def test_parse_filters_invalid_roles():
    raw = '["opener", "bogus", "roi", "filler"]'
    assert _parse_roles_response(raw) == ["opener", "roi"]


def test_parse_deduplicates():
    raw = '["opener", "opener", "roi", "roi"]'
    assert _parse_roles_response(raw) == ["opener", "roi"]


def test_parse_empty_array():
    raw = "[]"
    assert _parse_roles_response(raw) == []


def test_parse_garbage():
    raw = "Sorry, I can't do that."
    assert _parse_roles_response(raw) == []


# ─── plan_narrative_roles tests ──────────────────────────────────────────────


def test_plan_empty_brief_returns_fallback():
    """Empty brief should fallback without calling LLM."""

    class FakeSettings:
        cloud_vision_base_url = "http://localhost"
        openai_api_key = "x"
        vision_api_key = ""
        cloud_vision_model = "m"

    roles, source = plan_narrative_roles("", settings=FakeSettings())
    assert roles == list(DEFAULT_NARRATIVE_ROLES)
    assert source == "fallback"


def test_plan_llm_success():
    """Successful LLM call returns parsed roles with source='llm'."""

    class FakeSettings:
        cloud_vision_base_url = "http://localhost"
        openai_api_key = "x"
        vision_api_key = ""
        cloud_vision_model = "m"

    with patch("ppt_lib.planner.call_llm", return_value='["opener", "solution", "cta"]'):
        roles, source = plan_narrative_roles("客户想看AI解决方案", settings=FakeSettings())
    assert roles == ["opener", "solution", "cta"]
    assert source == "llm"


def test_plan_llm_failure_returns_fallback():
    """LLM error should fallback gracefully."""
    from ppt_lib.llm_client import LLMError

    class FakeSettings:
        cloud_vision_base_url = "http://localhost"
        openai_api_key = "x"
        vision_api_key = ""
        cloud_vision_model = "m"

    with patch("ppt_lib.planner.call_llm", side_effect=LLMError("timeout")):
        roles, source = plan_narrative_roles("brief text", settings=FakeSettings())
    assert roles == list(DEFAULT_NARRATIVE_ROLES)
    assert source == "fallback"


def test_plan_llm_empty_result_returns_fallback():
    """LLM returning empty array → fallback."""

    class FakeSettings:
        cloud_vision_base_url = "http://localhost"
        openai_api_key = "x"
        vision_api_key = ""
        cloud_vision_model = "m"

    with patch("ppt_lib.planner.call_llm", return_value="[]"):
        roles, source = plan_narrative_roles("some brief", settings=FakeSettings())
    assert roles == list(DEFAULT_NARRATIVE_ROLES)
    assert source == "fallback"


# ─── diff-summary.md tests ──────────────────────────────────────────────────


def test_diff_summary_written(tmp_path: Path):
    """compose() should write diff-summary.md in run directory."""
    from ppt_lib.composer import _write_diff_summary
    from ppt_lib.searcher import SearchResult
    from ppt_lib.selector import RoleSelection, SelectionReport

    # Create a fake SearchResult
    slide = SearchResult(
        slide_id=1,
        score=0.8,
        title="Test",
        text_summary="summary",
        source_file=Path("/x.pptx"),
        page_number=1,
        screenshot_path=None,
        source="index",
        confidence=0.8,
        metadata={},
    )
    report = SelectionReport(
        query="q",
        options={},
        roles=[
            RoleSelection(role="opener", slides=[slide], gap=False),
            RoleSelection(role="roi", slides=[], gap=True),
        ],
        total_slides=1,
        gaps=["roi"],
        timestamp="t",
    )
    manifest = {
        "slides": [
            {"source_file": "/x.pptx", "page_number": 1},
        ]
    }

    _write_diff_summary(tmp_path, report, manifest, "llm")

    summary = (tmp_path / "diff-summary.md").read_text(encoding="utf-8")
    assert "Plan Source: llm" in summary
    assert "opener" in summary
    assert "GAP" in summary
    assert "roi" in summary
    assert "/x.pptx" in summary


def test_diff_summary_fallback_source(tmp_path: Path):
    """diff-summary should show 'fallback' source correctly."""
    from ppt_lib.composer import _write_diff_summary
    from ppt_lib.selector import RoleSelection, SelectionReport

    report = SelectionReport(
        query="q", options={}, timestamp="t",
        roles=[RoleSelection(role="opener", slides=[], gap=True)],
        total_slides=0, gaps=["opener"],
    )
    _write_diff_summary(tmp_path, report, {"slides": []}, "fallback")

    summary = (tmp_path / "diff-summary.md").read_text(encoding="utf-8")
    assert "Plan Source: fallback" in summary
