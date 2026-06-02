"""Tests for --context search parameter (P2-C2)."""

from __future__ import annotations

import numpy as np

from ppt_lib.searcher import (
    SearchOptions,
    _context_score,
    _ContextHints,
    _final_score,
    _parse_context,
)


class TestParseContext:
    """Test _parse_context keyword extraction."""

    def test_empty_context_returns_none(self):
        assert _parse_context("") is None
        assert _parse_context("   ") is None

    def test_unrecognized_context_returns_none(self):
        assert _parse_context("hello world") is None

    def test_industry_english_label(self):
        hints = _parse_context("retail pitch scenario")
        assert hints is not None
        assert "retail" in hints.industries
        assert "pitch" in hints.scenarios

    def test_industry_chinese_alias(self):
        hints = _parse_context("制造业大客户")
        assert hints is not None
        assert "manufacturing" in hints.industries

    def test_scenario_chinese_alias(self):
        hints = _parse_context("售前拜访")
        assert hints is not None
        assert "pitch" in hints.scenarios

    def test_multiple_matches(self):
        hints = _parse_context("零售行业培训方案")
        assert hints is not None
        assert "retail" in hints.industries
        assert "training" in hints.scenarios
        assert "proposal" in hints.scenarios

    def test_case_insensitive(self):
        hints = _parse_context("Retail Pitch")
        assert hints is not None
        assert "retail" in hints.industries
        assert "pitch" in hints.scenarios

    def test_mixed_chinese_english(self):
        hints = _parse_context("beauty case_study")
        assert hints is not None
        assert "beauty" in hints.industries
        assert "case_study" in hints.scenarios

    def test_finance_aliases(self):
        for keyword in ("金融", "银行", "保险"):
            hints = _parse_context(keyword)
            assert hints is not None, f"failed for {keyword}"
            assert "finance" in hints.industries

    def test_real_estate_alias(self):
        hints = _parse_context("房地产")
        assert hints is not None
        assert "real_estate" in hints.industries


class TestContextScore:
    """Test _context_score boosting logic."""

    def _make_row(self, industry=None, scenario=None):
        """Helper to create a mock row with metadata."""
        return {
            "slide_id": 1,
            "title": "test",
            "text_content": "test",
            "embedding": np.zeros(4, dtype=np.float32),
            "screenshot_hash": None,
            "source": "vision",
            "metadata": {
                "industry": industry,
                "scenario": scenario,
                "narrative_role": None,
                "origin_type": "original",
                "win_rate": None,
                "won_count": 0,
                "lost_count": 0,
                "reuse_count": 0,
                "last_deal_outcome": None,
            },
            "slide_index": 0,
            "source_file": "test.pptx",
            "screenshot_path": None,
        }

    def test_none_hints_returns_none(self):
        row = self._make_row(industry="retail")
        assert _context_score(row, None) is None

    def test_matching_industry_gives_boost(self):
        row = self._make_row(industry="retail")
        hints = _ContextHints(industries=frozenset(["retail"]), scenarios=frozenset())
        score = _context_score(row, hints)
        assert score is not None
        assert score > 0.0

    def test_matching_scenario_gives_boost(self):
        row = self._make_row(scenario="pitch")
        hints = _ContextHints(industries=frozenset(), scenarios=frozenset(["pitch"]))
        score = _context_score(row, hints)
        assert score is not None
        assert score > 0.0

    def test_matching_both_gives_double_boost(self):
        row = self._make_row(industry="retail", scenario="pitch")
        hints = _ContextHints(industries=frozenset(["retail"]), scenarios=frozenset(["pitch"]))
        score = _context_score(row, hints)
        row_single = self._make_row(industry="retail")
        score_single = _context_score(row_single, hints)
        assert score is not None and score_single is not None
        assert score > score_single

    def test_no_match_returns_zero(self):
        row = self._make_row(industry="healthcare", scenario="training")
        hints = _ContextHints(industries=frozenset(["retail"]), scenarios=frozenset(["pitch"]))
        score = _context_score(row, hints)
        assert score == 0.0

    def test_missing_metadata_returns_zero(self):
        row = self._make_row()  # no industry, no scenario
        hints = _ContextHints(industries=frozenset(["retail"]), scenarios=frozenset(["pitch"]))
        score = _context_score(row, hints)
        assert score == 0.0


class TestFinalScoreWithContext:
    """Test _final_score integration with context_score."""

    def test_no_context_no_business(self):
        assert _final_score(0.75, None, None) == 0.75

    def test_with_context_only(self):
        result = _final_score(0.75, None, 0.05)
        assert abs(result - 0.80) < 1e-6

    def test_with_business_only(self):
        result = _final_score(0.75, 0.10, None)
        assert abs(result - 0.85) < 1e-6

    def test_with_both(self):
        result = _final_score(0.75, 0.10, 0.05)
        assert abs(result - 0.90) < 1e-6

    def test_clamped_to_one(self):
        result = _final_score(0.95, 0.10, 0.10)
        assert result == 1.0


class TestSearchOptionsContext:
    """Test SearchOptions accepts context parameter."""

    def test_default_none(self):
        opts = SearchOptions()
        assert opts.context is None

    def test_set_context(self):
        opts = SearchOptions(context="制造业pitch")
        assert opts.context == "制造业pitch"

    def test_context_only_affects_business_ranking(self):
        """Context is only active when ranking=business; in classic mode it's ignored."""
        opts = SearchOptions(ranking="classic", context="retail")
        assert opts.context == "retail"
        assert opts.ranking == "classic"
