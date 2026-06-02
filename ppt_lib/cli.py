from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, NoReturn, cast

from ppt_lib.assemble_ingest import AssembleIngestError, ingest_assemble_output
from ppt_lib.assemble_spike import AssembleSpikeManifestError, load_assemble_spike_manifest, run_assemble_spike
from ppt_lib.assembler import AssembleManifestError, AssembleRunError, load_assemble_manifest, run_assemble
from ppt_lib.config import (
    ConfigCommandError,
    ConfigError,
    config_path_for_home,
    get_effective_config,
    load_settings,
    resolve_home_dir,
    set_config_value,
    settings_summary,
    write_setup_config,
)
from ppt_lib.db import (
    DatabaseError,
    connect,
    create_workspace_profile,
    get_active_workspace_profile,
    get_stats,
    init_db,
    insert_deal,
    list_failed_jobs,
    list_orphan_presentations,
    recompute_slide_stats,
    record_slide_usage,
    upsert_library_source,
)
from ppt_lib.diagnostics import run_diagnostics
from ppt_lib.discovery import DiscoveryError, create_symlink_view, deduplicate_versions, scan_presentations
from ppt_lib.doctor import run_doctor
from ppt_lib.embedding import EmbeddingProviderError
from ppt_lib.enrichment import enrich_pending_slides, profile_payload_from_row
from ppt_lib.evaluation import (
    EvaluationManifestError,
    calibrate_search_thresholds,
    evaluate_search_manifest,
    load_evaluation_manifest,
)
from ppt_lib.html_renderer import HtmlRenderOptions, render_search_review
from ppt_lib.indexer import ErrorRecord, extract_pptx_text, index_batch, index_file
from ppt_lib.metadata import MetadataJsonlError, export_metadata_jsonl, import_metadata_jsonl
from ppt_lib.model_compat import detect_lmstudio_chat_model
from ppt_lib.pptx_package import PptxPackageError
from ppt_lib.profile import build_workspace_profile_payload
from ppt_lib.prune import prune_orphans, purge_assembled_output
from ppt_lib.sample_qa import SampleQaManifestError, run_local_sample_qa
from ppt_lib.searcher import SearchError, SearchOptions, search
from ppt_lib.selector import NARRATIVE_ROLES, record_selection_usage, select_slides, select_slides_from_plan
from ppt_lib.setup_probe import detect_environment, recommend_setup
from ppt_lib.sources import (
    ALLOWED_SOURCE_ROLES,
    SourceError,
    add_source,
    collect_pptx_files,
    load_sources_manifest,
    load_sources_profile,
    risky_source_warnings,
    scan_sources,
    source_profile_hash,
    validate_scan_state_for_index,
    write_scan_state,
    write_sources_profile,
)
from ppt_lib.versioning import enrich_pending_decks, get_version_status, inspect_deck_family, recompute_deck_versions
from ppt_lib.watch import WatchRuntimeError, watch_directory


