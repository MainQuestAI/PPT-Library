from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ppt_lib.db import connect, init_db, record_slide_usage
from ppt_lib.embedding import build_embedding_provider
from ppt_lib.labels import NARRATIVE_ROLES
from ppt_lib.searcher import SearchOptions, SearchResult, search
from ppt_lib.settings import Settings


@dataclass(frozen=True)
class RoleSelection:
    role: str
    slides: list[SearchResult]
    gap: bool
    beat_id: str | None = None
    page_task_id: str | None = None


@dataclass(frozen=True)
class SelectionReport:
    query: str
    options: dict[str, object]
    roles: list[RoleSelection]
    total_slides: int
    gaps: list[str]
    timestamp: str


def select_slides(
    settings: Settings,
    *,
    roles: list[str],
    brief: str = "",
    industry: str | None = None,
    max_per_role: int = 3,
    ranking: str = "classic",
    threshold: float = 0.0,
    scope: str = "all",
) -> SelectionReport:
    _validate_roles(roles)
    if max_per_role < 1:
        raise ValueError("max_per_role must be at least 1.")

    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    provider = None
    query = brief.strip() or "presentation slide"

    selections: list[RoleSelection] = []
    total_slides = 0
    gaps: list[str] = []

    try:
        for role in roles:
            if not _role_has_rows(conn, role, scope=scope):
                gaps.append(role)
                selections.append(RoleSelection(role=role, slides=[], gap=True, beat_id=role, page_task_id=role))
                continue
            if provider is None:
                provider = build_embedding_provider(settings)
            candidate_limit = _candidate_limit(conn, role, max_per_role, industry=industry, scope=scope)
            results = search(
                query,
                SearchOptions(
                    top_k=candidate_limit,
                    threshold=threshold,
                    ranking=ranking,  # type: ignore[arg-type]
                    narrative_role=role,
                    scope=scope,  # type: ignore[arg-type]
                ),
                settings,
                conn=conn,
                provider=provider,
            )
            if industry:
                results = [result for result in results if _matches_industry(result, industry)]
                results = results[:max_per_role]
            if not results:
                gaps.append(role)
            selections.append(RoleSelection(role=role, slides=results, gap=not results, beat_id=role, page_task_id=role))
            total_slides += len(results)
    finally:
        conn.close()

    return SelectionReport(
        query=query,
        options={"roles": roles, "industry": industry, "ranking": ranking, "max_per_role": max_per_role, "scope": scope},
        roles=selections,
        total_slides=total_slides,
        gaps=gaps,
        timestamp=datetime.now(UTC).isoformat(),
    )


def select_slides_from_plan(
    settings: Settings,
    *,
    plan_path: Path,
    brief: str = "",
    max_per_role: int = 3,
    ranking: str = "classic",
    threshold: float = 0.0,
    scope: str = "all",
) -> SelectionReport:
    """Select slides from a narrative-plan.json file.

    Plan format: {"roles": ["opener", "problem", ...]} or
                 {"beats": [{"role": "opener", "brief": "..."}, ...]}
    """
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "beats" in payload:
            return _select_slides_from_beats(
                settings,
                payload["beats"],
                fallback_brief=brief,
                max_per_role=max_per_role,
                ranking=ranking,
                threshold=threshold,
                scope=scope,
            )
        elif "roles" in payload:
            roles = payload["roles"]
        else:
            raise ValueError("Plan file must contain 'roles' or 'beats' key.")
    else:
        raise ValueError("Plan file must be a JSON object.")

    if not isinstance(roles, list) or not roles:
        raise ValueError("Plan must specify at least one role.")

    return select_slides(
        settings,
        roles=roles,
        brief=brief,
        max_per_role=max_per_role,
        ranking=ranking,
        threshold=threshold,
        scope=scope,
    )


