from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ppt_lib.pptx_package import CopiedSlide, PptxPackageError, copy_slides_to_new_pptx
from ppt_lib.screenshot import ScreenshotError, render_pptx_slides

DEFAULT_SCHEMA_VERSION = "1.0"
DEFAULT_RUN_NAME = "assemble-run"
DEFAULT_RISK_POLICY = "allow_with_warnings"
DEFAULT_ON_COMPLEX_SLIDE = "include_with_warning"
ALLOWED_RISK_POLICIES = frozenset({"allow_with_warnings", "manual_review_required"})
ALLOWED_ON_COMPLEX_SLIDE = frozenset({"include_with_warning", "skip"})
SAFE_RUN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
FIDELITY_RENDER_TIMEOUT_SECONDS = 120


class AssembleManifestError(RuntimeError):
    pass


class AssembleRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssembleSlideSpec:
    source_file: Path
    page_number: int
    source_slide_id: int | None
    reason: str | None
    risk_policy: str


@dataclass(frozen=True)
class AssembleManifest:
    schema_version: str
    run_name: str
    output_path: Path
    overwrite: bool
    render_fidelity_baseline: bool
    on_complex_slide: str
    slides: list[AssembleSlideSpec]


@dataclass(frozen=True)
class AssembleSlideReport:
    output_page_number: int
    source_file: str
    source_page_number: int
    status: str
    risk_level: str
    warnings: list[str]


@dataclass(frozen=True)
class SkippedSlideReport:
    source_file: str
    source_page_number: int
    status: str
    reason: str
    warnings: list[str]


@dataclass(frozen=True)
class AssembleFidelityReport:
    source_screenshots_dir: str
    output_screenshots_dir: str
    manual_review_required: bool
    warnings: list[str]
    expected_source_screenshot_count: int = 0
    actual_source_screenshot_count: int = 0
    missing_source_screenshot_count: int = 0
    expected_output_screenshot_count: int = 0
    actual_output_screenshot_count: int = 0
    missing_output_screenshot_count: int = 0


@dataclass(frozen=True)
class AssembleReport:
    schema_version: str
    run_id: str
    status: str
    output_path: Path
    slide_count: int
    slides: list[AssembleSlideReport]
    errors: list[str]
    fidelity: AssembleFidelityReport
    skipped_slides: list[SkippedSlideReport] = field(default_factory=list)
    report_path: Path = Path("assemble-report.json")


@dataclass(frozen=True)
class _RenderResult:
    screenshot_count: int
    warnings: list[str]