def build_envelope(
    command: str,
    payload: dict[str, object],
    errors: list[ErrorRecord],
    *,
    schema_version: str = "1.0",
) -> dict[str, object]:
    return {
        "_meta": {
            "schema_version": schema_version,
            "command": command,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        **payload,
        "_errors": [_error_to_json(error) for error in errors],
    }


def _output_mode(args: argparse.Namespace) -> str:
    requested = getattr(args, "output", "auto")
    if requested == "json":
        return "json"
    if requested == "text":
        return "text"
    if requested == "auto":
        return "text" if sys.stdout.isatty() else "json"
    return "json"


def _print_command_output(
    command: str,
    payload: dict[str, object],
    errors: list[ErrorRecord],
    *,
    schema_version: str,
    output_mode: str,
) -> None:
    if output_mode == "text":
        text = _human_output(command, payload, errors)
        if text is not None:
            print(text)
            return
    print(json.dumps(build_envelope(command, payload, errors, schema_version=schema_version), default=_json_default))


class CLIUsageError(RuntimeError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CLIUsageError(message)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not _argv_has_command(argv):
        print(_plain_help_text(_package_version()))
        return 0

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CLIUsageError as exc:
        error = ErrorRecord("CLI_USAGE_ERROR", str(exc), "cli")
        print(json.dumps(build_envelope("unknown", {}, [error]), default=_json_default))
        return 2
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if args.command == "config":
        return _run_config_command(args)

    try:
        settings = load_settings({"home_dir": Path(args.home_dir)} if args.home_dir else {})
        payload, errors = _dispatch(args, settings)
        output_mode = _output_mode(args)
        _print_command_output(args.command, payload, errors, schema_version=settings.schema_version, output_mode=output_mode)
        return 1 if any(error.severity == "error" for error in errors) else 0
    except ConfigError as exc:
        error = ErrorRecord("CONFIG_ERROR", str(exc), "config")
        print(json.dumps(build_envelope(getattr(args, "command", "unknown"), {}, [error]), default=_json_default))
        return 1
    except Exception as exc:
        error = ErrorRecord("INTERNAL_ERROR", str(exc), "cli")
        print(json.dumps(build_envelope(getattr(args, "command", "unknown"), {}, [error]), default=_json_default))
        return 1


def _argv_has_command(argv: list[str]) -> bool:
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--home-dir":
            if index + 1 >= len(argv):
                return True
            index += 2
            continue
        if arg.startswith("--home-dir="):
            index += 1
            continue
        if arg in {"-h", "--help", "--version"}:
            return True
        if not arg.startswith("-"):
            return True
        index += 1
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="ppt-lib")
    parser.add_argument("--home-dir")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    setup_parser = subparsers.add_parser("setup", help="create local config and run diagnostics")
    setup_parser.add_argument(
        "--mode",
        choices=["lmstudio", "openai", "text-extraction", "text_extraction"],
        default=None,
        help="configuration mode to write",
    )
    setup_parser.add_argument("--quick", action="store_true", help="auto-detect best config")
    setup_parser.add_argument("--non-interactive", action="store_true", help="run without prompts")
    setup_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto", help="output format")

    init_parser = subparsers.add_parser("init", help="bootstrap source profiles from a manifest")
    init_parser.add_argument("--manifest", type=Path)
    init_parser.add_argument("--non-interactive", action="store_true")
    init_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto", help="output format")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True, parser_class=JsonArgumentParser)
    config_subparsers.add_parser("path")
    config_get_parser = config_subparsers.add_parser("get")
    config_get_parser.add_argument("key", nargs="?")
    config_set_parser = config_subparsers.add_parser("set")
    config_set_parser.add_argument("key")
    config_set_parser.add_argument("value")

    qa_parser = subparsers.add_parser("qa")
    qa_subparsers = qa_parser.add_subparsers(dest="qa_command", required=True, parser_class=JsonArgumentParser)
    qa_sample_parser = qa_subparsers.add_parser("sample")
    qa_sample_parser.add_argument("--phase", choices=["baseline", "complex", "all"], default="baseline")
    qa_sample_parser.add_argument("--max-files", type=int)
    qa_sample_parser.add_argument("--home-dir", dest="sample_home_dir", type=Path, default=Path(".gstack/local-sample-qa-home"))
    qa_sample_parser.add_argument("--report-dir", type=Path, default=Path(".gstack/qa-reports"))
    qa_sample_parser.add_argument("--manifest", type=Path, default=None)
    qa_sample_parser.add_argument("--vision-limit", type=int, default=3)
    qa_sample_parser.add_argument("--no-full", action="store_true")
    qa_sample_parser.add_argument("--fresh", action="store_true")

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("path", nargs="?")
    index_parser.add_argument("--batch", action="store_true")
    index_parser.add_argument("--full", action="store_true")
    index_parser.add_argument("--from-sources", action="store_true", help="index library sources from ppt-lib sources profile")
    index_parser.add_argument("--with-ai-summary", action="store_true", help="enrich indexed slides with workspace-profile-aware summaries")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--threshold", type=float, default=0.5)
    search_parser.add_argument("--cluster", action="store_true")
    search_parser.add_argument("--html", action="store_true")
    search_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")
    search_parser.add_argument("--include-assembled", action="store_true")
    search_parser.add_argument("--dedupe-lineage", action="store_true")
    search_parser.add_argument("--ranking", choices=["classic", "business"], default="classic")
    search_parser.add_argument("--narrative-role", choices=NARRATIVE_ROLES)
    search_parser.add_argument("--context", help="Business context for ranking boost (e.g. '制造业pitch')")
    search_parser.add_argument("--include-cache", action="store_true", help="include slides indexed from cache folders")
    search_parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="include duplicate slides instead of canonical results only",
    )
    search_parser.add_argument(
        "--include-versions",
        action="store_true",
        help="include non-representative deck versions in search results",
    )

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("root")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("root")

    vision_parser = subparsers.add_parser("vision")
    vision_parser.add_argument("--test", action="store_true", required=True)

    models_parser = subparsers.add_parser("models", help="probe model capabilities")
    models_subparsers = models_parser.add_subparsers(dest="models_command", required=True, parser_class=JsonArgumentParser)
    models_test_parser = models_subparsers.add_parser("test", help="test all configured model capabilities")
    models_test_parser.add_argument("--json", action="store_true", help="output raw JSON envelope")

    schema_parser = subparsers.add_parser("schema")
    schema_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    eval_parser = subparsers.add_parser("eval-search")
    eval_parser.add_argument("--manifest", required=True)
    eval_parser.add_argument("--top-k", type=int, default=10)
    eval_parser.add_argument("--threshold", type=float, default=0.0)
    eval_parser.add_argument("--calibrate", action="store_true")

    prune_parser = subparsers.add_parser("prune")
    prune_group = prune_parser.add_mutually_exclusive_group()
    prune_group.add_argument("--dry-run", action="store_true")
    prune_group.add_argument("--apply", action="store_true")

    purge_parser = subparsers.add_parser("purge")
    purge_parser.add_argument("--type", choices=["assembled_output"], required=True)
    purge_group = purge_parser.add_mutually_exclusive_group()
    purge_group.add_argument("--dry-run", action="store_true")
    purge_group.add_argument("--apply", action="store_true")

    sources_parser = subparsers.add_parser("sources", help="manage baseline/library/exclude source folders")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True, parser_class=JsonArgumentParser)

    sources_add_parser = sources_subparsers.add_parser("add", help="add one source path for a role")
    sources_add_parser.add_argument("source")
    sources_add_parser.add_argument("--role", choices=ALLOWED_SOURCE_ROLES, default="baseline")
    sources_add_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    sources_list_parser = sources_subparsers.add_parser("list", help="show current source profile")
    sources_list_parser.add_argument("--role", choices=ALLOWED_SOURCE_ROLES)
    sources_list_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    sources_scan_parser = sources_subparsers.add_parser("scan", help="preview files/pptx to be considered")
    sources_scan_parser.add_argument("--role", choices=ALLOWED_SOURCE_ROLES)
    sources_scan_group = sources_scan_parser.add_mutually_exclusive_group()
    sources_scan_group.add_argument("--dry-run", action="store_true", help="仅预览命中文件，不更新或写入（默认）")
    sources_scan_group.add_argument("--apply", action="store_true", help="不作为预览，输出为正式扫描")
    sources_scan_parser.add_argument(
        "--force-risky-sources",
        action="store_true",
        help="明确确认 Home/Downloads/缓存目录等高风险来源后才允许正式扫描",
    )
    sources_scan_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    profile_parser = subparsers.add_parser("profile", help="build or inspect workspace profile from baseline PPTs")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True, parser_class=JsonArgumentParser)
    profile_build_parser = profile_subparsers.add_parser("build")
    profile_build_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")
    profile_show_parser = profile_subparsers.add_parser("show")
    profile_show_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    enrich_parser = subparsers.add_parser("enrich", help="fill AI summaries for indexed slides")
    enrich_parser.add_argument("--pending", action="store_true", required=True)
    enrich_parser.add_argument("--limit", type=int, default=50)
    enrich_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    enrich_decks_parser = subparsers.add_parser("enrich-decks", help="fill deck-level insights and important slide candidates")
    enrich_decks_parser.add_argument("--pending", action="store_true", required=True)
    enrich_decks_parser.add_argument("--limit", type=int, default=50)
    enrich_decks_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    versions_parser = subparsers.add_parser("versions", help="inspect and recompute deck families and versions")
    versions_subparsers = versions_parser.add_subparsers(dest="versions_command", required=True, parser_class=JsonArgumentParser)
    versions_status_parser = versions_subparsers.add_parser("status")
    versions_status_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")
    versions_inspect_parser = versions_subparsers.add_parser("inspect")
    versions_inspect_parser.add_argument("family_id", type=int)
    versions_inspect_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")
    versions_recompute_parser = versions_subparsers.add_parser("recompute")
    versions_recompute_group = versions_recompute_parser.add_mutually_exclusive_group()
    versions_recompute_group.add_argument("--dry-run", action="store_true")
    versions_recompute_group.add_argument("--apply", action="store_true")
    versions_recompute_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    assets_parser = subparsers.add_parser("assets", help="inspect or clean derived preview assets")
    assets_subparsers = assets_parser.add_subparsers(dest="assets_command", required=True, parser_class=JsonArgumentParser)
    assets_status_parser = assets_subparsers.add_parser("status")
    assets_status_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")
    assets_prune_parser = assets_subparsers.add_parser("prune")
    assets_prune_group = assets_prune_parser.add_mutually_exclusive_group()
    assets_prune_group.add_argument("--dry-run", action="store_true")
    assets_prune_group.add_argument("--apply", action="store_true")
    assets_prune_parser.add_argument("--output", choices=["auto", "text", "json"], default="auto")

    record_deal_parser = subparsers.add_parser("record-deal")
    record_deal_parser.add_argument("--name", required=True)
    record_deal_parser.add_argument("--client-type")
    record_deal_parser.add_argument("--stage")
    record_deal_parser.add_argument("--outcome", choices=["won", "lost", "pending", "unknown"], default="unknown")
    record_deal_parser.add_argument("--notes")

    record_usage_parser = subparsers.add_parser("record-usage")
    record_usage_parser.add_argument("--deal-id", type=int, required=True)
    record_usage_parser.add_argument("--slide-id", type=int, required=True)
    record_usage_parser.add_argument("--deck-presentation-id", type=int, required=True)
    record_usage_parser.add_argument("--position", type=int)
    record_usage_parser.add_argument("--assemble-run-id", type=int)
    record_usage_parser.add_argument("--derived", action="store_true")

    recompute_parser = subparsers.add_parser("recompute-stats")
    recompute_parser.add_argument("--slide-id", type=int)

    import_metadata_parser = subparsers.add_parser("import-metadata")
    import_metadata_parser.add_argument("--jsonl", required=True)

    export_metadata_parser = subparsers.add_parser("export-metadata")
    export_metadata_parser.add_argument("--output", required=True)

    annotate_parser = subparsers.add_parser("annotate")
    annotate_parser.add_argument("--batch", type=int, default=50, help="Number of slides to annotate per run")
    annotate_parser.add_argument("--provider", choices=["auto", "lmstudio", "ollama", "cloud"], default="auto")
    annotate_parser.add_argument("--dry-run", action="store_true", help="Output JSONL but don't write to DB")
    annotate_parser.add_argument("--force", action="store_true", help="Re-annotate already annotated slides")
    annotate_parser.add_argument("--output", help="JSONL output path for dry-run results")

    select_parser = subparsers.add_parser("select-slides")
    select_parser.add_argument("--roles")
    select_parser.add_argument("--plan", help="narrative-plan.json file (alternative to --roles)")
    select_parser.add_argument("--brief", default="")
    select_parser.add_argument("--industry")
    select_parser.add_argument("--max-per-role", type=int, default=3)
    select_parser.add_argument("--ranking", choices=["classic", "business"], default="classic")
    select_parser.add_argument("--threshold", type=float, default=0.0)
    select_parser.add_argument("--output", help="write selection-report to file instead of stdout")
    select_parser.add_argument("--record-usage", action="store_true", help="write slide_usage for top-1 per role")
    select_parser.add_argument("--deal-id", type=int, help="deal ID for --record-usage")

    manifest_parser = subparsers.add_parser("build-manifest")
    manifest_parser.add_argument("--selection", required=True)
    manifest_parser.add_argument("--output")
    manifest_parser.add_argument("--strategy", default="top1-per-role")
    manifest_parser.add_argument("--run-name", default="auto-compose")
    manifest_parser.add_argument("--output-pptx")
    manifest_parser.add_argument("--overwrite", action="store_true")

    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--manifest", required=True)
    assemble_parser.add_argument("--ingest-output", action="store_true")

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--roles", help="comma-separated narrative roles (no-LLM path)")
    compose_parser.add_argument("--plan", help="narrative-plan.json (alternative to --roles)")
    compose_parser.add_argument("--confirm", help="execute from a previously saved plan path")
    compose_parser.add_argument("--brief", default="")
    compose_parser.add_argument("--industry")
    compose_parser.add_argument("--max-per-role", type=int, default=3)
    compose_parser.add_argument("--ranking", choices=["classic", "business"], default="classic")
    compose_parser.add_argument("--dry-run", action="store_true", help="generate plan only, don't assemble")
    compose_parser.add_argument("--deal-id", type=int, help="record slide usage for this deal")
    compose_parser.add_argument("--overwrite", action="store_true")
    compose_parser.add_argument("--verbose", action="store_true", help="write compose-timing.json")
    compose_parser.add_argument("--auto", action="store_true", help="skip confirmation (brief→assemble in one shot)")

    assemble_spike_parser = subparsers.add_parser("spike-assemble")
    assemble_spike_parser.add_argument("--manifest", required=True)
    assemble_spike_parser.add_argument("--out-dir")
    return parser


def _run_config_command(args: argparse.Namespace) -> int:
    home_dir = resolve_home_dir(Path(args.home_dir) if args.home_dir else None)
    config_path = config_path_for_home(home_dir)
    payload: dict[str, object] = {}
    errors: list[ErrorRecord] = []
    try:
        if args.config_command == "path":
            payload = {"config_path": str(_normalize_path(config_path))}
        elif args.config_command == "get":
            overrides: dict[str, object] = {"home_dir": home_dir} if args.home_dir else {}
            settings = load_settings(overrides, config_path=config_path)
            payload = get_effective_config(settings, args.key)
        elif args.config_command == "set":
            config_result = set_config_value(config_path, args.key, args.value, home_dir=home_dir)
            payload = _dataclass_to_json(config_result)
    except ConfigCommandError as exc:
        errors = [ErrorRecord(exc.code, str(exc), "config")]
    except ConfigError as exc:
        errors = [ErrorRecord("CONFIG_ERROR", str(exc), "config")]
    print(json.dumps(build_envelope("config", payload, errors), default=_json_default))
    return 1 if any(error.severity == "error" for error in errors) else 0