def record_selection_usage(
    settings: Settings,
    report: SelectionReport,
    *,
    deal_id: int,
    deck_presentation_id: int | None = None,
) -> int:
    """Write slide_usage records for all selected slides. Returns count written.

    If deck_presentation_id is not given, uses each slide's source presentation.
    """
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    count = 0
    try:
        position = 0
        for role_sel in report.roles:
            if role_sel.gap:
                continue
            for slide in role_sel.slides[:1]:  # top-1 per role for usage
                position += 1
                # Look up the slide's presentation_id if no explicit deck_presentation_id
                pres_id = deck_presentation_id
                if pres_id is None:
                    row = conn.execute(
                        "SELECT presentation_id FROM slides WHERE id = ?", (slide.slide_id,)
                    ).fetchone()
                    pres_id = row[0] if row else 0
                record_slide_usage(
                    conn,
                    slide_id=slide.slide_id,
                    deal_id=deal_id,
                    deck_presentation_id=pres_id,
                    position=position,
                    commit=False,
                )
                count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def record_assembled_usage(
    settings: Settings,
    slide_ids: list[int],
    *,
    deal_id: int,
) -> int:
    """Record usage in actual output order after assembly succeeds."""
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    count = 0
    try:
        for position, slide_id in enumerate(slide_ids, start=1):
            row = conn.execute(
                "SELECT presentation_id FROM slides WHERE id = ?",
                (slide_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Cannot record usage for unknown slide id: {slide_id}")
            record_slide_usage(
                conn,
                slide_id=slide_id,
                deal_id=deal_id,
                deck_presentation_id=int(row[0]),
                position=position,
                commit=False,
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def _role_has_rows(conn, role: str, *, scope: str = "all") -> bool:
    active_filter = "" if scope == "all" else """
      AND EXISTS (
        SELECT 1 FROM presentation_source_links psl
        JOIN library_sources ls ON ls.id = psl.library_source_id
        WHERE psl.presentation_id = slides.presentation_id AND ls.is_active = 1
      )
    """
    row = conn.execute(
        f"""
        SELECT 1
        FROM slides
        WHERE embedding IS NOT NULL
          AND narrative_role = ?
          AND (origin_type IS NULL OR origin_type != 'assembled_output')
          {active_filter}
        LIMIT 1
        """,
        (role,),
    ).fetchone()
    return row is not None


def _candidate_limit(conn, role: str, max_per_role: int, *, industry: str | None, scope: str = "all") -> int:
    if not industry:
        return max_per_role
    active_filter = "" if scope == "all" else """
      AND EXISTS (
        SELECT 1 FROM presentation_source_links psl
        JOIN library_sources ls ON ls.id = psl.library_source_id
        WHERE psl.presentation_id = slides.presentation_id AND ls.is_active = 1
      )
    """
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM slides
        WHERE embedding IS NOT NULL
          AND narrative_role = ?
          AND (origin_type IS NULL OR origin_type != 'assembled_output')
          {active_filter}
        """,
        (role,),
    ).fetchone()
    count = int(row[0] or 0) if row else 0
    return max(max_per_role, count)


def _select_slides_from_beats(
    settings: Settings,
    beats_payload: object,
    *,
    fallback_brief: str,
    max_per_role: int,
    ranking: str,
    threshold: float,
    scope: str = "all",
) -> SelectionReport:
    if not isinstance(beats_payload, list) or not beats_payload:
        raise ValueError("Plan beats must be a non-empty list.")

    selections: list[RoleSelection] = []
    gaps: list[str] = []
    roles: list[str] = []
    total_slides = 0
    for beat in beats_payload:
        if not isinstance(beat, dict):
            continue
        role = beat.get("role")
        if not isinstance(role, str):
            continue
        roles.append(role)
        beat_brief = beat.get("brief")
        beat_industry = beat.get("industry")
        report = select_slides(
            settings,
            roles=[role],
            brief=beat_brief if isinstance(beat_brief, str) and beat_brief.strip() else fallback_brief,
            industry=beat_industry if isinstance(beat_industry, str) and beat_industry.strip() else None,
            max_per_role=max_per_role,
            ranking=ranking,
            threshold=threshold,
            scope=scope,
        )
        beat_id = _beat_identifier(beat, role=role, index=len(roles))
        page_task_id = beat.get("page_task_id")
        if not isinstance(page_task_id, str) or not page_task_id.strip():
            page_task_id = beat_id
        selections.extend(
            replace(selection, beat_id=beat_id, page_task_id=page_task_id)
            for selection in report.roles
        )
        gaps.extend(report.gaps)
        total_slides += report.total_slides

    if not roles:
        raise ValueError("Plan beats must specify at least one role.")

    return SelectionReport(
        query=fallback_brief.strip() or "narrative plan",
        options={"roles": roles, "ranking": ranking, "max_per_role": max_per_role, "source": "beats"},
        roles=selections,
        total_slides=total_slides,
        gaps=gaps,
        timestamp=datetime.now(UTC).isoformat(),
    )


def _beat_identifier(beat: dict[str, object], *, role: str, index: int) -> str:
    for key in ("beat_id", "id"):
        value = beat.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return role or f"beat_{index + 1}"


def _parse_topn_strategy(strategy: str) -> int | None:
    """Parse a topN-per-role strategy string and return N.

    Accepts 'top1-per-role', 'top2-per-role', 'top3-per-role', etc.
    'top-n' is a compatibility alias for all candidates.
    Raises ValueError for unrecognized formats.
    """
    if strategy == "top-n":
        return None
    match = re.fullmatch(r"top(\d+)-per-role", strategy)
    if not match:
        raise ValueError(f"Unsupported strategy: {strategy}. Expected format: topN-per-role (e.g. top1-per-role, top3-per-role)")
    n = int(match.group(1))
    if n < 1:
        raise ValueError(f"Strategy N must be >= 1, got {n}")
    return n


def build_manifest_from_selection(
    report: SelectionReport,
    *,
    strategy: str = "top1-per-role",
    run_name: str = "auto-compose",
    output_path: str | None = None,
    overwrite: bool = False,
    schema_version: str = "1.0",
) -> dict[str, object]:
    n = _parse_topn_strategy(strategy)

    selected: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for role_selection in report.roles:
        candidates = role_selection.slides[:n] if n is not None else role_selection.slides
        for slide in candidates:
            key = (str(slide.source_file), slide.page_number)
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                {
                    "source_file": str(slide.source_file),
                    "page_number": slide.page_number,
                    "source_slide_id": slide.slide_id,
                    "reason": slide.title or role_selection.role,
                    "risk_policy": "allow_with_warnings",
                }
            )

    return {
        "schema_version": schema_version,
        "run_name": run_name,
        "output": {
            "path": str(output_path) if output_path else f"output/{run_name}.pptx",
            "overwrite": overwrite,
        },
        "options": {
            "render_fidelity_baseline": False,
            "on_complex_slide": "include_with_warning",
        },
        "slides": selected,
        "gaps": report.gaps,
    }


def _validate_roles(roles: list[str]) -> None:
    if not roles:
        raise ValueError("At least one narrative role is required.")
    invalid = [role for role in roles if role not in NARRATIVE_ROLES]
    if invalid:
        valid_roles = ", ".join(NARRATIVE_ROLES)
        raise ValueError(f"Invalid narrative role(s): {invalid}. Valid roles: {valid_roles}")


def _matches_industry(result: SearchResult, industry: str) -> bool:
    expected = industry.lower()
    metadata = result.metadata or {}
    result_industry = metadata.get("industry", "")
    if isinstance(result_industry, str) and expected in result_industry.lower():
        return True
    return expected in result.text_content.lower()
