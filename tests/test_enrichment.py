from __future__ import annotations

from ppt_lib.enrichment import SlideSummary, generate_slide_summary


class FakeSummaryClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def summarize(self, prompt: str) -> dict[str, object]:
        return self.payload


class FailingSummaryClient:
    def summarize(self, prompt: str) -> str:
        raise RuntimeError("LM Studio unavailable")


def test_generate_slide_summary_client_success() -> None:
    result = generate_slide_summary(
        "这是原始文本。",
        {"layout_type": "title"},
        {"industry": ["零售"], "deck_types": ["方案"]},
        client=FakeSummaryClient(
            {
                "ai_summary": "AI摘要内容",
                "visual_summary": "视觉信息提要",
                "summary_status": "ok",
            }
        ),
    )

    assert isinstance(result, SlideSummary)
    assert result.summary_status == "ok"
    assert result.ai_summary == "AI摘要内容"
    assert result.visual_summary == "视觉信息提要"
    assert result.warnings == []


def test_generate_slide_summary_fallback_without_client() -> None:
    result = generate_slide_summary(
        "  This is raw text for slide  \nwith extra spaces.",
        {"layout_type": "chart"},
        {"industry": ["科技"]},
        client=None,
    )

    assert result.summary_status == "fallback"
    assert result.ai_summary.startswith("文本摘要：")
    assert "SUMMARY_FALLBACK_TEXT_MODE" in result.warnings
    assert "layout_type:chart" in result.visual_summary

def test_generate_slide_summary_fallback_when_client_fails() -> None:
    result = generate_slide_summary(
        "本页文本为业务价值分析。",
        {"chart_types": ["line"]},
        {"industry": ["金融"]},
        client=FailingSummaryClient(),
    )

    assert result.summary_status == "fallback"
    assert any(item.startswith("SUMMARY_LM_UNAVAILABLE") for item in result.warnings)
    assert result.visual_summary