def _dispatch(args: argparse.Namespace, settings) -> tuple[dict[str, object], list[ErrorRecord]]:
    if args.command == "setup":
        assert settings.home_dir is not None
        config_path = settings.home_dir / "config.yml"

        # Branch 1: --mode explicitly provided → existing behavior
        if args.mode is not None:
            mode = args.mode.replace("-", "_")
            return _run_setup_mode(mode, settings, config_path)

        # Branch 2: --quick → auto-detect and write
        if args.quick:
            return _run_quick_setup(settings, config_path, args)

        # Branch 3: interactive prompt (stdin is tty, not non-interactive)
        if sys.stdin.isatty() and not args.non_interactive:
            return _interactive_setup(settings, config_path)

        # Branch 4: non-interactive without flags → guide user
        return {"mode": None, "config_path": str(_normalize_path(config_path))}, [
            ErrorRecord("SETUP_MODE_REQUIRED", "Specify --mode or --quick when running non-interactively.", "setup"),
        ]
    if args.command == "init":
        if not args.non_interactive:
            return {
                "command": "init",
                "mode": "interactive",
                "status": "ready",
                "instructions": [
                    "请使用 --manifest 指定初始化清单后再执行。",
                    "例如：",
                    "  ppt-lib init --manifest <manifest> --non-interactive",
                    "清单结构示例：",
                    '{"sources": {"baseline": ["/path/to/baseline.pptx"], '
                    '"library": ["/path/to/ppt-folder"], "exclude": ["/path/to/cache", ".stversions"]}}',
                ],
            }, []
        if args.manifest is None:
            return {
                "command": "init",
                "status": "failed",
                "output": "请在非交互模式下通过 --manifest 提供 sources 清单。",
            }, [ErrorRecord("INIT_MANIFEST_REQUIRED", "请提供 --manifest", "cli")]
        try:
            profile = load_sources_manifest(_normalize_path(args.manifest))
        except SourceError as exc:
            return {"command": "init", "status": "failed", "manifest": str(_normalize_path(args.manifest))}, [
                ErrorRecord(exc.code, str(exc), "sources")
            ]
        assert settings.home_dir is not None
        profile_path = write_sources_profile(settings.home_dir, profile)
        source_sync = _sync_source_profile_to_db(settings, profile)
        return {
            "command": "init",
            "mode": "non_interactive",
            "manifest": str(_normalize_path(args.manifest)),
            "profile_path": str(_normalize_path(profile_path)),
            "counts": {role: len(getattr(profile, role)) for role in ["baseline", "library", "exclude"]},
            "sources": profile.to_dict(),
            "db_sources_written": source_sync,
        }, []
    if args.command == "doctor":
        doctor_report = run_doctor(settings)
        summary = doctor_report.get("summary")
        if isinstance(summary, dict) and summary.get("status") == "error":
            return doctor_report, [ErrorRecord("DOCTOR_ERROR", "Doctor found blocking health issues.", "doctor")]
        return doctor_report, []
    if args.command == "qa":
        if args.qa_command == "sample":
            try:
                qa_report = run_local_sample_qa(
                    phase=args.phase,
                    max_files=args.max_files,
                    home_dir=args.sample_home_dir,
                    report_dir=args.report_dir,
                    manifest_path=args.manifest,
                    vision_limit=args.vision_limit,
                    full=not args.no_full,
                    fresh=args.fresh,
                )
            except SampleQaManifestError as exc:
                return {}, [ErrorRecord("QA_SAMPLE_MANIFEST_ERROR", str(exc), "sample_qa")]
            except RuntimeError as exc:
                return {}, [ErrorRecord("QA_SAMPLE_RUNTIME_ERROR", str(exc), "sample_qa")]
            qa_payload = {
                "overall_status": qa_report["overall_status"],
                "report_path": qa_report["report_path"],
                "json_path": qa_report["json_path"],
                "selection_path": qa_report["selection_path"],
                "phase": qa_report["phase"],
                "fresh": qa_report["fresh"],
            }
            if qa_report["overall_status"] == "failed":
                return qa_payload, [ErrorRecord("QA_SAMPLE_FAILED", "Local sample QA failed.", "sample_qa")]
            return qa_payload, []
    if args.command == "sources":
        if args.sources_command == "add":
            try:
                role = args.role
                profile = load_sources_profile(settings.home_dir) if settings.home_dir else load_sources_profile(Path.home())
                profile = add_source(profile, role, args.source)
                assert settings.home_dir is not None
                profile_path = write_sources_profile(settings.home_dir, profile)
                source_sync = _sync_source_profile_to_db(settings, profile)
                return {
                    "command": "sources",
                    "operation": "add",
                    "role": role,
                    "source": str(_normalize_path(Path(args.source))),
                    "profile_path": str(_normalize_path(profile_path)),
                    "counts": {role_name: len(getattr(profile, role_name)) for role_name in ["baseline", "library", "exclude"]},
                    "sources": profile.to_dict(),
                    "db_sources_written": source_sync,
                }, []
            except SourceError as exc:
                return {"command": "sources", "operation": "add"}, [ErrorRecord(exc.code, str(exc), "sources")]
        if args.sources_command == "list":
            try:
                profile = load_sources_profile(settings.home_dir) if settings.home_dir else load_sources_profile(Path.home())
                role = args.role
                if role:
                    source_payload = {role: getattr(profile, role)}
                else:
                    source_payload = profile.to_dict()
                return {
                    "command": "sources",
                    "operation": "list",
                    "role": role,
                    "sources": source_payload,
                    "counts": {role_name: len(getattr(profile, role_name)) for role_name in ["baseline", "library", "exclude"]},
                }, []
            except SourceError as exc:
                return {"command": "sources", "operation": "list"}, [ErrorRecord(exc.code, str(exc), "sources")]
        if args.sources_command == "scan":
            try:
                profile = load_sources_profile(settings.home_dir) if settings.home_dir else load_sources_profile(Path.home())
                roles: list[str] | None = [args.role] if args.role else None
                risk_warnings = risky_source_warnings(profile, roles=roles)
                if args.apply and risk_warnings and not args.force_risky_sources:
                    scan_result = _blocked_source_scan_result(profile, roles=roles)
                    scan_result["command"] = "sources"
                    scan_result["operation"] = "scan"
                    scan_result["dry_run"] = False
                    scan_result["source_profile_hash"] = source_profile_hash(profile)
                    scan_result["risk_warnings"] = risk_warnings
                    return {"operation": "scan", "scan": scan_result, "sources": profile.to_dict()}, [
                        ErrorRecord(
                            "SOURCE_RISK_CONFIRMATION_REQUIRED",
                            "扫描范围包含 Home/Downloads/缓存目录等高风险路径，请确认后追加 --force-risky-sources。",
                            "sources",
                        )
                    ]
                scan_result = scan_sources(profile, roles=roles)
                scan_result["command"] = "sources"
                scan_result["operation"] = "scan"
                scan_result["dry_run"] = not args.apply
                scan_result["source_profile_hash"] = source_profile_hash(profile)
                scan_result["risk_warnings"] = risk_warnings
                if args.apply:
                    assert settings.home_dir is not None
                    scan_state_path = write_scan_state(
                        settings.home_dir,
                        profile,
                        scan_result,
                        roles=roles,
                        risk_warnings=risk_warnings,
                        force_risky_sources=args.force_risky_sources,
                    )
                    scan_result["scan_state_path"] = str(_normalize_path(scan_state_path))
                return {"operation": "scan", "scan": scan_result, "sources": profile.to_dict()}, []
            except SourceError as exc:
                return {"command": "sources", "operation": "scan"}, [ErrorRecord(exc.code, str(exc), "sources")]
        raise ValueError(f"Unknown sources subcommand: {args.sources_command}")
    if args.command == "index":
        if args.from_sources:
            profile = load_sources_profile(settings.home_dir) if settings.home_dir else load_sources_profile(Path.home())
            payload: dict[str, object] = {
                "results": [],
                "source_count": len(profile.library),
                "pptx_count": 0,
            }
            try:
                assert settings.home_dir is not None
                validate_scan_state_for_index(settings.home_dir, profile, roles=["library"])
            except SourceError as exc:
                return payload, [ErrorRecord(exc.code, str(exc), "sources")]
            if args.with_ai_summary and not _active_workspace_profile_ready(settings):
                return payload, [
                    ErrorRecord(
                        "LIBRARY_PROFILE_NOT_READY",
                        "请先用 baseline PPT 完成 `ppt-lib profile build`，并确保 profile ready=true。",
                        "profile",
                    )
                ]
            pptx_files = collect_pptx_files(profile, roles=["library"])
            index_results = [index_file(path, settings, full=args.full) for path in pptx_files]
            payload = {
                "results": [_dataclass_to_json(result) for result in index_results],
                "source_count": len(profile.library),
                "pptx_count": len(pptx_files),
            }
            errors = _collect_errors(index_results)
            if args.with_ai_summary:
                enrich_result = enrich_pending_slides(settings, limit=None)
                payload["enrichment"] = _dataclass_to_json(enrich_result)
                errors.extend(
                    ErrorRecord("ENRICH_WARNING", warning, "enrichment", severity="warning")
                    for warning in enrich_result.warnings
                )
            return payload, errors
        if not args.path:
            raise ValueError("index path is required")
        root = _normalize_path(Path(args.path))
        if args.batch:
            index_results = index_batch(root, settings, full=args.full)
            payload = {"results": [_dataclass_to_json(result) for result in index_results]}
            errors = _collect_errors(index_results)
            if args.with_ai_summary:
                enrich_result = enrich_pending_slides(settings, limit=None)
                payload["enrichment"] = _dataclass_to_json(enrich_result)
                errors.extend(
                    ErrorRecord("ENRICH_WARNING", warning, "enrichment", severity="warning")
                    for warning in enrich_result.warnings
                )
            return payload, errors
        index_result = index_file(root, settings, full=args.full)
        payload = {"result": _dataclass_to_json(index_result)}
        errors = list(index_result.errors)
        if args.with_ai_summary:
            enrich_result = enrich_pending_slides(settings, limit=None)
            payload["enrichment"] = _dataclass_to_json(enrich_result)
            errors.extend(
                ErrorRecord("ENRICH_WARNING", warning, "enrichment", severity="warning")
                for warning in enrich_result.warnings
            )
        return payload, errors
    if args.command == "search":
        try:
            search_results = search(
                args.query,
                SearchOptions(
                    args.top_k,
                    args.threshold,
                    args.cluster,
                    args.include_assembled,
                    args.dedupe_lineage,
                    args.ranking,
                    args.narrative_role,
                    getattr(args, "context", None),
                    args.include_cache,
                    args.include_duplicates,
                    args.include_versions,
                ),
                settings,
            )
        except SearchError as exc:
            return {"results": []}, [ErrorRecord(exc.code, str(exc), "searcher")]
        except EmbeddingProviderError as exc:
            return {"results": []}, [ErrorRecord(exc.code, str(exc), "embedding")]
        search_payload: dict[str, object] = {"results": [_search_result_to_json(result) for result in search_results]}
        if args.html:
            assert settings.html_dir is not None
            html_path = render_search_review(search_results, HtmlRenderOptions(title=f"Search: {args.query}"), settings.html_dir)
            search_payload["html_path"] = str(_normalize_path(html_path))
        return search_payload, []
    if args.command == "profile":
        if args.profile_command == "build":
            return _build_workspace_profile(settings)
        if args.profile_command == "show":
            return _show_workspace_profile(settings)
        raise ValueError(f"Unknown profile subcommand: {args.profile_command}")
    if args.command == "enrich":
        enrich_result = enrich_pending_slides(settings, limit=args.limit)
        errors = [
            ErrorRecord("ENRICH_WARNING", warning, "enrichment", severity="warning")
            for warning in enrich_result.warnings
        ]
        return {"result": _dataclass_to_json(enrich_result)}, errors
    if args.command == "enrich-decks":
        deck_enrich_result = enrich_pending_decks(settings, limit=args.limit)
        errors = [
            ErrorRecord("ENRICH_DECKS_WARNING", warning, "versioning", severity="warning")
            for warning in deck_enrich_result.warnings
        ]
        return {"result": _dataclass_to_json(deck_enrich_result)}, errors
    if args.command == "versions":
        conn = connect(settings.db_path)
        init_db(conn)
        if args.versions_command == "status":
            return {"status": _dataclass_to_json(get_version_status(conn))}, []
        if args.versions_command == "inspect":
            family_payload = inspect_deck_family(conn, args.family_id)
            if family_payload is None:
                return {"family": None, "versions": []}, [
                    ErrorRecord("DECK_FAMILY_NOT_FOUND", f"Deck family not found: {args.family_id}", "versioning")
                ]
            return family_payload, []
        if args.versions_command == "recompute":
            result = recompute_deck_versions(conn, dry_run=not args.apply)
            return {"result": _dataclass_to_json(result)}, []
        raise ValueError(f"Unknown versions subcommand: {args.versions_command}")
    if args.command == "assets":
        if args.assets_command == "status":
            return _assets_status(settings), []
        if args.assets_command == "prune":
            payload = _assets_prune(settings, dry_run=not args.apply)
            return payload, []
        raise ValueError(f"Unknown assets subcommand: {args.assets_command}")
    if args.command == "status":
        conn = connect(settings.db_path)
        init_db(conn)
        status_stats = get_stats(conn)
        # Health metrics: annotation coverage, deals, slide_usage
        annotated_count = conn.execute(
            "SELECT COUNT(*) FROM slides WHERE narrative_role IS NOT NULL"
        ).fetchone()[0]
        total_slides = status_stats.slide_count
        annotated_pct = (annotated_count / total_slides * 100) if total_slides > 0 else 0.0
        deals_count = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        slide_usage_count = conn.execute("SELECT COUNT(*) FROM slide_usage").fetchone()[0]
        return {
            "stats": _dataclass_to_json(status_stats),
            "health": {
                "total_slides": total_slides,
                "annotated_count": annotated_count,
                "annotated_pct": round(annotated_pct, 1),
                "deals_count": deals_count,
                "slide_usage_count": slide_usage_count,
            },
            "failed_jobs": [_dataclass_to_json(job) for job in list_failed_jobs(conn)],
            "orphan_presentations": [_dataclass_to_json(item) for item in list_orphan_presentations(conn)],
        }, []
    if args.command == "discover":
        try:
            items = deduplicate_versions(scan_presentations(_normalize_path(Path(args.root)), settings))
            links = create_symlink_view(items, settings)
        except DiscoveryError as exc:
            return {"items": [], "symlinks": []}, [ErrorRecord(exc.code, str(exc), "discovery")]
        return {
            "items": [_dataclass_to_json(item) for item in items],
            "symlinks": [str(_normalize_path(link)) for link in links],
        }, []
    if args.command == "watch":
        try:
            watch_directory(_normalize_path(Path(args.root)), settings, lambda path: index_file(path, settings))
        except WatchRuntimeError as exc:
            return {"status": "stopped"}, [ErrorRecord(exc.code, str(exc), "watch")]
        except FileNotFoundError as exc:
            return {"status": "failed"}, [ErrorRecord("WATCH_ROOT_NOT_FOUND", str(exc), "watch")]
        return {"status": "completed"}, []
    if args.command == "vision":
        return run_diagnostics(settings).to_json(), []
    if args.command == "models":
        from ppt_lib.models_test import run_models_test

        model_report = run_models_test(settings)
        summary = model_report.get("summary", {})
        if isinstance(summary, dict) and summary.get("status") == "error":
            return model_report, [
                ErrorRecord(
                    "MODEL_COMPATIBILITY_CHECK_FAILED",
                    "One or more model capability probes failed.",
                    "models",
                )
            ]
        return model_report, []
    if args.command == "schema":
        return {"schema": _schema(settings.schema_version)}, []
    if args.command == "eval-search":
        try:
            evaluation_manifest = load_evaluation_manifest(_normalize_path(Path(args.manifest)))
            if args.calibrate:
                return calibrate_search_thresholds(evaluation_manifest, settings, top_k=args.top_k), []
            evaluation_report = evaluate_search_manifest(evaluation_manifest, settings, top_k=args.top_k, threshold=args.threshold)
        except EvaluationManifestError as exc:
            return {"summary": None, "query_results": []}, [ErrorRecord("EVAL_MANIFEST_ERROR", str(exc), "evaluation")]
        except SearchError as exc:
            return {"summary": None, "query_results": []}, [ErrorRecord(exc.code, str(exc), "searcher")]
        except EmbeddingProviderError as exc:
            return {"summary": None, "query_results": []}, [ErrorRecord(exc.code, str(exc), "embedding")]
        return _dataclass_to_json(evaluation_report), []
    if args.command == "prune":
        conn = connect(settings.db_path)
        init_db(conn)
        prune_result = prune_orphans(conn, settings, dry_run=not args.apply)
        return {"result": _dataclass_to_json(prune_result)}, []
    if args.command == "purge":
        conn = connect(settings.db_path)
        init_db(conn)
        if args.type == "assembled_output":
            purge_result = purge_assembled_output(conn, settings, dry_run=not args.apply)
            return {"result": _dataclass_to_json(purge_result)}, []
        raise ValueError(f"Unknown purge type: {args.type}")
    if args.command == "record-deal":
        conn = connect(settings.db_path)
        init_db(conn)
        try:
            deal_id = insert_deal(
                conn,
                args.name,
                client_type=args.client_type,
                deal_stage=args.stage,
                outcome=args.outcome,
                notes=args.notes,
            )
        except DatabaseError as exc:
            return {"deal": None}, [ErrorRecord("RECORD_DEAL_ERROR", str(exc), "db")]
        deal = _fetch_deal(conn, deal_id)
        return {"deal": deal}, []
    if args.command == "record-usage":
        conn = connect(settings.db_path)
        init_db(conn)
        try:
            usage_id = record_slide_usage(
                conn,
                slide_id=args.slide_id,
                deal_id=args.deal_id,
                deck_presentation_id=args.deck_presentation_id,
                position=args.position,
                assemble_run_id=args.assemble_run_id,
                is_original=not args.derived,
            )
            usage_stats = recompute_slide_stats(conn, slide_id=args.slide_id)
        except DatabaseError as exc:
            return {"usage": None, "stats": None}, [ErrorRecord("RECORD_USAGE_ERROR", str(exc), "db")]
        usage = _fetch_usage(conn, usage_id)
        return {"usage": usage, "stats": usage_stats}, []
    if args.command == "recompute-stats":
        conn = connect(settings.db_path)
        init_db(conn)
        try:
            recomputed_stats = recompute_slide_stats(conn, slide_id=args.slide_id)
        except DatabaseError as exc:
            return {"result": None}, [ErrorRecord("RECOMPUTE_STATS_ERROR", str(exc), "db")]
        return {"result": recomputed_stats}, []
    if args.command == "import-metadata":
        conn = connect(settings.db_path)
        init_db(conn)
        try:
            import_result = import_metadata_jsonl(conn, _normalize_path(Path(args.jsonl)))
        except (MetadataJsonlError, OSError, DatabaseError) as exc:
            return {"result": None}, [ErrorRecord("METADATA_IMPORT_ERROR", str(exc), "metadata")]
        return {"result": import_result}, []
    if args.command == "export-metadata":
        conn = connect(settings.db_path)
        init_db(conn)
        try:
            export_result = export_metadata_jsonl(conn, _normalize_path(Path(args.output)))
        except (OSError, DatabaseError) as exc:
            return {"result": None}, [ErrorRecord("METADATA_EXPORT_ERROR", str(exc), "metadata")]
        return {"result": export_result}, []
    if args.command == "annotate":
        from ppt_lib.annotator import annotate_batch

        conn = connect(settings.db_path)
        init_db(conn)
        try:
            batch_result = annotate_batch(
                conn,
                settings,
                batch_size=args.batch,
                provider=args.provider,
                force=args.force,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            return {"result": None}, [ErrorRecord("ANNOTATE_ERROR", str(exc), "annotator")]
        output = {
            "annotated": len(batch_result.results),
            "errors": len(batch_result.errors),
            "dry_run": args.dry_run,
        }
        if args.dry_run and batch_result.results:
            jsonl_lines = []
            for r in batch_result.results:
                jsonl_lines.append(json.dumps(
                    {"slide_id": r.slide_id, "narrative_role": r.narrative_role,
                     "industry": r.industry, "scenario": r.scenario},
                    ensure_ascii=False,
                ))
            output["annotations"] = jsonl_lines
            if hasattr(args, "output") and args.output:
                out_path = _normalize_path(Path(args.output))
                out_path.write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")
                output["output_path"] = str(out_path)
        if batch_result.errors:
            output["error_details"] = [{"slide_id": sid, "error": msg} for sid, msg in batch_result.errors]
        return {"result": output}, []
    if args.command == "select-slides":
        try:
            if args.plan:
                report = select_slides_from_plan(
                    settings,
                    plan_path=_normalize_path(Path(args.plan)),
                    brief=args.brief,
                    max_per_role=args.max_per_role,
                    ranking=args.ranking,
                    threshold=args.threshold,
                )
            elif args.roles:
                roles = [role.strip() for role in args.roles.split(",") if role.strip()]
                report = select_slides(
                    settings,
                    roles=roles,
                    brief=args.brief,
                    industry=args.industry,
                    max_per_role=args.max_per_role,
                    ranking=args.ranking,
                    threshold=args.threshold,
                )
            else:
                return {
                    "report": None
                }, [ErrorRecord("SELECT_SLIDES_ERROR", "Either --roles or --plan is required.", "select-slides")]
            if args.record_usage:
                if args.deal_id is None:
                    return {
                        "report": None
                    }, [ErrorRecord("SELECT_SLIDES_ERROR", "--deal-id is required with --record-usage.", "select-slides")]
                usage_count = record_selection_usage(settings, report, deal_id=args.deal_id)
            else:
                usage_count = 0
        except (SearchError, EmbeddingProviderError, ValueError) as exc:
            return {"report": None}, [ErrorRecord("SELECT_SLIDES_ERROR", str(exc), "select-slides")]
        report_json = _selection_report_to_json(report)
        if usage_count:
            report_json["usage_recorded"] = usage_count
        if args.output:
            out = _normalize_path(Path(args.output))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"report": report_json}, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"report_path": str(out), "total_slides": report.total_slides, "gaps": report.gaps}, []
        return {"report": report_json}, []
    if args.command == "build-manifest":
        try:
            selection_payload = json.loads(_normalize_path(Path(args.selection)).read_text(encoding="utf-8"))
            manifest = _manifest_from_selection_payload(
                selection_payload,
                strategy=args.strategy,
                run_name=args.run_name,
                output_path=args.output_pptx,
                overwrite=args.overwrite,
                schema_version=settings.schema_version,
            )
            if args.output:
                manifest_output_path = _normalize_path(Path(args.output))
                manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                return {"manifest": str(manifest_output_path), "slide_count": _manifest_slide_count(manifest)}, []
            return {"manifest": manifest, "slide_count": _manifest_slide_count(manifest)}, []
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return {"manifest": None}, [ErrorRecord("BUILD_MANIFEST_ERROR", str(exc), "build-manifest")]
    if args.command == "assemble":
        try:
            assemble_manifest = load_assemble_manifest(_normalize_path(Path(args.manifest)))
            assemble_report = run_assemble(assemble_manifest)
        except AssembleManifestError as exc:
            return {"report": None}, [ErrorRecord("ASSEMBLE_MANIFEST_ERROR", str(exc), "assemble")]
        except (AssembleRunError, PptxPackageError) as exc:
            return {"report": None}, [ErrorRecord("ASSEMBLE_RUN_FAILED", str(exc), "assemble")]
        payload = {"report": _dataclass_to_json(assemble_report)}
        if assemble_report.status == "failed":
            message = "; ".join(assemble_report.errors) or "Assemble run failed."
            return payload, [ErrorRecord("ASSEMBLE_RUN_FAILED", message, "assemble")]
        if args.ingest_output:
            try:
                ingest = ingest_assemble_output(
                    settings,
                    assemble_manifest,
                    assemble_report,
                    index_file_func=index_file,
                )
            except AssembleIngestError as exc:
                return payload | {"ingest": None}, [ErrorRecord("ASSEMBLE_INGEST_ERROR", str(exc), "assemble_ingest")]
            payload["ingest"] = _dataclass_to_json(ingest)
            if ingest.status != "completed" or ingest.warnings:
                warnings = ingest.warnings or [f"ingest status: {ingest.status}"]
                return payload, [
                    ErrorRecord("ASSEMBLE_INGEST_PENDING", warning, "assemble_ingest", severity="warning")
                    for warning in warnings
                ]
        return payload, []
    if args.command == "compose":
        try:
            from ppt_lib.composer import compose, compose_confirm

            if args.confirm:
                compose_result = compose_confirm(
                    settings,
                    plan_path=_normalize_path(Path(args.confirm)),
                    overwrite=args.overwrite,
                    deal_id=args.deal_id,
                    verbose=args.verbose,
                )
            elif args.roles or args.plan or args.brief:
                roles_list = [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else None
                plan = _normalize_path(Path(args.plan)) if args.plan else None
                compose_result = compose(
                    settings,
                    roles=roles_list,
                    plan_path=plan,
                    brief=args.brief,
                    industry=args.industry,
                    max_per_role=args.max_per_role,
                    ranking=args.ranking,
                    dry_run=args.dry_run,
                    overwrite=args.overwrite,
                    deal_id=args.deal_id,
                    verbose=args.verbose,
                )
            else:
                return {"result": None}, [ErrorRecord("COMPOSE_ERROR", "Either --roles, --plan, or --confirm is required.", "compose")]
            compose_payload: dict[str, object] = {
                "run_id": compose_result.run_id,
                "run_dir": str(_normalize_path(compose_result.run_dir)),
                "total_slides": compose_result.selection_report.total_slides,
                "gaps": compose_result.gaps,
                "dry_run": compose_result.dry_run,
            }
            if compose_result.assemble_report:
                compose_payload["output_pptx"] = str(_normalize_path(compose_result.assemble_report.output_path))
                compose_payload["assemble_status"] = compose_result.assemble_report.status
            if compose_result.timings.total_ms:
                compose_payload["timings_ms"] = compose_result.timings.total_ms
            return {"result": compose_payload}, []
        except (SearchError, EmbeddingProviderError, ValueError, OSError) as exc:
            return {"result": None}, [ErrorRecord("COMPOSE_ERROR", str(exc), "compose")]
    if args.command == "spike-assemble":
        try:
            manifest_path = _normalize_path(Path(args.manifest))
            assemble_spike_manifest = load_assemble_spike_manifest(manifest_path)
            output_dir = _normalize_path(Path(args.out_dir)) if args.out_dir else manifest_path.parent / "assemble-spike-reports"
            assemble_spike_report = run_assemble_spike(assemble_spike_manifest, output_dir)
        except AssembleSpikeManifestError as exc:
            return {"report": None}, [ErrorRecord("ASSEMBLE_SPIKE_MANIFEST_ERROR", str(exc), "assemble_spike")]
        return {"report": _dataclass_to_json(assemble_spike_report)}, []
    raise ValueError(f"Unknown command: {args.command}")


def _collect_errors(results: list[Any]) -> list[ErrorRecord]:
    errors: list[ErrorRecord] = []
    for result in results:
        errors.extend(getattr(result, "errors", []))
    return errors


def _search_result_to_json(result) -> dict[str, object]:
    return {
        "slide_id": result.slide_id,
        "score": result.score,
        "title": result.title,
        "text_summary": result.text_summary,
        "source_file": str(_normalize_path(result.source_file)),
        "page_number": result.page_number,
        "screenshot_path": str(_normalize_path(result.screenshot_path)) if result.screenshot_path else None,
        "source": result.source,
        "confidence": result.confidence,
        "narrative_role": result.metadata.get("narrative_role") if isinstance(result.metadata, dict) else None,
        "metadata": result.metadata,
        "cluster_id": result.cluster_id,
        "cluster_label": result.cluster_label,
        "score_breakdown": result.score_breakdown,
        "duplicate_count": result.duplicate_count,
        "canonical_slide_id": result.canonical_slide_id,
        "deck_family_id": result.deck_family_id,
        "version_role": result.version_role,
        "is_representative_version": result.is_representative_version,
        "family_duplicate_count": result.family_duplicate_count,
    }


def _selection_report_to_json(report) -> dict[str, object]:
    return {
        "query": report.query,
        "options": report.options,
        "timestamp": report.timestamp,
        "roles": [
            {
                "role": role_selection.role,
                "count": len(role_selection.slides),
                "status": "gap" if role_selection.gap else "matched",
                "gap": role_selection.gap,
                "slides": [_search_result_to_json(slide) for slide in role_selection.slides],
            }
            for role_selection in report.roles
        ],
        "total_slides": report.total_slides,
        "gaps": report.gaps,
    }


def _manifest_from_selection_payload(
    payload: dict[str, object],
    *,
    strategy: str,
    run_name: str,
    output_path: str | None,
    overwrite: bool,
    schema_version: str,
) -> dict[str, object]:
    take_n = _manifest_strategy_take_n(strategy)
    report_payload = payload.get("report", payload)
    if not isinstance(report_payload, dict):
        raise ValueError("selection payload must be an object.")
    roles = report_payload.get("roles")
    if not isinstance(roles, list):
        raise ValueError("selection payload must contain roles.")

    selected: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for role_item in roles:
        if not isinstance(role_item, dict):
            continue
        role = str(role_item.get("role") or "")
        slides = role_item.get("slides")
        if not isinstance(slides, list) or not slides:
            continue
        candidates = slides[:take_n] if take_n else slides
        for slide in candidates:
            if not isinstance(slide, dict):
                continue
            source_file = str(slide["source_file"])
            page_number = int(slide["page_number"])
            key = (source_file, page_number)
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                {
                    "source_file": source_file,
                    "page_number": page_number,
                    "source_slide_id": int(slide["slide_id"]),
                    "reason": str(slide.get("title") or role or "selected"),
                    "risk_policy": "allow_with_warnings",
                }
            )

    gaps = report_payload.get("gaps", [])
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
        "gaps": gaps if isinstance(gaps, list) else [],
    }


