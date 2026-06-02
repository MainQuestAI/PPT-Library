"""Compose: convenience wrapper that orchestrates select-slides → build-manifest → assemble."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ppt_lib.assembler import AssembleReport, load_assemble_manifest, run_assemble
from ppt_lib.selector import SelectionReport, build_manifest_from_selection, select_slides, select_slides_from_plan
from ppt_lib.settings import Settings


@dataclass
class ComposeTimings:
    select_slides_ms: int = 0
    build_manifest_ms: int = 0
    assemble_ms: int = 0
    total_ms: int = 0


@dataclass
class ComposeResult:
    run_id: str
    run_dir: Path
    selection_report: SelectionReport
    manifest: dict[str, object]
    assemble_report: AssembleReport | None
    gaps: list[str]
    timings: ComposeTimings
    dry_run: bool = False


def compose(
    settings: Settings,
    *,
    roles: list[str] | None = None,
    plan_path: Path | None = None,
    brief: str = "",
    industry: str | None = None,
    max_per_role: int = 3,
    ranking: str = "classic",
    threshold: float = 0.0,
    run_name: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    deal_id: int | None = None,
    verbose: bool = False,
) -> ComposeResult:
    """Run the full compose pipeline: select-slides → build-manifest → assemble.

    Args:
        roles: Narrative roles to select (mutually exclusive with plan_path).
        plan_path: Path to a narrative-plan.json (mutually exclusive with roles).
        brief: Search query / context.
        industry: Optional industry filter.
        dry_run: If True, generate plan + selection but don't assemble.
        deal_id: If set, record slide usage for the deal.
    """
    # Auto-plan from brief if neither roles nor plan_path given
    plan_source = "manual"
    if not roles and not plan_path:
        if brief:
            from ppt_lib.planner import plan_narrative_roles
            roles, plan_source = plan_narrative_roles(brief, industry=industry, settings=settings)
        else:
            raise ValueError("Either roles, plan_path, or brief is required.")

    run_id = _run_id()
    actual_run_name = run_name or f"compose-{run_id}"
    assert settings.home_dir is not None
    run_dir = settings.home_dir / "composed" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    timings = ComposeTimings()
    total_start = time.monotonic()

    # Step 1: Select slides
    t0 = time.monotonic()
    if plan_path:
        selection = select_slides_from_plan(
            settings,
            plan_path=plan_path,
            brief=brief,
            max_per_role=max_per_role,
            ranking=ranking,
            threshold=threshold,
        )
    else:
        assert roles is not None
        selection = select_slides(
            settings,
            roles=roles,
            brief=brief,
            industry=industry,
            max_per_role=max_per_role,
            ranking=ranking,
            threshold=threshold,
        )
    timings.select_slides_ms = int((time.monotonic() - t0) * 1000)

    # Write selection report
    _write_json(run_dir / "selection-report.json", _selection_to_dict(selection))

    # Write narrative plan (for --confirm later)
    plan = {"roles": [rs.role for rs in selection.roles], "brief": brief, "industry": industry, "source": plan_source}
    _write_json(run_dir / "narrative-plan.json", plan)

    # Write gaps
    if selection.gaps:
        _write_json(run_dir / "gaps.json", {"gaps": selection.gaps})

    # Step 2: Build manifest
    t0 = time.monotonic()
    output_pptx = run_dir / f"{actual_run_name}.pptx"
    manifest_dict = build_manifest_from_selection(
        selection,
        strategy="top1-per-role",
        run_name=actual_run_name,
        output_path=str(output_pptx),
        overwrite=overwrite,
    )
    timings.build_manifest_ms = int((time.monotonic() - t0) * 1000)

    manifest_path = run_dir / "manifest.json"
    _write_json(manifest_path, manifest_dict)

    # Step 3: Assemble (unless dry-run)
    assemble_report = None
    if not dry_run:
        t0 = time.monotonic()
        assemble_manifest = load_assemble_manifest(manifest_path)
        assemble_report = run_assemble(assemble_manifest)
        timings.assemble_ms = int((time.monotonic() - t0) * 1000)

    timings.total_ms = int((time.monotonic() - total_start) * 1000)

    # Write timings if verbose
    if verbose:
        _write_json(run_dir / "compose-timing.json", {
            "select_slides_ms": timings.select_slides_ms,
            "build_manifest_ms": timings.build_manifest_ms,
            "assemble_ms": timings.assemble_ms,
            "total_ms": timings.total_ms,
        })

    # Record usage if deal_id provided
    if deal_id is not None and not dry_run:
        from ppt_lib.selector import record_selection_usage
        record_selection_usage(settings, selection, deal_id=deal_id)

    # Write diff-summary.md
    _write_diff_summary(run_dir, selection, manifest_dict, plan_source)

    # Print human-readable summary to stderr
    _print_compose_summary(selection, timings, dry_run)

    return ComposeResult(
        run_id=run_id,
        run_dir=run_dir,
        selection_report=selection,
        manifest=manifest_dict,
        assemble_report=assemble_report,
        gaps=selection.gaps,
        timings=timings,
        dry_run=dry_run,
    )


def compose_confirm(
    settings: Settings,
    *,
    plan_path: Path,
    overwrite: bool = False,
    deal_id: int | None = None,
    verbose: bool = False,
) -> ComposeResult:
    """Execute compose from a previously saved narrative-plan.json."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    roles = plan.get("roles", [])
    brief = plan.get("brief", "")
    industry = plan.get("industry")

    if not roles:
        raise ValueError("Plan file must contain 'roles'.")

    result = compose(
        settings,
        roles=roles,
        brief=brief,
        industry=industry,
        dry_run=False,
        overwrite=overwrite,
        deal_id=deal_id,
        verbose=verbose,
    )

    # Overwrite plan source to 'confirmed' for consistency
    plan_out = result.run_dir / "narrative-plan.json"
    if plan_out.exists():
        plan_data = json.loads(plan_out.read_text(encoding="utf-8"))
        plan_data["source"] = "confirmed"
        plan_out.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    return result


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _selection_to_dict(report: SelectionReport) -> dict[str, object]:
    return {
        "query": report.query,
        "options": report.options,
        "timestamp": report.timestamp,
        "roles": [
            {
                "role": rs.role,
                "count": len(rs.slides),
                "status": "gap" if rs.gap else "matched",
                "slides": [
                    {
                        "slide_id": s.slide_id,
                        "score": s.score,
                        "title": s.title,
                        "source_file": str(s.source_file),
                        "page_number": s.page_number,
                        "score_breakdown": s.score_breakdown,
                    }
                    for s in rs.slides
                ],
            }
            for rs in report.roles
        ],
        "total_slides": report.total_slides,
        "gaps": report.gaps,
    }


