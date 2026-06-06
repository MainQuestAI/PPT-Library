from __future__ import annotations

import base64
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ppt_lib.searcher import SearchResult


class HtmlRenderError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HtmlRenderOptions:
    title: str
    max_results: int = 10
    embed_images: bool = True


def render_search_review(results: list[SearchResult], options: HtmlRenderOptions, output_dir: Path) -> Path:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HtmlRenderError(f"Cannot write HTML output: {output_dir}", code="HTML_OUTPUT_NOT_WRITABLE") from exc

    visible = results[: options.max_results]
    state = _state(results, options.max_results)
    body = _render_body(visible, options, state)
    html_text = _document(options.title, state, body)
    output_path = output_dir / f"search-review-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}.html"
    output_path.write_text(html_text)
    return output_path


def _state(results: list[SearchResult], max_results: int) -> str:
    if not results:
        return "empty"
    if len(results) > max_results:
        return "truncated"
    if len(results) == 1:
        return "single"
    return "normal"


def _render_body(results: list[SearchResult], options: HtmlRenderOptions, state: str) -> str:
    if state == "empty":
        return "<main><h1>No results</h1><p>Try a broader query or lower the threshold.</p></main>"
    cards = "\n".join(_render_result(result, options, index) for index, result in enumerate(results))
    truncated = (
        "<p class=\"notice\">Showing first results only. Refine the query or lower the threshold.</p>"
        if state == "truncated"
        else ""
    )
    script = _keyboard_script() if state in {"normal", "truncated"} else ""
    return f"<main>{truncated}<section class=\"results\">{cards}</section>{script}</main>"


def _render_result(result: SearchResult, options: HtmlRenderOptions, index: int) -> str:
    image = _render_image(result, options)
    tags_html = _render_narrative_tags(result)
    breakdown_html = _render_score_breakdown(result)
    title = _display_title(result)
    metadata_html = _render_metadata(result)
    duplicate_html = _render_duplicate_info(result)
    asset_html = _render_asset_summary(result)
    return f"""
    <article class="result" data-index="{index}">
      <div class="media">{image}</div>
      <div class="content">
        <h2>{html.escape(title)}</h2>
        {tags_html}
        <p>{html.escape(result.text_summary)}</p>
        <dl>
          <dt>Source</dt><dd>{html.escape(result.source_file.name)}（评分 {result.score:.3f}）</dd>
          <dt>Page</dt><dd>{result.page_number}</dd>
          <dt>Source Type</dt><dd>{html.escape(result.source)}</dd>
          <dt>Score</dt><dd>{result.score:.3f}</dd>{breakdown_html}{asset_html}
          {duplicate_html}
          <dt>Metadata</dt><dd>{metadata_html}</dd>
        </dl>
      </div>
    </article>
    """


def _render_narrative_tags(result: SearchResult) -> str:
    """Render narrative tags (role, industry, scenario) as colored badges."""
    meta = result.metadata or {}
    tags = []
    role = meta.get("narrative_role")
    industry = meta.get("industry")
    scenario = meta.get("scenario")
    page_role = meta.get("page_role")
    if role:
        tags.append(f'<span class="tag tag-role">{html.escape(str(role))}</span>')
    if page_role:
        tags.append(f'<span class="tag tag-key">{html.escape(str(page_role))}</span>')
    if industry:
        tags.append(f'<span class="tag tag-industry">{html.escape(str(industry))}</span>')
    if scenario:
        tags.append(f'<span class="tag tag-scenario">{html.escape(str(scenario))}</span>')
    if not tags:
        return ""
    return f'<div class="tags">{"".join(tags)}</div>'