def load_assemble_manifest(path: Path) -> AssembleManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssembleManifestError(f"Cannot read assemble manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AssembleManifestError(f"Invalid assemble manifest JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise AssembleManifestError("Assemble manifest must be a JSON object.")

    run_name = _string_value(raw.get("run_name"), DEFAULT_RUN_NAME, "run_name")
    output = _object_value(raw.get("output"), "output")
    options = _object_value(raw.get("options"), "options")
    output_path = _output_path(output, run_name)

    raw_slides = raw.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise AssembleManifestError("Assemble manifest must contain a non-empty slides array.")

    return AssembleManifest(
        schema_version=_string_value(raw.get("schema_version"), DEFAULT_SCHEMA_VERSION, "schema_version"),
        run_name=run_name,
        output_path=output_path,
        overwrite=_bool_value(output.get("overwrite"), False, "output.overwrite"),
        render_fidelity_baseline=_bool_value(options.get("render_fidelity_baseline"), True, "options.render_fidelity_baseline"),
        on_complex_slide=_enum_value(
            options.get("on_complex_slide"),
            DEFAULT_ON_COMPLEX_SLIDE,
            "options.on_complex_slide",
            ALLOWED_ON_COMPLEX_SLIDE,
        ),
        slides=[_parse_slide(item, index) for index, item in enumerate(raw_slides, start=1)],
    )


def run_assemble(manifest: AssembleManifest) -> AssembleReport:
    report_path = manifest.output_path.parent / "assemble-report.json"
    try:
        manifest.output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AssembleRunError(f"Cannot create assemble run directory: {manifest.output_path.parent}") from exc

    if manifest.output_path.exists() and not manifest.overwrite:
        report = _assemble_report(
            manifest=manifest,
            copied_slides=[],
            report_path=report_path,
            fatal_errors=[f"output_exists: {manifest.output_path} already exists and overwrite is false."],
        )
        _write_report(report)
        return report

    try:
        skipped_slides: list[SkippedSlideReport] = []
        active_manifest = manifest
        if manifest.on_complex_slide == "skip":
            active_manifest, skipped_slides = _skip_unrenderable_slides(manifest)
        copied_slides = copy_slides_to_new_pptx(
            [(slide.source_file, slide.page_number) for slide in active_manifest.slides],
            manifest.output_path,
        )
        fidelity = _render_fidelity_baseline(active_manifest) if manifest.render_fidelity_baseline else _empty_fidelity_report()
        report = _assemble_report(
            manifest=manifest,
            copied_slides=copied_slides,
            skipped_slides=skipped_slides,
            report_path=report_path,
            fatal_errors=[],
            fidelity=fidelity,
        )
    except PptxPackageError as exc:
        report = _assemble_report(
            manifest=manifest,
            copied_slides=[],
            report_path=report_path,
            fatal_errors=[f"package_error: {exc}"],
            fidelity=_empty_fidelity_report(),
        )
    _write_report(report)
    return report


def _parse_slide(item: Any, index: int) -> AssembleSlideSpec:
    if not isinstance(item, dict):
        raise AssembleManifestError(f"slides[{index}] must be a JSON object.")

    source_file = _required_string(item.get("source_file"), f"slides[{index}].source_file")
    page_number = _positive_int(item.get("page_number"), f"slides[{index}].page_number")
    source_slide_id = _optional_int(item.get("source_slide_id"), f"slides[{index}].source_slide_id")
    reason = _optional_string(item.get("reason"), f"slides[{index}].reason")
    risk_policy = _enum_value(item.get("risk_policy"), DEFAULT_RISK_POLICY, f"slides[{index}].risk_policy", ALLOWED_RISK_POLICIES)

    return AssembleSlideSpec(
        source_file=Path(source_file).expanduser(),
        page_number=page_number,
        source_slide_id=source_slide_id,
        reason=reason,
        risk_policy=risk_policy,
    )


def _assemble_report(
    *,
    manifest: AssembleManifest,
    copied_slides: list[CopiedSlide],
    skipped_slides: list[SkippedSlideReport] | None = None,
    report_path: Path,
    fatal_errors: list[str],
    fidelity: AssembleFidelityReport | None = None,
) -> AssembleReport:
    slide_reports = [_slide_report(slide) for slide in copied_slides]
    skipped_reports = skipped_slides or []
    fidelity_report = fidelity or _empty_fidelity_report()
    return AssembleReport(
        schema_version=manifest.schema_version,
        run_id=_run_id(),
        status=_aggregate_status(slide_reports, skipped_reports, fatal_errors, fidelity_report.warnings),
        output_path=manifest.output_path,
        slide_count=len(slide_reports),
        slides=slide_reports,
        skipped_slides=skipped_reports,
        errors=fatal_errors,
        fidelity=fidelity_report,
        report_path=report_path,
    )


def _empty_fidelity_report() -> AssembleFidelityReport:
    return AssembleFidelityReport(
        source_screenshots_dir="",
        output_screenshots_dir="",
        manual_review_required=True,
        warnings=[],
    )


def _render_fidelity_baseline(manifest: AssembleManifest) -> AssembleFidelityReport:
    screenshots_root = manifest.output_path.parent / "screenshots"
    source_dir = screenshots_root / "source"
    output_dir = screenshots_root / "output"
    warnings: list[str] = []
    expected_source_count = _expected_source_screenshot_count(manifest)
    actual_source_count = 0

    for source_file in _unique_source_files(manifest):
        target_dir = source_dir / _source_screenshot_subdir(source_file)
        render_result = _render_screenshots(source_file, target_dir, label=f"source:{source_file}")
        actual_source_count += render_result.screenshot_count
        warnings.extend(render_result.warnings)

    output_result = _render_screenshots(manifest.output_path, output_dir, label=f"output:{manifest.output_path}")
    expected_output_count = len(manifest.slides)
    actual_output_count = output_result.screenshot_count
    warnings.extend(output_result.warnings)
    missing_source_count = max(0, expected_source_count - actual_source_count)
    missing_output_count = max(0, expected_output_count - actual_output_count)
    if missing_source_count:
        warnings.append(
            "fidelity_render_incomplete: source screenshots "
            f"expected={expected_source_count} actual={actual_source_count} missing={missing_source_count}"
        )
    if missing_output_count:
        warnings.append(
            "fidelity_render_incomplete: output screenshots "
            f"expected={expected_output_count} actual={actual_output_count} missing={missing_output_count}"
        )

    return AssembleFidelityReport(
        source_screenshots_dir=str(source_dir),
        output_screenshots_dir=str(output_dir),
        manual_review_required=True,
        warnings=warnings,
        expected_source_screenshot_count=expected_source_count,
        actual_source_screenshot_count=actual_source_count,
        missing_source_screenshot_count=missing_source_count,
        expected_output_screenshot_count=expected_output_count,
        actual_output_screenshot_count=actual_output_count,
        missing_output_screenshot_count=missing_output_count,
    )


def _skip_unrenderable_slides(manifest: AssembleManifest) -> tuple[AssembleManifest, list[SkippedSlideReport]]:
    active_slides: list[AssembleSlideSpec] = []
    skipped_slides: list[SkippedSlideReport] = []
    for slide in manifest.slides:
        warnings = _slide_render_preflight(slide)
        if warnings:
            skipped_slides.append(
                SkippedSlideReport(
                    source_file=str(slide.source_file),
                    source_page_number=slide.page_number,
                    status="skipped",
                    reason="render_preflight_failed",
                    warnings=warnings,
                )
            )
            continue
        active_slides.append(slide)
    return (
        AssembleManifest(
            schema_version=manifest.schema_version,
            run_name=manifest.run_name,
            output_path=manifest.output_path,
            overwrite=manifest.overwrite,
            render_fidelity_baseline=manifest.render_fidelity_baseline,
            on_complex_slide=manifest.on_complex_slide,
            slides=active_slides,
        ),
        skipped_slides,
    )


def _slide_render_preflight(slide: AssembleSlideSpec) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="ppt-lib-assemble-preflight-") as temp_root:
        temp_dir = Path(temp_root)
        output_path = temp_dir / "single-slide.pptx"
        try:
            copy_slides_to_new_pptx([(slide.source_file, slide.page_number)], output_path)
            results = render_pptx_slides(output_path, temp_dir / "screens", timeout_seconds=FIDELITY_RENDER_TIMEOUT_SECONDS)
        except PptxPackageError as exc:
            return [f"render_preflight_failed: package_error: {exc}"]
        except ScreenshotError as exc:
            return [f"render_preflight_failed: {exc.code}: {exc}"]
        except (OSError, RuntimeError) as exc:
            return [f"render_preflight_failed: {type(exc).__name__}: {exc}"]
        if not results:
            return ["render_preflight_failed: renderer produced no screenshots"]
    return []