def _write_diff_summary(run_dir: Path, selection: SelectionReport, manifest: dict[str, object], plan_source: str) -> None:
    """Write a human-readable diff-summary.md to the run directory."""
    lines: list[str] = []
    lines.append("# Compose Summary\n")
    lines.append(f"Plan Source: {plan_source}\n")

    # Roles
    lines.append("\n## Narrative Roles\n")
    for rs in selection.roles:
        status = "GAP" if rs.gap else f"{len(rs.slides)} slides"
        lines.append(f"- **{rs.role}**: {status}")
    lines.append("")

    # Gaps
    if selection.gaps:
        lines.append("\n## Gaps (no slides found)\n")
        for g in selection.gaps:
            lines.append(f"- {g}")
        lines.append("")

    # Slide manifest
    slide_entries = manifest.get("slides", [])
    if isinstance(slide_entries, list) and slide_entries:
        lines.append(f"\n## Manifest: {len(slide_entries)} slides\n")
        for i, s in enumerate(slide_entries, 1):
            if isinstance(s, dict):
                lines.append(f"{i}. {s.get('source_file', '?')} p{s.get('page_number', '?')}")
        lines.append("")

    content = "\n".join(lines) + "\n"
    (run_dir / "diff-summary.md").write_text(content, encoding="utf-8")


def _print_compose_summary(selection: SelectionReport, timings: ComposeTimings, dry_run: bool) -> None:
    """Print a human-readable compose summary to stderr."""
    roles_used = [rs.role for rs in selection.roles if not rs.gap]
    gaps = selection.gaps
    total = selection.total_slides
    mode = "dry-run" if dry_run else "assembled"

    lines = [
        f"\n── Compose Summary ({mode}) ──",
        f"  Roles: {', '.join(roles_used) if roles_used else '(none)'}",
        f"  Gaps:  {', '.join(gaps) if gaps else '(none)'}",
        f"  Total slides: {total}",
        f"  Timing: select={timings.select_slides_ms}ms manifest={timings.build_manifest_ms}ms"
        f" assemble={timings.assemble_ms}ms total={timings.total_ms}ms",
        "",
    ]
    sys.stderr.write("\n".join(lines) + "\n")