def _render_asset_summary(result: SearchResult) -> str:
    meta = result.metadata or {}
    parts: list[str] = []
    for key in ("page_role", "importance_score", "importance_reason", "needs_visual", "reuse_count", "won_count", "lost_count", "win_rate"):
        value = meta.get(key)
        if value is None:
            continue
        parts.append(f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>")
    return "".join(parts)


def _render_score_breakdown(result: SearchResult) -> str:
    """Render score breakdown as additional DT/DD pairs."""
    if not result.score_breakdown:
        return ""
    parts = []
    for key, value in result.score_breakdown.items():
        if value is not None:
            label = html.escape(key.replace("_", " ").title())
            parts.append(f"<dt>{label}</dt><dd>{value:.3f}</dd>")
    return "".join(parts)


def _render_duplicate_info(result: SearchResult) -> str:
    if result.duplicate_count is None and result.canonical_slide_id is None:
        return ""
    parts = ['<dt>Duplicate</dt><dd>']
    values: list[str] = []
    if result.canonical_slide_id is not None:
        values.append(f"canonical_slide_id={result.canonical_slide_id}")
    if result.duplicate_count is not None:
        values.append(f"duplicate_count={result.duplicate_count}")
    parts.append(", ".join(values))
    parts.append("</dd>")
    return "".join(parts)


def _render_metadata(result: SearchResult) -> str:
    metadata = _safe_metadata(result.metadata)
    if not metadata:
        return "<span>metadata: none</span>"
    keys = (
        "industry",
        "scenario",
        "narrative_role",
        "page_role",
        "importance_score",
        "reuse_count",
        "won_count",
        "win_rate",
        "confidence",
        "origin_type",
    )
    rows = []
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if value is None:
            continue
        rows.append(f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>")
    remaining = len(metadata) - len(rows)
    if remaining <= 0:
        body = "".join(rows)
    else:
        body = "".join(rows) + f'<dt>other</dt><dd>+{remaining} fields</dd>'
    return f"<details><summary>show metadata</summary><dl>{body}</dl></details>"


def _render_image(result: SearchResult, options: HtmlRenderOptions) -> str:
    path = result.screenshot_path
    if not path or not path.exists():
        return "<div class=\"placeholder\">No screenshot yet</div>"
    if not options.embed_images:
        return f"<img src=\"{html.escape(str(path))}\" alt=\"Slide screenshot\">"
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return "<div class=\"placeholder\">No screenshot yet</div>"
    return f"<img src=\"data:image/png;base64,{encoded}\" alt=\"Slide screenshot\">"


def _display_title(result: SearchResult) -> str:
    if result.title and result.title.strip():
        return result.title
    return f"{result.source_file.stem} · P{result.page_number}"


def _document(title: str, state: str, body: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en" data-state="{state}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #1f2933; }}
    main {{ max-width: 100%; }}
    .result {{
      display: grid;
      grid-template-columns: minmax(220px, 42%) 1fr;
      gap: 20px;
      border-bottom: 1px solid #d8dee4;
      padding: 20px 0;
      min-width: 0;
    }}
    .media, .content {{ min-width: 0; }}
    img {{ max-width: 100%; border: 1px solid #d8dee4; }}
    .placeholder {{ display: grid; place-items: center; min-height: 180px; background: #f3f4f6; color: #6b7280; }}
    h2, p, dt, dd, summary, .tag {{ overflow-wrap: anywhere; }}
    dt {{ font-weight: 700; margin-top: 8px; }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    .notice {{ padding: 10px 12px; background: #fff7ed; border: 1px solid #fed7aa; }}
    .tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
    .tag-role {{ background: #dbeafe; color: #1e40af; }}
    .tag-key {{ background: #fde68a; color: #854d0e; }}
    .tag-industry {{ background: #dcfce7; color: #166534; }}
    .tag-scenario {{ background: #fef3c7; color: #92400e; }}
    @media (max-width: 700px) {{
      body {{ margin: 16px; }}
      .result {{ grid-template-columns: 1fr; gap: 12px; }}
      .placeholder {{ min-height: 140px; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _keyboard_script() -> str:
    return """
    <script>
      document.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
          const cards = Array.from(document.querySelectorAll('.result'));
          const current = cards.findIndex(card => card.getBoundingClientRect().top >= 0);
          const delta = event.key === 'ArrowRight' ? 1 : -1;
          const next = Math.max(0, Math.min(cards.length - 1, current + delta));
          cards[next]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    </script>
    """


def _safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    try:
        json.dumps(metadata)
        return metadata
    except TypeError:
        return {key: str(value) for key, value in metadata.items()}