def _unique_source_files(manifest: AssembleManifest) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for slide in manifest.slides:
        if slide.source_file in seen:
            continue
        seen.add(slide.source_file)
        unique.append(slide.source_file)
    return unique


def _expected_source_screenshot_count(manifest: AssembleManifest) -> int:
    max_page_by_file: dict[Path, int] = {}
    for slide in manifest.slides:
        max_page_by_file[slide.source_file] = max(max_page_by_file.get(slide.source_file, 0), slide.page_number)
    return sum(max_page_by_file.values())


def _source_screenshot_subdir(source_file: Path) -> str:
    digest = sha256(str(source_file).encode("utf-8")).hexdigest()[:12]
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_file.stem).strip("._-") or "source"
    return f"{safe_stem}-{digest}"


def _render_screenshots(pptx_path: Path, output_dir: Path, *, label: str) -> _RenderResult:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        results = render_pptx_slides(pptx_path, output_dir, timeout_seconds=FIDELITY_RENDER_TIMEOUT_SECONDS)
    except ScreenshotError as exc:
        return _RenderResult(0, [f"fidelity_render_failed: {label}: {exc.code}: {exc}"])
    except (OSError, RuntimeError) as exc:
        return _RenderResult(0, [f"fidelity_render_failed: {label}: {type(exc).__name__}: {exc}"])
    if not results:
        return _RenderResult(0, [f"fidelity_render_empty: {label}: renderer produced no screenshots"])
    warnings: list[str] = []
    for result in results:
        warnings.extend(result.warnings)
    return _RenderResult(len(results), warnings)


def _slide_report(slide: CopiedSlide) -> AssembleSlideReport:
    return AssembleSlideReport(
        output_page_number=slide.output_page_number,
        source_file=str(slide.source_file),
        source_page_number=slide.source_page_number,
        status=slide.status,
        risk_level=_risk_level(slide.risk_tags),
        warnings=slide.warnings,
    )


