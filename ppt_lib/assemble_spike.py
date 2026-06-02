from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AssembleSpikeManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssembleSpikeSample:
    id: str
    path: Path
    slides: list[int]
    expected_complexity: list[str]


@dataclass(frozen=True)
class AssembleSpikeManifest:
    version: str
    samples: list[AssembleSpikeSample]
    routes: list[str]


@dataclass(frozen=True)
class AssembleSpikeRouteResult:
    route: str
    status: str
    output_path: str | None
    warnings: list[str]
    evidence: dict[str, object]


@dataclass(frozen=True)
class AssembleSpikeReport:
    generated_at: str
    manifest_version: str
    sample_count: int
    route_results: list[AssembleSpikeRouteResult]
    recommendation: str
    report_path: str


def load_assemble_spike_manifest(path: Path) -> AssembleSpikeManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssembleSpikeManifestError(f"Cannot read assemble spike manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AssembleSpikeManifestError(f"Invalid assemble spike manifest JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AssembleSpikeManifestError("Assemble spike manifest must be a JSON object.")
    raw_samples = raw.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise AssembleSpikeManifestError("Assemble spike manifest must contain a non-empty samples array.")
    routes = raw.get("routes", ["xml-inspection", "image-baseline"])
    if not isinstance(routes, list) or not routes:
        raise AssembleSpikeManifestError("routes must be a non-empty array.")
    return AssembleSpikeManifest(
        version=str(raw.get("version", "1.0")),
        samples=[_parse_sample(item) for item in raw_samples],
        routes=[str(item) for item in routes],
    )


def run_assemble_spike(manifest: AssembleSpikeManifest, output_dir: Path) -> AssembleSpikeReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    generated_at = now.isoformat()
    run_id = now.strftime("%Y%m%d%H%M%S%f")
    route_results = [_run_route(route, manifest, output_dir, run_id) for route in manifest.routes]
    report_path = output_dir / f"assemble-spike-report-{run_id}.json"
    report = AssembleSpikeReport(
        generated_at=generated_at,
        manifest_version=manifest.version,
        sample_count=len(manifest.samples),
        route_results=route_results,
        recommendation=_recommend(route_results),
        report_path=str(report_path),
    )
    report_path.write_text(json.dumps(_report_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _parse_sample(item: Any) -> AssembleSpikeSample:
    if not isinstance(item, dict):
        raise AssembleSpikeManifestError("Each sample must be a JSON object.")
    sample_id = str(item.get("id", "")).strip()
    path_text = str(item.get("path", "")).strip()
    slides = _positive_int_list(item.get("slides", []), "slides")
    if not sample_id:
        raise AssembleSpikeManifestError("Each sample must include id.")
    if not path_text:
        raise AssembleSpikeManifestError(f"Sample {sample_id} must include path.")
    return AssembleSpikeSample(
        id=sample_id,
        path=Path(path_text).expanduser(),
        slides=slides,
        expected_complexity=[str(value) for value in item.get("expected_complexity", [])],
    )


def _run_route(route: str, manifest: AssembleSpikeManifest, output_dir: Path, run_id: str) -> AssembleSpikeRouteResult:
    if route == "xml-inspection":
        return _run_xml_inspection(manifest, output_dir, run_id)
    if route == "image-baseline":
        missing_warnings = _missing_sample_warnings(manifest.samples)
        return AssembleSpikeRouteResult(
            route,
            "needs_manual_review",
            None,
            [*missing_warnings, "Image baseline requires rendered visual diff inspection before production assemble."],
            {"samples": [sample.id for sample in manifest.samples]},
        )
    return AssembleSpikeRouteResult(route, "unsupported", None, [f"Unsupported route: {route}"], {})


def _run_xml_inspection(manifest: AssembleSpikeManifest, output_dir: Path, run_id: str) -> AssembleSpikeRouteResult:
    warnings: list[str] = []
    inspected: list[dict[str, object]] = []
    for sample in manifest.samples:
        if not sample.path.exists():
            warnings.append(f"Missing sample: {sample.path}")
            continue
        try:
            with zipfile.ZipFile(sample.path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            warnings.append(f"Sample is not a valid PPTX zip: {sample.path}")
            continue
        missing_slides = [slide for slide in sample.slides if f"ppt/slides/slide{slide}.xml" not in names]
        if missing_slides:
            warnings.append(f"Sample {sample.id} is missing slide XML for: {missing_slides}")
        inspected.append(
            {
                "id": sample.id,
                "path": str(sample.path),
                "requested_slides": sample.slides,
                "missing_slides": missing_slides,
                "layout_count": len([name for name in names if name.startswith("ppt/slideLayouts/") and name.endswith(".xml")]),
                "media_count": len([name for name in names if name.startswith("ppt/media/")]),
                "complexity": sample.expected_complexity,
            }
        )
    evidence_path = output_dir / f"xml-inspection-evidence-{run_id}.json"
    evidence_path.write_text(json.dumps(inspected, ensure_ascii=False, indent=2), encoding="utf-8")
    if not inspected:
        status = "skipped"
    else:
        status = "passed" if not warnings else "needs_manual_review"
    return AssembleSpikeRouteResult(
        "xml-inspection",
        status,
        str(evidence_path),
        warnings,
        {"inspected_sample_count": len(inspected), "evidence_path": str(evidence_path)},
    )


def _missing_sample_warnings(samples: list[AssembleSpikeSample]) -> list[str]:
    return [f"Missing sample: {sample.path}" for sample in samples if not sample.path.exists()]


def _recommend(results: list[AssembleSpikeRouteResult]) -> str:
    passed = [item.route for item in results if item.status == "passed"]
    if passed:
        return f"Use {passed[0]} as the next prototype route, then verify visual fidelity manually."
    needs_review = [item.route for item in results if item.status == "needs_manual_review"]
    if needs_review:
        return f"Continue manual fidelity review for {needs_review[0]} before production assemble."
    return "No assemble route is ready for production; fix skipped or unsupported routes first."


def _positive_int_list(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise AssembleSpikeManifestError(f"{field_name} must be a non-empty array.")
    try:
        parsed = [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise AssembleSpikeManifestError(f"{field_name} must contain positive 1-based slide numbers.") from exc
    if any(item <= 0 for item in parsed):
        raise AssembleSpikeManifestError(f"{field_name} must contain positive 1-based slide numbers.")
    return parsed


def _report_to_json(report: AssembleSpikeReport) -> dict[str, object]:
    return {
        "generated_at": report.generated_at,
        "manifest_version": report.manifest_version,
        "sample_count": report.sample_count,
        "route_results": [
            {
                "route": item.route,
                "status": item.status,
                "output_path": item.output_path,
                "warnings": item.warnings,
                "evidence": item.evidence,
            }
            for item in report.route_results
        ],
        "recommendation": report.recommendation,
        "report_path": report.report_path,
    }