def _manifest_strategy_take_n(strategy: str) -> int | None:
    if strategy == "top-n":
        return None
    match = re.fullmatch(r"top(\d+)-per-role", strategy)
    if not match:
        raise ValueError(f"Unsupported strategy: {strategy}. Expected topN-per-role or top-n.")
    take_n = int(match.group(1))
    if take_n < 1:
        raise ValueError(f"Strategy N must be >= 1, got {take_n}")
    return take_n


def _manifest_slide_count(manifest: dict[str, object]) -> int:
    slides = manifest.get("slides", [])
    return len(slides) if isinstance(slides, list) else 0


def _dataclass_to_json(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_default(item) for key, item in asdict(cast(Any, value)).items()}
    return _json_default(value)


def _human_output(command: str, payload: dict[str, object], errors: list[ErrorRecord]) -> str | None:
    text: str | None = None
    if command == "setup":
        text = _human_setup(payload)
    elif command == "doctor":
        text = _human_doctor(payload)
    elif command == "status":
        text = _human_status(payload)
    elif command == "search":
        text = _human_search(payload)
    elif command == "schema":
        text = _human_schema(payload)
    elif command == "init":
        text = _human_init(payload)
    elif command == "sources":
        text = _human_sources(payload)
    elif command == "profile":
        text = _human_profile(payload)
    elif command == "enrich":
        text = _human_enrich(payload)
    elif command == "enrich-decks":
        text = _human_enrich_decks(payload)
    elif command == "assets":
        text = _human_assets(payload)
    elif command == "versions":
        text = _human_versions(payload)
    if errors and text:
        return f"{text}\n\n{_human_errors(command, errors)}"
    if errors:
        return _human_errors(command, errors)
    return text


