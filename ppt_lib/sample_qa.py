from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ppt_lib.config import ensure_dirs, load_settings
from ppt_lib.db import connect, get_stats, init_db
from ppt_lib.discovery import DiscoveryError, scan_presentations
from ppt_lib.embedding import EmbeddingProviderError, build_embedding_provider
from ppt_lib.indexer import ErrorRecord, index_file
from ppt_lib.searcher import SearchError, SearchOptions, get_search_index_stats, search
from ppt_lib.settings import Settings

SamplePhase = Literal["baseline", "complex", "all"]
SAMPLE_MANIFEST_ENV = "PPT_LIB_SAMPLE_MANIFEST"
DEFAULT_SAMPLE_MANIFEST_PATH = Path(".gstack/local-sample-manifest.json")
QA_HOME_SENTINEL = ".ppt-library-sample-qa-home"
QA_HOME_SENTINEL_CONTENT = "ppt-library-sample-qa:v1\n"


class SampleQaManifestError(RuntimeError):
    pass


class SampleQaSafetyError(RuntimeError):
    def __init__(self, message: str, *, code: str = "QA_FRESH_HOME_NOT_OWNED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SampleSpec:
    label: str
    phase: Literal["baseline", "complex"]
    path: Path
    expected_complexity: str


SEARCH_QUERIES = ["AI 智能体", "数据治理", "CMS 部署", "SCRM", "微信小店", "营销自动化"]
SEARCH_GOLDSET = {
    "AI 智能体": ["AI 智能体", "云栖", "AIpersona", "Agent"],
    "数据治理": ["数据治理"],
    "CMS 部署": ["CMS", "部署"],
    "SCRM": ["SCRM", "示例卤味品牌"],
    "微信小店": ["微信小店", "示例美妆品牌"],
    "营销自动化": ["营销自动化", "SCRM", "营销"],
}


def load_samples(manifest_path: Path | None = None) -> list[SampleSpec]:
    path = _resolve_manifest_path(manifest_path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SampleQaManifestError(f"Cannot load sample manifest {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise SampleQaManifestError(f"Sample manifest must be a list: {path}")
    samples: list[SampleSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SampleQaManifestError(f"Sample manifest item {index} must be an object")
        phase = item.get("phase")
        if phase not in {"baseline", "complex"}:
            raise SampleQaManifestError(f"Sample manifest item {index} has invalid phase: {phase}")
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise SampleQaManifestError(f"Sample manifest item {index} missing path")
        samples.append(
            SampleSpec(
                label=str(item.get("label") or f"sample-{index}"),
                phase=phase,
                path=Path(path_value).expanduser().resolve(strict=False),
                expected_complexity=str(item.get("expected_complexity") or ""),
            )
        )
    return samples


def select_samples(
    phase: SamplePhase,
    max_files: int | None = None,
    *,
    samples: list[SampleSpec] | None = None,
    manifest_path: Path | None = None,
) -> list[SampleSpec]:
    pool = samples if samples is not None else load_samples(manifest_path)
    if phase == "baseline":
        selected = [sample for sample in pool if sample.phase == "baseline"]
    elif phase == "complex":
        selected = [sample for sample in pool if sample.phase == "complex"]
    else:
        selected = list(pool)
    return selected[:max_files] if max_files is not None else selected


def build_local_sample_settings(home_dir: Path, *, vision_limit: int | None = 3) -> Settings:
    return load_settings(
        {
            "home_dir": home_dir,
            "embedding_provider": "lmstudio",
            "lmstudio_embedding_model": "text-embedding-nomic-embed-text-v1.5",
            "embedding_dimensions": 768,
            "vision_provider": "lmstudio",
            "lmstudio_vision_model": "google/gemma-4-26b-a4b",
            "lmstudio_base_url": "http://127.0.0.1:1234/v1",
            "vision_max_slides_per_file": vision_limit,
            "search_threshold": 0.0,
        },
        config_path=home_dir / "config.yml",
    )


def run_local_sample_qa(
    *,
    phase: SamplePhase = "baseline",
    max_files: int | None = None,
    home_dir: Path = Path(".gstack/local-sample-qa-home"),
    report_dir: Path = Path(".gstack/qa-reports"),
    manifest_path: Path | None = None,
    vision_limit: int | None = 3,
    full: bool = True,
    fresh: bool = False,
) -> dict[str, Any]:
    if fresh:
        _reset_generated_home(home_dir)
    settings = build_local_sample_settings(home_dir, vision_limit=vision_limit)
    ensure_dirs(settings)
    source_manifest_path = _resolve_manifest_path(manifest_path)
    samples = select_samples(phase, max_files=max_files, manifest_path=source_manifest_path)
    preflight = run_preflight(settings)
    embedding_ready = _check_status(preflight, "embedding_smoke") == "ok"
    discovery_rows = run_discovery_checks(samples, settings)

    sample_rows = []
    for sample in samples:
        started = time.perf_counter()
        if not sample.path.exists():
            sample_rows.append(_missing_sample_row(sample))
            continue
        if not embedding_ready:
            row = _sample_base_row(sample)
            row.update(
                {
                    "status": "skipped",
                    "status_reason": "embedding preflight failed",
                    "slides_indexed": 0,
                    "duration_seconds": _duration_seconds(started),
                    "warnings": [],
                    "errors": ["embedding preflight failed"],
                }
            )
            sample_rows.append(row)
            continue
        result = index_file(sample.path, settings, full=full)
        row = _sample_base_row(sample)
        row.update(
            {
                "status": result.status,
                "status_reason": _sample_status_reason(result.status),
                "slides_indexed": result.slides_indexed,
                "duration_seconds": _duration_seconds(started),
                "warnings": result.warnings,
                "errors": [_error_to_text(error) for error in result.errors],
            }
        )
        sample_rows.append(row)

    status_payload = _status_payload(settings)
    search_index_payload = _search_index_payload(settings)
    search_rows = _run_searches(settings, enabled=embedding_ready and int(search_index_payload["searchable_embeddings"]) > 0)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": phase,
        "fresh": fresh,
        "home_dir": str(settings.home_dir),
        "source_manifest_path": str(source_manifest_path),
        "vision_limit": vision_limit,
        "preflight": preflight,
        "discovery": discovery_rows,
        "samples": sample_rows,
        "status": status_payload,
        "search_index": search_index_payload,
        "searches": search_rows,
    }
    report["overall_status"] = _overall_status(report)
    report_dir.mkdir(parents=True, exist_ok=True)
    selection_path = write_manifest(samples, report_dir)
    report_path = write_markdown_report(report, report_dir)
    latest_json_path = report_dir / "local-sample-qa-latest.json"
    report["selection_path"] = str(selection_path)
    report["report_path"] = str(report_path)
    report["json_path"] = str(latest_json_path)
    latest_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_discovery_checks(samples: list[SampleSpec], settings: Settings) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        if not sample.path.exists():
            rows.append({"label": sample.label, "status": "missing", "discovered_count": 0, "path": str(sample.path)})
            continue
        try:
            items = scan_presentations(sample.path.parent, settings)
        except DiscoveryError as exc:
            rows.append(
                {
                    "label": sample.label,
                    "status": "failed",
                    "error": f"{exc.code}: {exc}",
                    "discovered_count": 0,
                    "path": str(sample.path),
                }
            )
            continue
        matched = any(item.path == sample.path for item in items)
        rows.append(
            {
                "label": sample.label,
                "status": "ok" if matched else "warning",
                "discovered_count": len(items),
                "path": str(sample.path),
            }
        )
    return rows


def run_preflight(settings: Settings) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    models_url = f"{settings.lmstudio_base_url.rstrip('/')}/models"
    try:
        models_payload = _get_json(models_url)
        model_ids = _model_ids(models_payload)
        missing = [
            model
            for model in [settings.lmstudio_embedding_model, settings.lmstudio_vision_model]
            if model not in model_ids
        ]
        checks.append(
            {
                "name": "lmstudio_models",
                "status": "ok" if not missing else "warning",
                "message": "required models listed" if not missing else f"missing listed models: {', '.join(missing)}",
                "details": {"url": models_url, "models": model_ids},
            }
        )
    except Exception as exc:
        checks.append({"name": "lmstudio_models", "status": "warning", "message": str(exc), "details": {"url": models_url}})

    try:
        vector = build_embedding_provider(settings).encode("PPT Library local embedding smoke")
        checks.append(
            {
                "name": "embedding_smoke",
                "status": "ok",
                "message": f"embedding ready: {vector.shape[0]} dimensions",
                "details": {"model": settings.lmstudio_embedding_model, "dimensions": int(vector.shape[0])},
            }
        )
    except EmbeddingProviderError as exc:
        checks.append({"name": "embedding_smoke", "status": "error", "message": str(exc), "details": {"code": exc.code}})
    return checks


def write_manifest(samples: list[SampleSpec], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "local-sample-manifest.json"
    path.write_text(
        json.dumps(
            [
                {
                    "label": sample.label,
                    "phase": sample.phase,
                    "path": str(sample.path),
                    "expected_complexity": sample.expected_complexity,
                    "exists": sample.path.exists(),
                    "file_size": sample.path.stat().st_size if sample.path.exists() else None,
                }
                for sample in samples
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_markdown_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = _compact_timestamp(str(report.get("generated_at") or datetime.now(UTC).isoformat()))
    path = report_dir / f"local-sample-qa-{stamp}.md"
    lines = [
        "# PPT Library Local Sample QA",
        "",
        f"- Phase: `{report.get('phase')}`",
        f"- Fresh run: `{report.get('fresh', False)}`",
        f"- Overall status: `{report.get('overall_status', 'unknown')}`",
        f"- Home dir: `{report.get('home_dir', '')}`",
        f"- Source manifest: `{report.get('source_manifest_path', '')}`",
        f"- Vision limit: `{report.get('vision_limit')}`",
        "",
        "## Preflight",
        "",
        "| Check | Status | Message |",
        "|---|---|---|",
    ]
    for check in report.get("preflight", []):
        lines.append(f"| {check.get('name')} | {check.get('status')} | {_escape_table(str(check.get('message', '')))} |")
    lines.extend(["", "## Discovery", "", "| Label | Status | Discovered Count | Path |", "|---|---|---:|---|"])
    for item in report.get("discovery", []):
        lines.append(f"| {item.get('label')} | {item.get('status')} | {item.get('discovered_count', 0)} | `{item.get('path')}` |")
    lines.extend(
        [
            "",
            "## Samples",
            "",
            "| Label | Phase | Status | Slides | Seconds | Warnings | Errors | Path |",
            "|---|---|---|---:|---:|---|---|---|",
        ]
    )
    for sample in report.get("samples", []):
        warnings = "; ".join(str(warning) for warning in sample.get("warnings", []))
        errors = "; ".join(str(error) for error in sample.get("errors", []))
        lines.append(
            "| "
            f"{sample.get('label')} | {sample.get('phase')} | {sample.get('status')} | "
            f"{sample.get('slides_indexed', 0)} | {sample.get('duration_seconds', 0.0)} | "
            f"{_escape_table(warnings)} | {_escape_table(errors)} | `{sample.get('path')}` |"
        )
    lines.extend(["", "## Searches", "", "| Query | Status | Quality | Top Results |", "|---|---|---|---|"])
    for item in report.get("searches", []):
        titles = ", ".join(str(result.get("title") or result.get("source_file")) for result in item.get("top_results", []))
        lines.append(f"| {item.get('query')} | {item.get('status')} | {item.get('quality_status', '')} | {_escape_table(titles)} |")
    lines.extend(["", "## Search Index", "", "```json", json.dumps(report.get("search_index", {}), ensure_ascii=False, indent=2), "```"])
    lines.extend(["", "## Status", "", "```json", json.dumps(report.get("status", {}), ensure_ascii=False, indent=2), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _run_searches(settings: Settings, *, enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return [
            {
                "query": query,
                "status": "skipped",
                "result_count": 0,
                "top_results": [],
                **_evaluate_search_quality(query, []),
            }
            for query in SEARCH_QUERIES
        ]
    rows: list[dict[str, Any]] = []
    for query in SEARCH_QUERIES:
        try:
            results = search(query, SearchOptions(top_k=3, threshold=0.0), settings)
        except (SearchError, EmbeddingProviderError) as exc:
            rows.append({"query": query, "status": "failed", "error": str(exc), "top_results": []})
            continue
        status = "ok" if results else "warning"
        top_results = [
            {
                "title": result.title,
                "score": result.score,
                "source_file": str(result.source_file),
                "page_number": result.page_number,
            }
            for result in results
        ]
        rows.append(
            {
                "query": query,
                "status": status,
                "result_count": len(results),
                "error": None if results else "no search results",
                "top_results": top_results,
                **_evaluate_search_quality(query, top_results),
            }
        )
    return rows


def _evaluate_search_quality(query: str, top_results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_keywords = SEARCH_GOLDSET.get(query, [])
    if not top_results:
        return {
            "expected_source_keywords": expected_keywords,
            "matched_expected_source": False,
            "matched_keywords": [],
            "quality_status": "empty",
        }
    if not expected_keywords:
        return {
            "expected_source_keywords": expected_keywords,
            "matched_expected_source": False,
            "matched_keywords": [],
            "quality_status": "not_evaluated",
        }
    haystacks = [
        " ".join(str(result.get(key) or "") for key in ["title", "source_file", "page_number"]).lower()
        for result in top_results
    ]
    matched_keywords = [
        keyword
        for keyword in expected_keywords
        if any(keyword.lower() in haystack for haystack in haystacks)
    ]
    return {
        "expected_source_keywords": expected_keywords,
        "matched_expected_source": bool(matched_keywords),
        "matched_keywords": matched_keywords,
        "quality_status": "matched" if matched_keywords else "off_target",
    }


def _status_payload(settings: Settings) -> dict[str, Any]:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    return asdict(get_stats(conn))


def _search_index_payload(settings: Settings) -> dict[str, Any]:
    stats = get_search_index_stats(settings)
    return {
        "configured_dimensions": stats.configured_dimensions,
        "total_embeddings": stats.total_embeddings,
        "searchable_embeddings": stats.searchable_embeddings,
        "skipped_embeddings": stats.skipped_embeddings,
        "dimension_counts": {str(key): value for key, value in sorted(stats.dimension_counts.items())},
    }


def _missing_sample_row(sample: SampleSpec) -> dict[str, Any]:
    row = _sample_base_row(sample)
    row.update(
        {
            "status": "missing",
            "status_reason": "file not found",
            "slides_indexed": 0,
            "duration_seconds": 0.0,
            "warnings": [],
            "errors": ["file not found"],
        }
    )
    return row


def _sample_base_row(sample: SampleSpec) -> dict[str, Any]:
    exists = sample.path.exists()
    return {
        "label": sample.label,
        "phase": sample.phase,
        "path": str(sample.path),
        "expected_complexity": sample.expected_complexity,
        "exists": exists,
        "file_size": sample.path.stat().st_size if exists else None,
        "duration_seconds": 0.0,
    }


def _sample_status_reason(status: str) -> str:
    if status == "indexed":
        return "indexed in this run"
    if status == "skipped":
        return "unchanged from existing index"
    if status == "failed":
        return "indexing failed"
    return status


def _overall_status(report: dict[str, Any]) -> str:
    preflight_statuses = {str(check.get("status")) for check in report.get("preflight", [])}
    sample_statuses = {str(sample.get("status")) for sample in report.get("samples", [])}
    search_statuses = {str(item.get("status")) for item in report.get("searches", [])}
    discovery_statuses = {str(item.get("status")) for item in report.get("discovery", [])}
    status_payload = report.get("status", {})
    failed_jobs = int(status_payload.get("failed_job_count", 0)) if isinstance(status_payload, dict) else 0
    if (
        "error" in preflight_statuses
        or failed_jobs > 0
        or "failed" in sample_statuses
        or "failed" in search_statuses
        or "failed" in discovery_statuses
    ):
        return "failed"
    if "warning" in preflight_statuses:
        return "warning"
    search_index = report.get("search_index", {})
    skipped_embeddings = int(search_index.get("skipped_embeddings", 0)) if isinstance(search_index, dict) else 0
    if skipped_embeddings > 0:
        return "warning"
    if any(sample.get("warnings") for sample in report.get("samples", [])):
        return "warning"
    if "missing" in sample_statuses or search_statuses & {"warning", "skipped"} or discovery_statuses & {"warning", "missing"}:
        return "warning"
    return "passed"


def _check_status(checks: list[dict[str, Any]], name: str) -> str | None:
    for check in checks:
        if check.get("name") == name:
            status = check.get("status")
            return str(status) if status is not None else None
    return None


def _error_to_text(error: ErrorRecord) -> str:
    return f"{error.code}: {error.message}"


def _reset_generated_home(home_dir: Path) -> None:
    expanded_root = home_dir.expanduser()
    if expanded_root.is_symlink():
        raise SampleQaSafetyError(f"Refusing to reset symlinked sample QA home: {expanded_root}")
    root = expanded_root.resolve(strict=False)
    production_home = (Path.home() / ".ppt-library").resolve(strict=False)
    if root == production_home:
        raise SampleQaSafetyError(f"Refusing to reset the primary PPT Library home: {root}")
    if not root.exists():
        root.mkdir(parents=True, exist_ok=False)
        (root / QA_HOME_SENTINEL).write_text(QA_HOME_SENTINEL_CONTENT, encoding="utf-8")
        return
    if not root.is_dir():
        raise SampleQaSafetyError(f"Sample QA home is not a directory: {root}")
    sentinel = root / QA_HOME_SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file():
        raise SampleQaSafetyError(f"Refusing to reset unowned sample QA home without a valid sentinel: {root}")
    try:
        sentinel_content = sentinel.read_text(encoding="utf-8")
    except OSError as exc:
        raise SampleQaSafetyError(f"Cannot read sample QA home sentinel: {sentinel}") from exc
    if sentinel_content != QA_HOME_SENTINEL_CONTENT:
        raise SampleQaSafetyError(f"Refusing to reset sample QA home with an invalid sentinel: {root}")
    for name in [
        "config.yml",
        "index.db",
        "index.db-shm",
        "index.db-wal",
        "screenshots",
        "symlinks",
        "html",
        "logs",
        "backups",
    ]:
        target = root / name
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def _duration_seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Cannot read {url}: non-object JSON")
    return payload


def _model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids = [item.get("id") for item in data if isinstance(item, dict)]
    return sorted(str(item) for item in ids if item)


def _compact_timestamp(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace(".", "").replace("+", "Z")[:15]


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _resolve_manifest_path(manifest_path: Path | None) -> Path:
    if manifest_path is not None:
        return manifest_path.expanduser().resolve(strict=False)
    return Path(os.environ.get(SAMPLE_MANIFEST_ENV, str(DEFAULT_SAMPLE_MANIFEST_PATH))).expanduser().resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ppt_lib.sample_qa")
    parser.add_argument("--phase", choices=["baseline", "complex", "all"], default="baseline")
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--home-dir", type=Path, default=Path(".gstack/local-sample-qa-home"))
    parser.add_argument("--report-dir", type=Path, default=Path(".gstack/qa-reports"))
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--vision-limit", type=int, default=3)
    parser.add_argument("--no-full", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args(argv)
    report = run_local_sample_qa(
        phase=args.phase,
        max_files=args.max_files,
        home_dir=args.home_dir,
        report_dir=args.report_dir,
        manifest_path=args.manifest,
        vision_limit=args.vision_limit,
        full=not args.no_full,
        fresh=args.fresh,
    )
    print(json.dumps({"overall_status": report["overall_status"], "report_path": report["report_path"]}, ensure_ascii=False))
    return 1 if report["overall_status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
