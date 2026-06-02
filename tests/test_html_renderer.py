from __future__ import annotations

from pathlib import Path

from ppt_lib.html_renderer import HtmlRenderOptions, render_search_review
from ppt_lib.searcher import SearchResult


def result(
    title: str,
    screenshot_path: Path | None = None,
    score: float = 0.9,
    **kwargs,
) -> SearchResult:
    metadata = kwargs.pop("metadata", {"language": "en", "notes": "x" * 2048, "industry": "retail"})
    return SearchResult(
        slide_id=1,
        score=score,
        title=title,
        text_summary=f"{title} summary",
        source_file=Path("/tmp/source.pptx"),
        page_number=3,
        screenshot_path=screenshot_path,
        source="text_extraction",
        confidence=0.5,
        metadata=metadata,
        **kwargs,
    )


def test_empty_state_html(tmp_path: Path) -> None:
    html_path = render_search_review([], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "data-state=\"empty\"" in html
    assert "No results" in html


def test_single_result_html(tmp_path: Path) -> None:
    html_path = render_search_review([result("One")], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "data-state=\"single\"" in html
    assert "One summary" in html


def test_normal_carousel_contains_keyboard_js(tmp_path: Path) -> None:
    html_path = render_search_review([result("One"), result("Two")], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "data-state=\"normal\"" in html
    assert "keydown" in html


def test_truncated_state_limits_results(tmp_path: Path) -> None:
    html_path = render_search_review(
        [result(f"Slide {idx}") for idx in range(12)],
        HtmlRenderOptions(title="Review", max_results=10),
        tmp_path,
    )

    html = html_path.read_text()
    assert "data-state=\"truncated\"" in html
    assert "Slide 9" in html
    assert "Slide 10" not in html


def test_missing_screenshot_placeholder(tmp_path: Path) -> None:
    html_path = render_search_review([result("Missing", Path("/tmp/missing.png"))], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "No screenshot yet" in html


def test_base64_embed_image(tmp_path: Path) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(b"fake-image")

    html_path = render_search_review([result("Image", image)], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "data:image/png;base64" in html


def test_metadata_render_safe(tmp_path: Path) -> None:
    html_path = render_search_review([result("<unsafe>")], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "&lt;unsafe&gt;" in html
    assert "<unsafe>" not in html


def test_untitled_result_uses_filename_and_page(tmp_path: Path) -> None:
    untitled = result("")
    html_path = render_search_review([untitled], HtmlRenderOptions(title="Review"), tmp_path)

    html = html_path.read_text()
    assert "source · P3" in html
    assert "Untitled" not in html
    assert "Source</dt><dd>source.pptx" in html
    assert "/tmp/source.pptx" not in html


def test_output_filename_stable_and_unique(tmp_path: Path) -> None:
    first = render_search_review([result("One")], HtmlRenderOptions(title="Review"), tmp_path)
    second = render_search_review([result("One")], HtmlRenderOptions(title="Review"), tmp_path)

    assert first != second
    assert first.suffix == ".html"
    assert second.suffix == ".html"


def _result_with_tags(
    narrative_role: str | None = None,
    industry: str | None = None,
    scenario: str | None = None,
    **kwargs,
) -> SearchResult:
    meta = {"language": "en"}
    if narrative_role:
        meta["narrative_role"] = narrative_role
    if industry:
        meta["industry"] = industry
    if scenario:
        meta["scenario"] = scenario
    return SearchResult(
        slide_id=1,
        score=0.9,
        title="Tagged",
        text_summary="Tagged summary",
        source_file=Path("/tmp/source.pptx"),
        page_number=1,
        screenshot_path=None,
        source="text_extraction",
        confidence=0.5,
        metadata=meta,
        **kwargs,
    )


def test_narrative_tags_rendered(tmp_path: Path) -> None:
    r = _result_with_tags(narrative_role="opener", industry="retail", scenario="pitch")
    html_path = render_search_review([r], HtmlRenderOptions(title="Review"), tmp_path)
    html_text = html_path.read_text()
    assert "tag-role" in html_text
    assert "opener" in html_text
    assert "tag-industry" in html_text
    assert "retail" in html_text
    assert "tag-scenario" in html_text
    assert "pitch" in html_text


def test_no_tags_when_unannotated(tmp_path: Path) -> None:
    r = _result_with_tags()  # no narrative fields
    html_path = render_search_review([r], HtmlRenderOptions(title="Review"), tmp_path)
    html_text = html_path.read_text()
    # No tags div should be rendered (class="tags" only appears in CSS, not in content)
    assert '<div class="tags">' not in html_text


def test_score_breakdown_rendered(tmp_path: Path) -> None:
    r = _result_with_tags(
        score_breakdown={"semantic_score": 0.85, "business_score": 0.12, "context_score": 0.05}
    )
    html_path = render_search_review([r], HtmlRenderOptions(title="Review"), tmp_path)
    html_text = html_path.read_text()
    assert "Semantic Score" in html_text
    assert "0.850" in html_text
    assert "Business Score" in html_text
    assert "0.120" in html_text


def test_score_breakdown_skips_none(tmp_path: Path) -> None:
    r = _result_with_tags(
        score_breakdown={"semantic_score": 0.7, "win_rate": None}
    )
    html_path = render_search_review([r], HtmlRenderOptions(title="Review"), tmp_path)
    html_text = html_path.read_text()
    assert "Semantic Score" in html_text
    assert "Win Rate" not in html_text


def test_metadata_render_collapses_to_key_fields(tmp_path: Path) -> None:
    huge_meta = {"industry": "retail"}
    huge_meta.update({f"field{i}": ("x" * 200) for i in range(20)})
    html_path = render_search_review([result("Metadata", metadata=huge_meta)], HtmlRenderOptions(title="Review"), tmp_path)

    html_text = html_path.read_text()
    assert "<details><summary>show metadata</summary>" in html_text
    assert "<code>" not in html_text
    assert "industry" in html_text
    assert html_text.count("x" * 200) == 0
