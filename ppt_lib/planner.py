"""LLM-driven narrative planner: decompose a brief into narrative roles."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ppt_lib.labels import NARRATIVE_ROLES
from ppt_lib.llm_client import LLMError, call_llm

if TYPE_CHECKING:
    from ppt_lib.settings import Settings


class PlannerError(Exception):
    """Raised when narrative planning fails."""


# Default roles used when LLM is unavailable or returns nothing useful.
DEFAULT_NARRATIVE_ROLES = ["opener", "problem", "solution", "case", "roi"]

_PROMPT_TEMPLATE = """\
You are a presentation strategist. Given a client brief, determine the optimal narrative structure.

Brief: {brief}
Industry: {industry}

Choose 3-7 roles from this ordered list and arrange them in presentation order:
- opener: opening hook / company intro
- problem: pain point / challenge statement
- solution: proposed solution / approach
- architecture: technical architecture / system design
- case: case study / success story / evidence
- roi: ROI / business value / metrics
- cta: call to action / next steps
- appendix: supplementary material

Return ONLY a JSON array of role names, e.g.: ["opener", "problem", "solution", "case", "roi"]
Do NOT include any other text, markdown fences, or explanation."""


def plan_narrative_roles(
    brief: str,
    *,
    industry: str | None = None,
    settings: Settings,
) -> tuple[list[str], str]:
    """Decompose a brief into narrative roles via LLM.

    Returns (roles, source) where source is "llm" or "fallback".
    Never raises — falls back to DEFAULT_NARRATIVE_ROLES on any failure.
    """
    if not brief or not brief.strip():
        return list(DEFAULT_NARRATIVE_ROLES), "fallback"

    # Truncate very long briefs to avoid token overflow
    truncated_brief = brief[:2000]

    prompt = _PROMPT_TEMPLATE.format(
        brief=truncated_brief,
        industry=industry or "general",
    )

    try:
        raw = call_llm(prompt, settings, max_tokens=200, temperature=0.1)
        roles = _parse_roles_response(raw)
        if roles:
            return roles, "llm"
        # LLM returned empty or all-invalid → fallback
        return list(DEFAULT_NARRATIVE_ROLES), "fallback"
    except (LLMError, RuntimeError):
        return list(DEFAULT_NARRATIVE_ROLES), "fallback"


def _parse_roles_response(raw: str) -> list[str]:
    """Parse LLM response into a list of valid roles.

    Handles: pure JSON, markdown-fenced JSON, extra whitespace.
    Returns empty list if parsing fails completely.
    """
    text = raw.strip()

    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    # Try to extract JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []

    try:
        parsed = json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    valid_set = set(NARRATIVE_ROLES)
    # Filter to valid roles, deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item in valid_set and item not in seen:
            seen.add(item)
            result.append(item)

    return result
