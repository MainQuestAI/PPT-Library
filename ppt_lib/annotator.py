"""LLM-assisted batch annotation of slides with narrative_role, industry, scenario."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from ppt_lib.fts_search import fts_tables_exist, index_from_slides
from ppt_lib.labels import INDUSTRY_LABELS, NARRATIVE_ROLES, SCENARIO_LABELS
from ppt_lib.settings import Settings

logger = logging.getLogger(__name__)

ANNOTATION_PROMPT_TEMPLATE = """\
You are a presentation analyst. Given the text content of a single slide, classify it into three dimensions.

## Dimensions

1. **narrative_role** — the structural role this slide plays in a presentation narrative.
   Valid values: {roles}

2. **industry** — the primary industry this slide is about.
   Valid values: {industries}

3. **scenario** — the presentation scenario/context.
   Valid values: {scenarios}

## Rules
- Pick exactly ONE value per dimension.
- If unsure, use "appendix" for narrative_role, "cross_industry" for industry, "general" for scenario.
- Respond ONLY with a JSON object, no explanation.

## Slide Content
```
{content}
```

## Response Format
{{"narrative_role": "...", "industry": "...", "scenario": "..."}}
"""


@dataclass
class AnnotationResult:
    slide_id: int
    narrative_role: str
    industry: str
    scenario: str
    raw_response: str | None = None


@dataclass
class AnnotationBatch:
    results: list[AnnotationResult]
    errors: list[tuple[int, str]]  # (slide_id, error_message)


def build_annotation_prompt(text_content: str, vision_description: str = "") -> str:
    """Build the LLM prompt for a single slide."""
    content = text_content.strip()
    if vision_description:
        content += f"\n\n[Visual description]: {vision_description}"
    # Truncate very long content
    if len(content) > 3000:
        content = content[:3000] + "\n...(truncated)"

    return ANNOTATION_PROMPT_TEMPLATE.format(
        roles=", ".join(NARRATIVE_ROLES),
        industries=", ".join(INDUSTRY_LABELS),
        scenarios=", ".join(SCENARIO_LABELS),
        content=content,
    )


def parse_annotation_response(response: str) -> dict[str, str]:
    """Parse LLM JSON response into annotation dict. Raises ValueError on failure."""
    # Try to extract JSON from response
    text = response.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

    data = json.loads(text)

    narrative_role = data.get("narrative_role", "appendix")
    industry = data.get("industry", "cross_industry")
    scenario = data.get("scenario", "general")

    # Validate
    if narrative_role not in NARRATIVE_ROLES:
        narrative_role = "appendix"
    if industry not in INDUSTRY_LABELS:
        industry = "cross_industry"
    if scenario not in SCENARIO_LABELS:
        scenario = "general"

    return {"narrative_role": narrative_role, "industry": industry, "scenario": scenario}


def _http_post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 30.0) -> dict:
    """POST JSON and return parsed response. Delegates to llm_client."""
    from ppt_lib.llm_client import http_post_json
    return http_post_json(url, payload, headers=headers, timeout=timeout)


def _call_llm(prompt: str, settings: Settings) -> str:
    """Call LLM. Delegates to llm_client.call_llm."""
    from ppt_lib.llm_client import call_llm
    return call_llm(prompt, settings)


def _call_lmstudio(prompt: str, settings: Settings) -> str:
    """Call LM Studio local LLM. Delegates to llm_client.call_lmstudio."""
    from ppt_lib.llm_client import call_lmstudio
    return call_lmstudio(prompt, settings)


def _call_ollama(prompt: str, settings: Settings) -> str:
    """Call Ollama local LLM."""
    base_url = settings.ollama_base_url.rstrip("/")
    data = _http_post_json(
        f"{base_url}/api/generate",
        {"model": settings.ollama_vision_model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
        timeout=60.0,
    )
    return data["response"]


def annotate_slide(
    slide_id: int,
    text_content: str,
    vision_description: str,
    settings: Settings,
    provider: str = "auto",
) -> AnnotationResult:
    """Annotate a single slide via LLM."""
    prompt = build_annotation_prompt(text_content, vision_description)

    if provider == "auto":
        # Try LM Studio first (local, free), then cloud
        for attempt_provider in ("lmstudio", "cloud"):
            try:
                return annotate_slide(slide_id, text_content, vision_description, settings, attempt_provider)
            except Exception as e:
                logger.debug("Provider %s failed: %s", attempt_provider, e)
                continue
        raise RuntimeError(f"All providers failed for slide {slide_id}")

    if provider == "lmstudio":
        raw = _call_lmstudio(prompt, settings)
    elif provider == "ollama":
        raw = _call_ollama(prompt, settings)
    elif provider == "cloud":
        raw = _call_llm(prompt, settings)
    else:
        raise ValueError(f"Unknown annotation provider: {provider}")

    parsed = parse_annotation_response(raw)
    return AnnotationResult(
        slide_id=slide_id,
        narrative_role=parsed["narrative_role"],
        industry=parsed["industry"],
        scenario=parsed["scenario"],
        raw_response=raw,
    )


def load_unannotated_slides(
    conn: sqlite3.Connection,
    limit: int | None = None,
    force: bool = False,
) -> list[dict]:
    """Load slides that need annotation."""
    if force:
        query = "SELECT id, text_content, metadata_json FROM slides"
    else:
        query = "SELECT id, text_content, metadata_json FROM slides WHERE narrative_role IS NULL"

    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    results = []
    for row in rows:
        meta = json.loads(row[2]) if row[2] else {}
        results.append({
            "slide_id": row[0],
            "text_content": row[1] or "",
            "vision_description": meta.get("vision_description", ""),
        })
    return results


def write_annotations(conn: sqlite3.Connection, results: Sequence[AnnotationResult]) -> int:
    """Write annotation results back to slides table. Returns count of updated rows."""
    updated = 0
    updated_slide_ids: list[int] = []
    for r in results:
        conn.execute(
            "UPDATE slides SET narrative_role = ?, industry = ?, scenario = ? WHERE id = ?",
            (r.narrative_role, r.industry, r.scenario, r.slide_id),
        )
        updated += 1
        updated_slide_ids.append(r.slide_id)
    if updated_slide_ids and fts_tables_exist(conn):
        index_from_slides(conn, slide_ids=sorted(set(updated_slide_ids)), commit=False)
    conn.commit()
    return updated


def annotate_batch(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    batch_size: int = 50,
    provider: str = "auto",
    force: bool = False,
    dry_run: bool = False,
) -> AnnotationBatch:
    """Annotate a batch of unannotated slides.

    Returns AnnotationBatch with results and errors.
    If dry_run=True, does not write to DB.
    """
    slides = load_unannotated_slides(conn, limit=batch_size, force=force)
    if not slides:
        logger.info("No slides to annotate")
        return AnnotationBatch(results=[], errors=[])

    results: list[AnnotationResult] = []
    errors: list[tuple[int, str]] = []

    for i, slide in enumerate(slides):
        try:
            result = annotate_slide(
                slide["slide_id"],
                slide["text_content"],
                slide["vision_description"],
                settings,
                provider=provider,
            )
            results.append(result)
            if (i + 1) % 10 == 0:
                logger.info("Annotated %d/%d slides", i + 1, len(slides))
        except Exception as e:
            errors.append((slide["slide_id"], str(e)))
            logger.warning("Failed to annotate slide %d: %s", slide["slide_id"], e)

    if not dry_run and results:
        write_annotations(conn, results)
        logger.info("Wrote %d annotations to DB", len(results))

    return AnnotationBatch(results=results, errors=errors)