def _risk_level(risk_tags: list[str]) -> str:
    tags = set(risk_tags)
    if tags & {"embedded_object", "smartart_or_diagram", "missing_relationship_target"}:
        return "high"
    if tags & {"external_relationship", "chart", "slide_layout", "slide_master", "theme"}:
        return "medium"
    return "low"


def _aggregate_status(
    slides: list[AssembleSlideReport],
    skipped_slides: list[SkippedSlideReport],
    fatal_errors: list[str],
    fidelity_warnings: list[str],
) -> str:
    if fatal_errors or not slides:
        return "failed"
    if skipped_slides:
        return "partial"
    if any(slide.status != "copied" for slide in slides):
        return "partial"
    if any(slide.risk_level != "low" for slide in slides):
        return "needs_manual_review"
    if fidelity_warnings:
        return "needs_manual_review"
    return "passed"


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _write_report(report: AssembleReport) -> None:
    try:
        report.report_path.parent.mkdir(parents=True, exist_ok=True)
        report.report_path.write_text(json.dumps(_report_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise AssembleRunError(f"Cannot write assemble report: {report.report_path}") from exc


def _report_to_json(report: AssembleReport) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "run_id": report.run_id,
        "status": report.status,
        "output_path": str(report.output_path),
        "slide_count": report.slide_count,
        "slides": [
            {
                "output_page_number": slide.output_page_number,
                "source_file": slide.source_file,
                "source_page_number": slide.source_page_number,
                "status": slide.status,
                "risk_level": slide.risk_level,
                "warnings": slide.warnings,
            }
            for slide in report.slides
        ],
        "skipped_slides": [
            {
                "source_file": slide.source_file,
                "source_page_number": slide.source_page_number,
                "status": slide.status,
                "reason": slide.reason,
                "warnings": slide.warnings,
            }
            for slide in report.skipped_slides
        ],
        "errors": report.errors,
        "fidelity": {
            "source_screenshots_dir": report.fidelity.source_screenshots_dir,
            "output_screenshots_dir": report.fidelity.output_screenshots_dir,
            "manual_review_required": report.fidelity.manual_review_required,
            "warnings": report.fidelity.warnings,
            "expected_source_screenshot_count": report.fidelity.expected_source_screenshot_count,
            "actual_source_screenshot_count": report.fidelity.actual_source_screenshot_count,
            "missing_source_screenshot_count": report.fidelity.missing_source_screenshot_count,
            "expected_output_screenshot_count": report.fidelity.expected_output_screenshot_count,
            "actual_output_screenshot_count": report.fidelity.actual_output_screenshot_count,
            "missing_output_screenshot_count": report.fidelity.missing_output_screenshot_count,
        },
        "report_path": str(report.report_path),
    }


def _output_path(output: dict[str, Any], run_name: str) -> Path:
    if "path" not in output:
        if not SAFE_RUN_NAME_PATTERN.fullmatch(run_name):
            raise AssembleManifestError("run_name must use only letters, numbers, hyphens, and underscores when output.path is omitted.")
        return Path(f".gstack/assembled/{run_name}/output.pptx")
    path_text = _required_string(output.get("path"), "output.path")
    return Path(path_text).expanduser()


def _object_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AssembleManifestError(f"{field_name} must be a JSON object.")
    return value


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssembleManifestError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _string_value(value: Any, default: str, field_name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise AssembleManifestError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _enum_value(value: Any, default: str, field_name: str, allowed_values: frozenset[str]) -> str:
    normalized = _string_value(value, default, field_name)
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise AssembleManifestError(f"{field_name} must be one of: {allowed}.")
    return normalized


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AssembleManifestError(f"{field_name} must be a string.")
    return value


def _bool_value(value: Any, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise AssembleManifestError(f"{field_name} must be a boolean.")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AssembleManifestError(f"{field_name} must be a positive integer.")
    return value


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise AssembleManifestError(f"{field_name} must be an integer.")
    return value


__all__ = [
    "AssembleFidelityReport",
    "AssembleManifest",
    "AssembleManifestError",
    "AssembleReport",
    "AssembleRunError",
    "AssembleSlideReport",
    "AssembleSlideSpec",
    "load_assemble_manifest",
    "run_assemble",
]