def _human_errors(command: str, errors: list[ErrorRecord]) -> str:
    lines = [f"{command}: 发现问题"]
    for error in errors:
        lines.append(f"- [{error.code}] {error.message}")
    return "\n".join(lines)


def _run_setup_mode(
    mode: str, settings: Any, config_path: Path, *,
    extra_keys: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[ErrorRecord]]:
    """Execute the existing setup flow with a resolved mode name."""
    changed_keys = write_setup_config(config_path, mode)
    # Apply extra config keys after writing base mode config
    if extra_keys:
        for key, value in extra_keys.items():
            try:
                result = set_config_value(config_path, key, str(value).lower(), home_dir=settings.home_dir)
                if result.changed:
                    changed_keys.append(key)
            except Exception:
                pass  # non-critical; config already usable
    updated_settings = load_settings({"home_dir": settings.home_dir}, config_path=config_path)
    setup_warnings: list[str] = []
    if mode == "lmstudio" and not updated_settings.lmstudio_vision_model:
        detected_model = detect_lmstudio_chat_model(updated_settings.lmstudio_base_url)
        if detected_model:
            config_set_result = set_config_value(config_path, "lmstudio_vision_model", detected_model, home_dir=settings.home_dir)
            if config_set_result.changed:
                changed_keys.append("lmstudio_vision_model")
            updated_settings = load_settings({"home_dir": settings.home_dir}, config_path=config_path)
        else:
            setup_warnings.append("No LM Studio chat/vision model detected; set lmstudio_vision_model explicitly.")
    diagnostics = run_diagnostics(updated_settings).to_json()
    return {
        "mode": mode,
        "config_path": str(_normalize_path(config_path)),
        "changed_keys": changed_keys,
        "effective_config": settings_summary(updated_settings),
        "diagnostics": diagnostics,
        "setup_warnings": setup_warnings,
        "next_commands": [
            "ppt-lib init --manifest <sources-manifest.json> --non-interactive",
            "ppt-lib sources scan --dry-run",
            "ppt-lib sources scan --apply",
            "ppt-lib index --from-sources",
            'ppt-lib search "<query>"',
        ],
    }, []


def _run_quick_setup(settings: Any, config_path: Path, args: argparse.Namespace) -> tuple[dict[str, object], list[ErrorRecord]]:
    """Auto-detect environment, recommend setup, and write config."""
    env = detect_environment(settings)
    if env["provider"] is None:
        return {"mode": None, "config_path": str(_normalize_path(config_path)), "env": env}, [
            ErrorRecord("SETUP_NO_PROVIDER", env["details"], "setup"),
        ]

    recommended_mode, message, overrides = recommend_setup(env)
    if recommended_mode == "needs_config":
        return {"mode": None, "config_path": str(_normalize_path(config_path)), "env": env}, [
            ErrorRecord("SETUP_NEEDS_CONFIG", message, "setup"),
        ]

    return _run_setup_mode(recommended_mode, settings, config_path, extra_keys=overrides)


def _interactive_setup(settings: Any, config_path: Path) -> tuple[dict[str, object], list[ErrorRecord]]:
    """Interactive mode selection menu when no flags are provided."""
    print("\nPPT Library Setup")
    print("=" * 40)
    print("1) Quick Start — auto-detect best config (recommended)")
    print("2) Production — choose specific providers")
    try:
        choice = input("\nSelect [1/2]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return {"mode": None, "status": "cancelled", "config_path": str(_normalize_path(config_path))}, []

    if choice == "1":
        return _quick_setup_interactive(settings, config_path)
    if choice == "2":
        print()
        print("Use --mode to configure specific providers:")
        print("  ppt-lib setup --mode openai")
        print("  ppt-lib setup --mode lmstudio")
        print("  ppt-lib setup --mode text-extraction")
        print()
        return {"mode": None, "status": "use_mode", "config_path": str(_normalize_path(config_path))}, []
    print("Invalid choice.")
    return {"mode": None, "status": "invalid", "config_path": str(_normalize_path(config_path))}, []


def _quick_setup_interactive(settings: Any, config_path: Path) -> tuple[dict[str, object], list[ErrorRecord]]:
    """Auto-detect and confirm with user before writing config."""
    env = detect_environment(settings)
    if env["provider"] is None:
        print(f"\n{env['details']}")
        return {"mode": None, "status": "no_provider", "config_path": str(_normalize_path(config_path))}, []

    recommended_mode, message, overrides = recommend_setup(env)
    if recommended_mode == "needs_config":
        print(f"\nDetected: {env['details']}")
        print(message)
        return {"mode": None, "status": "needs_config", "config_path": str(_normalize_path(config_path))}, []

    if recommended_mode == "lmstudio":
        detected_model = detect_lmstudio_chat_model(settings.lmstudio_base_url)
        if detected_model:
            overrides = {**overrides, "lmstudio_vision_model": detected_model}
    else:
        detected_model = None

    print("\nDetecting environment...")
    print(f"Found: {env['details']}")
    print(f"Settings: {_config_overview_for_mode(recommended_mode, vision_model=detected_model)}")

    try:
        confirm = input("Confirm? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return {"mode": None, "status": "cancelled", "config_path": str(_normalize_path(config_path))}, []

    if confirm and confirm not in ("y", "yes", ""):
        print("Setup cancelled.")
        return {"mode": None, "status": "cancelled", "config_path": str(_normalize_path(config_path))}, []

    payload, errors = _run_setup_mode(recommended_mode, settings, config_path, extra_keys=overrides)
    print(f"\nConfiguration written to {config_path}")
    print("Next: ppt-lib init ... -> sources scan -> index -> search")
    return payload, errors


def _config_overview_for_mode(mode: str, *, vision_model: str | None = None) -> str:
    """Return a short human-readable summary of what a mode configures."""
    if mode == "openai":
        return "embedding=text-embedding-3-small, vision calls during indexing=disabled by default"
    if mode == "lmstudio":
        if vision_model:
            return f"embedding=local (768d), vision model={vision_model}, vision calls during indexing=disabled by default"
        return "embedding=local (768d), vision model=not detected yet, vision calls during indexing=disabled by default"
    return mode


def _human_setup(payload: dict[str, object]) -> str:
    mode = payload.get("mode")
    if mode is None:
        status = payload.get("status", "")
        if status in ("cancelled", "invalid"):
            return "Setup cancelled."
        if status in ("no_provider", "needs_config"):
            return "PPT Library Setup\n- No supported provider detected. Use --mode or --quick."
        if status == "use_mode":
            return "PPT Library Setup\n- Use --mode or --quick to configure."
        return "PPT Library Setup\n- Specify --mode or --quick."
    diagnostics = payload.get("diagnostics")
    checks = diagnostics.get("checks", []) if isinstance(diagnostics, dict) else []
    changed_keys = payload.get("changed_keys", [])
    changed_text = ", ".join(str(item) for item in changed_keys) if isinstance(changed_keys, list) else "-"
    lines = [
        "PPT Library Setup",
        f"- 模式: {mode}",
        f"- 配置文件: {payload.get('config_path', '-')}",
        f"- 已更新: {changed_text}",
    ]
    for check in checks:
        if isinstance(check, dict):
            lines.append(f"- {check.get('name', '-')}: {check.get('status', '-')} - {check.get('message', '')}")
    lines.extend([
        "",
        "下一步:",
        "  ppt-lib init --manifest <sources-manifest.json> --non-interactive",
        "  ppt-lib sources scan --dry-run",
        "  ppt-lib sources scan --apply",
        "  ppt-lib index --from-sources",
        "  ppt-lib search \"<query>\" --top-k 5",
    ])
    return "\n".join(lines)


def _human_doctor(payload: dict[str, object]) -> str:
    summary = payload.get("summary")
    index = payload.get("index")
    diagnostics = payload.get("diagnostics")
    stats = index.get("stats", {}) if isinstance(index, dict) else {}
    checks = diagnostics.get("checks", []) if isinstance(diagnostics, dict) else []
    status = summary.get("status", "-") if isinstance(summary, dict) else "-"
    lines = [
        "PPT Library Doctor",
        f"- 总体状态: {status}",
        f"- PPT: {stats.get('presentation_count', 0) if isinstance(stats, dict) else 0}",
        f"- Slides: {stats.get('slide_count', 0) if isinstance(stats, dict) else 0}",
        f"- Failed jobs: {stats.get('failed_job_count', 0) if isinstance(stats, dict) else 0}",
    ]
    for check in checks:
        if isinstance(check, dict):
            lines.append(f"- {check.get('name', '-')}: {check.get('status', '-')} - {check.get('message', '')}")
    recommendations = payload.get("recommendations", [])
    if isinstance(recommendations, list) and recommendations:
        lines.append("")
        lines.append("建议:")
        lines.extend(f"  - {item}" for item in recommendations)
    return "\n".join(lines)


def _human_status(payload: dict[str, object]) -> str:
    stats = payload.get("stats")
    health = payload.get("health")
    failed_jobs = payload.get("failed_jobs", [])
    orphan_presentations = payload.get("orphan_presentations", [])
    lines = [
        "PPT Library Status",
        f"- PPT: {stats.get('presentation_count', 0) if isinstance(stats, dict) else 0}",
        f"- Slides: {stats.get('slide_count', 0) if isinstance(stats, dict) else 0}",
        f"- Screenshots: {stats.get('screenshot_count', 0) if isinstance(stats, dict) else 0}",
        f"- Failed jobs: {stats.get('failed_job_count', 0) if isinstance(stats, dict) else 0}",
        f"- Orphans: {stats.get('orphan_presentation_count', 0) if isinstance(stats, dict) else 0}",
        f"- Annotated: {health.get('annotated_pct', 0.0) if isinstance(health, dict) else 0.0}%",
        f"- Deals: {health.get('deals_count', 0) if isinstance(health, dict) else 0}",
        f"- Usage records: {health.get('slide_usage_count', 0) if isinstance(health, dict) else 0}",
    ]
    if isinstance(failed_jobs, list) and failed_jobs:
        lines.append("")
        lines.append(f"有 {len(failed_jobs)} 个失败任务，建议运行 doctor 或 prune。")
    if isinstance(orphan_presentations, list) and orphan_presentations:
        lines.append(f"有 {len(orphan_presentations)} 个孤立 PPT 记录。")
    return "\n".join(lines)


def _human_init(payload: dict[str, object]) -> str:
    lines = ["PPT Library 初始化"]
    mode = payload.get("mode", "interactive")
    if mode == "interactive":
        lines.append("状态: 交互式提示")
        instructions = payload.get("instructions", [])
        if isinstance(instructions, list):
            lines.append("")
            lines.extend(str(item) for item in instructions)
        return "\n".join(lines)
    lines.append("状态: 已完成（非交互）")
    manifest = payload.get("manifest", "-")
    profile_path = payload.get("profile_path", "-")
    lines.append(f"- 清单: {manifest}")
    lines.append(f"- Profile: {profile_path}")
    counts = payload.get("counts", {})
    if isinstance(counts, dict):
        lines.append(f"- baseline: {counts.get('baseline', 0)}")
        lines.append(f"- library: {counts.get('library', 0)}")
        lines.append(f"- exclude: {counts.get('exclude', 0)}")
    return "\n".join(lines)


def _human_sources(payload: dict[str, object]) -> str:
    operation = payload.get("operation", "-")
    lines = ["PPT Library Sources"]
    lines.append(f"- 操作: {operation}")
    if operation == "add":
        lines.append(f"- 角色: {payload.get('role', '-')}")
        lines.append(f"- 路径: {payload.get('source', '-')}")
        lines.append(f"- Profile: {payload.get('profile_path', '-')}")
        counts = payload.get("counts", {})
        if isinstance(counts, dict):
            lines.append(f"- baseline: {counts.get('baseline', 0)}")
            lines.append(f"- library: {counts.get('library', 0)}")
            lines.append(f"- exclude: {counts.get('exclude', 0)}")
    elif operation == "scan":
        scan = payload.get("scan", {})
        if isinstance(scan, dict):
            scanned_roots = scan.get("scanned_roots", [])
            lines.append(f"- 扫描源数: {len(scanned_roots) if isinstance(scanned_roots, list) else 0}")
            lines.append(f"- 文件数: {scan.get('file_count', 0)}")
            lines.append(f"- PPTX: {scan.get('pptx_count', 0)}")
            lines.append(f"- 预计页数: {scan.get('estimated_pages', 0)}")
            lines.append(f"- dry-run: {scan.get('dry_run', True)}")
            excluded_directories = scan.get("excluded_directories", [])
            if isinstance(excluded_directories, list) and excluded_directories:
                lines.append("- 已排除目录:")
                lines.extend(f"  - {item}" for item in excluded_directories)
    elif operation == "list":
        role = payload.get("role")
        sources = payload.get("sources", {})
        if isinstance(sources, dict):
            if isinstance(role, str):
                role_sources = sources.get(role, [])
                role_items = role_sources if isinstance(role_sources, list) else []
                lines.append(f"- {role}: {len(role_items)}")
                for source in role_items:
                    lines.append(f"  - {source}")
            else:
                for role_name in ("baseline", "library", "exclude"):
                    items = sources.get(role_name, [])
                    if isinstance(items, list):
                        lines.append(f"- {role_name}: {len(items)}")
                        lines.extend(f"  - {item}" for item in items)
    return "\n".join(lines)


def _human_search(payload: dict[str, object]) -> str:
    results = payload.get("results", [])
    if not isinstance(results, list) or not results:
        return "Search Results\n- 没有命中结果。可尝试降低 threshold，或先运行 status 检查索引库。"
    lines = [f"Search Results ({len(results)})"]
    for idx, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or _human_result_title(item)
        score = item.get("score")
        page = item.get("page_number")
        source = item.get("source_file")
        source_name = Path(str(source)).name if source else "-"
        summary = item.get("text_summary") or ""
        score_text = f"{float(score):.3f}" if isinstance(score, int | float) else "-"
        lines.append(f"{idx}. {title} | score {score_text} | page {page}")
        lines.append(f"   来源: {source_name}")
        if summary:
            lines.append(f"   {summary}")
    html_path = payload.get("html_path")
    if html_path:
        lines.extend(["", f"HTML 审查页: {html_path}"])
    return "\n".join(lines)


def _human_result_title(item: dict[str, object]) -> str:
    source = item.get("source_file")
    page = item.get("page_number")
    if source:
        return f"{Path(str(source)).stem} · P{page}"
    return "(untitled)"


def _human_profile(payload: dict[str, object]) -> str:
    lines = ["PPT Library Profile", f"- 状态: {payload.get('status', '-')}"]
    if payload.get("profile_id") is not None:
        lines.append(f"- Profile ID: {payload.get('profile_id')}")
    if payload.get("baseline_file_count") is not None:
        lines.append(f"- baseline PPT: {payload.get('baseline_file_count')}")
    profile = payload.get("profile")
    if isinstance(profile, dict):
        for label, key in (("行业", "industry"), ("PPT 类型", "deck_types"), ("产品/服务", "products_or_services")):
            values = profile.get(key, [])
            text = ", ".join(str(item) for item in values) if isinstance(values, list) else str(values or "")
            lines.append(f"- {label}: {text or '-'}")
    return "\n".join(lines)


def _human_enrich(payload: dict[str, object]) -> str:
    result = payload.get("result")
    lines = ["PPT Library Enrich"]
    if isinstance(result, dict):
        lines.append(f"- 已处理: {result.get('processed', 0)}")
        lines.append(f"- 剩余: {result.get('remaining', 0)}")
        warnings = result.get("warnings", [])
        if isinstance(warnings, list) and warnings:
            lines.append(f"- 警告: {len(warnings)}")
    return "\n".join(lines)


def _human_enrich_decks(payload: dict[str, object]) -> str:
    result = payload.get("result")
    lines = ["PPT Library Deck Enrich"]
    if isinstance(result, dict):
        lines.append(f"- 已处理 PPT: {result.get('processed', 0)}")
        lines.append(f"- 剩余 PPT: {result.get('remaining', 0)}")
        warnings = result.get("warnings", [])
        if isinstance(warnings, list) and warnings:
            lines.append(f"- 警告: {len(warnings)}")
    return "\n".join(lines)


def _human_versions(payload: dict[str, object]) -> str:
    if "status" in payload:
        status = payload.get("status", {})
        lines = ["PPT Library Versions"]
        if isinstance(status, dict):
            lines.append(f"- Families: {status.get('family_count', 0)}")
            lines.append(f"- Version records: {status.get('presentation_version_count', 0)}")
            lines.append(f"- Representative versions: {status.get('representative_count', 0)}")
            lines.append(f"- Deck insights: {status.get('insight_count', 0)}")
            lines.append(f"- Important slides: {status.get('slide_importance_count', 0)}")
        return "\n".join(lines)
    if "result" in payload:
        result = payload.get("result", {})
        lines = ["PPT Library Versions Recompute"]
        if isinstance(result, dict):
            lines.append(f"- dry-run: {result.get('dry_run', True)}")
            lines.append(f"- Families: {result.get('family_count', 0)}")
            lines.append(f"- PPT: {result.get('presentation_count', 0)}")
            lines.append(f"- Representative versions: {result.get('representative_count', 0)}")
        return "\n".join(lines)
    family = payload.get("family")
    versions = payload.get("versions", [])
    lines = ["PPT Library Version Family"]
    if isinstance(family, dict):
        lines.append(f"- Family ID: {family.get('id', '-')}")
        lines.append(f"- Title: {family.get('title', '-')}")
        lines.append(f"- PPT versions: {family.get('presentation_count', 0)}")
    if isinstance(versions, list):
        for item in versions[:20]:
            if isinstance(item, dict):
                marker = "*" if item.get("is_representative") else "-"
                lines.append(f"{marker} {item.get('filename')} [{item.get('version_role')}]")
    return "\n".join(lines)


def _human_assets(payload: dict[str, object]) -> str:
    result = payload.get("result", payload)
    lines = ["PPT Library Assets"]
    if isinstance(result, dict):
        lines.append(f"- 截图: {result.get('screenshots', 0)}")
        lines.append(f"- slide_assets: {result.get('slide_assets', 0)}")
        lines.append(f"- duplicate_groups: {result.get('duplicate_groups', 0)}")
        lines.append(f"- dry-run: {result.get('dry_run', True)}")
    return "\n".join(lines)


def _human_schema(payload: dict[str, object]) -> str:
    schema = payload.get("schema")
    commands = schema.get("commands", []) if isinstance(schema, dict) else []
    lines = ["PPT Library Commands"]
    if isinstance(commands, list):
        lines.extend(f"- {command}" for command in commands)
    lines.extend(["", "Agent/脚本需要机器输出时使用: --output json"])
    return "\n".join(lines)


def _error_to_json(error: ErrorRecord) -> dict[str, object]:
    return {
        "code": error.code,
        "message": error.message,
        "source_module": error.source_module,
        "severity": error.severity,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_default(item) for key, item in value.items()}
    return value


def _schema(schema_version: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "required_envelope_fields": ["_meta", "_errors"],
        "commands": [
            "init",
            "sources",
            "profile",
            "enrich",
            "enrich-decks",
            "versions",
            "assets",
            "setup",
            "doctor",
            "config",
            "qa sample",
            "index",
            "search",
            "status",
            "discover",
            "watch",
            "vision",
            "models",
            "schema",
            "eval-search",
            "prune",
            "purge",
            "record-deal",
            "record-usage",
            "recompute-stats",
            "import-metadata",
            "export-metadata",
            "annotate",
            "select-slides",
            "build-manifest",
            "compose",
            "assemble",
            "spike-assemble",
        ],
        "envelope": {
            "_meta": {"type": "object", "required": ["schema_version", "command", "generated_at"]},
            "_errors": {"type": "array", "items": "ErrorRecord"},
        },
        "error": {
            "code": "string",
            "message": "string",
            "source_module": "string",
            "severity": "string",
        },
        "search_result": {
            "slide_id": "integer",
            "score": "number",
            "title": "string|null",
            "text_summary": "string",
            "source_file": "absolute-path",
            "page_number": "integer",
            "screenshot_path": "absolute-path|null",
            "source": "vision_model|text_extraction|hybrid",
            "confidence": "number|null",
            "metadata": "object",
            "cluster_id": "integer|null",
            "cluster_label": "string|null",
            "score_breakdown": "object|null",
            "duplicate_count": "integer|null",
            "canonical_slide_id": "integer|null",
            "deck_family_id": "integer|null",
            "version_role": "string|null",
            "is_representative_version": "boolean|null",
            "family_duplicate_count": "integer|null",
        },
    }


def _help_payload(version: str, schema_version: str) -> dict[str, object]:
    return {
        "version": version,
        "summary": "PPT Library local CLI is installed. Choose a command below.",
        "quick_start": [
            "ppt-lib setup --quick",
            "ppt-lib init --manifest <sources-manifest.json> --non-interactive",
            "ppt-lib sources scan --dry-run",
            "ppt-lib sources scan --apply",
            "ppt-lib index --from-sources",
            "ppt-lib search \"<query>\" --top-k 5",
        ],
        "commands": _schema(schema_version)["commands"],
    }


def _plain_help_text(version: str) -> str:
    return "\n".join(
        [
            f"PPT Library CLI {version}",
            "",
            "常用命令：",
            "  ppt-lib setup --quick",
            "  ppt-lib setup --mode lmstudio --non-interactive",
            "  ppt-lib init --manifest <sources-manifest.json> --non-interactive",
            "  ppt-lib sources scan --dry-run",
            "  ppt-lib sources scan --apply",
            "  ppt-lib index --from-sources",
            "  ppt-lib doctor --output json",
            "  ppt-lib status",
            "  ppt-lib search \"<query>\" --top-k 5",
            "",
            "查看完整命令：",
            "  ppt-lib schema --output json",
            "  ppt-lib --help",
        ]
    )


def _sync_source_profile_to_db(settings, profile) -> int:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute("UPDATE library_sources SET is_active = 0")
    written = 0
    for role_name in ("baseline", "library", "exclude"):
        for path in getattr(profile, role_name):
            upsert_library_source(
                conn,
                str(path),
                source_type=role_name,
                metadata_json={"path": str(path), "role": role_name},
                is_active=True,
                commit=False,
            )
            written += 1
    conn.commit()
    return written


def _blocked_source_scan_result(profile, *, roles: list[str] | None) -> dict[str, object]:
    selected_roles = roles or ["baseline", "library"]
    scanned_roots = [
        (role, str(source))
        for role in selected_roles
        for source in getattr(profile, role)
    ]
    return {
        "roles": selected_roles,
        "scanned_roots": scanned_roots,
        "file_count": 0,
        "pptx_count": 0,
        "estimated_pages": 0,
        "excluded_directories": [],
    }


def _active_workspace_profile_ready(settings) -> bool:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    active = get_active_workspace_profile(conn)
    if active is None:
        return False
    row = conn.execute(
        "SELECT metadata_json FROM workspace_profiles WHERE id = ?",
        (active.id,),
    ).fetchone()
    profile_payload = profile_payload_from_row(row[0] if row else None)
    return profile_payload.get("status") == "complete"


def _build_workspace_profile(settings) -> tuple[dict[str, object], list[ErrorRecord]]:
    try:
        profile = load_sources_profile(settings.home_dir) if settings.home_dir else load_sources_profile(Path.home())
    except SourceError as exc:
        return {"status": "failed", "profile": None}, [ErrorRecord(exc.code, str(exc), "sources")]

    baseline_files = collect_pptx_files(profile, roles=["baseline"])
    baseline_texts: list[str] = []
    warnings: list[ErrorRecord] = []
    for file_path in baseline_files:
        try:
            baseline_texts.extend(extract_pptx_text(file_path).values())
        except (OSError, ValueError) as exc:
            warnings.append(
                ErrorRecord(
                    "PROFILE_BASELINE_READ_WARNING",
                    f"{file_path.name}: {exc}",
                    "profile",
                    severity="warning",
                )
            )

    workspace_profile = build_workspace_profile_payload(baseline_texts)
    payload_json = _dataclass_to_json(workspace_profile)
    assert isinstance(payload_json, dict)
    payload_json["baseline_files"] = [str(_normalize_path(path)) for path in baseline_files]

    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    source_id = upsert_library_source(
        conn,
        "__workspace_profile__",
        source_type="profile",
        metadata_json={"baseline_files": payload_json["baseline_files"]},
        is_active=True,
    )
    profile_id = create_workspace_profile(
        conn,
        library_source_id=source_id,
        name="default",
        metadata_json=payload_json,
        is_active=True,
    )
    if not baseline_files:
        warnings.append(
            ErrorRecord(
                "PROFILE_BASELINE_MISSING",
                "未配置 baseline PPT，已生成空画像；后续摘要会采用通用规则。",
                "profile",
                severity="warning",
            )
        )
    profile_status = str(payload_json.get("status") or "empty")
    if warnings and baseline_files:
        profile_status = "partial"
    return {
        "status": profile_status,
        "ready": profile_status == "complete",
        "profile_id": profile_id,
        "baseline_file_count": len(baseline_files),
        "profile": payload_json,
    }, warnings


def _show_workspace_profile(settings) -> tuple[dict[str, object], list[ErrorRecord]]:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    active = get_active_workspace_profile(conn)
    if active is None:
        return {"status": "missing", "profile_id": None, "profile": None}, []
    row = conn.execute(
        "SELECT metadata_json FROM workspace_profiles WHERE id = ?",
        (active.id,),
    ).fetchone()
    return {
        "status": "active",
        "profile_id": active.id,
        "profile": profile_payload_from_row(row[0] if row else None),
    }, []


def _assets_status(settings) -> dict[str, object]:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    counts = _asset_counts(conn)
    counts["dry_run"] = True
    return {"result": counts}


def _asset_counts(conn) -> dict[str, object]:
    counts: dict[str, object] = {
        "screenshots": _table_count(conn, "screenshots"),
        "slide_assets": _table_count(conn, "slide_assets"),
        "duplicate_groups": _table_count(conn, "duplicate_groups"),
        "duplicate_members": _table_count(conn, "slide_duplicate_members"),
    }
    return counts


def _assets_prune(settings, *, dry_run: bool) -> dict[str, object]:
    assert settings.db_path is not None
    assert settings.home_dir is not None
    conn = connect(settings.db_path)
    init_db(conn)
    orphan_rows = conn.execute(
        """
        SELECT sa.id, sa.asset_uri
        FROM slide_assets sa
        LEFT JOIN slides s ON s.id = sa.slide_id
        WHERE s.id IS NULL
        ORDER BY sa.id
        """
    ).fetchall()
    candidate_files: list[str] = []
    deleted_files: list[str] = []
    deletable_ids: list[int] = []
    unsafe_count = 0
    for row_id, asset_uri in orphan_rows:
        path = _safe_asset_path(settings, str(asset_uri))
        if path is None:
            unsafe_count += 1
            continue
        deletable_ids.append(int(row_id))
        candidate_files.append(str(_normalize_path(path)))
        if not dry_run and path.is_file():
            path.unlink()
            deleted_files.append(str(_normalize_path(path)))

    deleted_rows = 0
    if not dry_run and deletable_ids:
        placeholders = ",".join("?" for _ in deletable_ids)
        cursor = conn.execute(f"DELETE FROM slide_assets WHERE id IN ({placeholders})", deletable_ids)
        deleted_rows = int(cursor.rowcount if cursor.rowcount != -1 else 0)
        conn.commit()

    result = _asset_counts(conn)
    result.update(
        {
            "dry_run": dry_run,
            "orphan_slide_assets": len(orphan_rows),
            "unsafe_orphan_slide_assets": unsafe_count,
            "deleted": deleted_rows,
            "candidate_files": candidate_files,
            "deleted_files": deleted_files,
        }
    )
    return {"result": result}


def _safe_asset_path(settings, asset_uri: str) -> Path | None:
    if "://" in asset_uri:
        return None
    assert settings.home_dir is not None
    home_dir = _normalize_path(settings.home_dir)
    raw_path = Path(asset_uri)
    path = _normalize_path(raw_path if raw_path.is_absolute() else home_dir / raw_path)
    safe_roots = [home_dir / "assets", home_dir / "thumbnails"]
    if not any(path == root or root in path.parents for root in safe_roots):
        return None
    return path


def _table_count(conn, table_name: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)).fetchone()
    if not row or int(row[0]) == 0:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _normalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _fetch_deal(conn, deal_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, deal_name, client_type, deal_stage, outcome, created_at, closed_at, notes
        FROM deals
        WHERE id = ?
        """,
        (deal_id,),
    ).fetchone()
    if row is None:
        raise DatabaseError(f"Deal not found: {deal_id}")
    return {
        "id": int(row[0]),
        "deal_name": row[1],
        "client_type": row[2],
        "deal_stage": row[3],
        "outcome": row[4],
        "created_at": row[5],
        "closed_at": row[6],
        "notes": row[7],
    }


def _fetch_usage(conn, usage_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, slide_id, deal_id, assemble_run_id, deck_presentation_id,
               position, is_original, used_at
        FROM slide_usage
        WHERE id = ?
        """,
        (usage_id,),
    ).fetchone()
    if row is None:
        raise DatabaseError(f"Slide usage not found: {usage_id}")
    return {
        "id": int(row[0]),
        "slide_id": int(row[1]),
        "deal_id": int(row[2]),
        "assemble_run_id": row[3],
        "deck_presentation_id": int(row[4]),
        "position": row[5],
        "is_original": bool(row[6]),
        "used_at": row[7],
    }


def _package_version() -> str:
    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "0.1.0"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
