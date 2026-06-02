from __future__ import annotations

import json
from pathlib import Path

from ppt_lib.cli import main
from ppt_lib.indexer import IndexResult


def _read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_cli_init_manifest_loads_profile(tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline"
    library = tmp_path / "library"
    baseline.mkdir()
    library.mkdir()
    manifest_path = tmp_path / "sources-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sources": {
                    "baseline": [str(baseline)],
                    "library": [str(library)],
                    "exclude": [".gstack", ".stversions"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest_path),
        "--non-interactive",
        "--output", "json",
    ])
    payload = _read_json(capsys)

    assert exit_code == 0
    assert payload["command"] == "init"
    assert payload["mode"] == "non_interactive"
    assert payload["counts"]["baseline"] == 1
    assert payload["counts"]["library"] == 1
    assert payload["counts"]["exclude"] == 2
    profile_path = Path(payload["profile_path"])
    assert profile_path.exists()
    saved_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert Path(saved_profile["baseline"][0]) == baseline.resolve()
    assert Path(saved_profile["library"][0]) == library.resolve()


def test_cli_init_interactive_outputs_guidance(tmp_path: Path, capsys) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "init", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "请使用 --manifest" in output
    assert "ppt-lib init --manifest <manifest> --non-interactive" in output


def test_cli_init_non_interactive_missing_manifest_returns_error(tmp_path: Path, capsys) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "init", "--non-interactive", "--output", "json"])
    payload = _read_json(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "INIT_MANIFEST_REQUIRED"


def test_cli_sources_add_list_scan_and_exclusions(tmp_path: Path, capsys) -> None:
    baseline_root = tmp_path / "project" / "baseline"
    keep_root = baseline_root / "keep"
    excluded_stversions = baseline_root / ".stversions"
    excluded_cache = baseline_root / ".cache"
    excluded_tmp = baseline_root / "tmp"
    excluded_gstack = baseline_root / ".gstack"

    keep_root.mkdir(parents=True)
    excluded_stversions.mkdir(parents=True)
    excluded_cache.mkdir(parents=True)
    excluded_tmp.mkdir(parents=True)
    excluded_gstack.mkdir(parents=True)
    (baseline_root / "overview.pptx").write_text("pptx")
    (keep_root / "notes.txt").write_text("keep")
    (keep_root / "chapter.pptx").write_text("pptx")
    (excluded_stversions / "skip.pptx").write_text("skip")
    (excluded_cache / "skip.pptx").write_text("skip")
    (excluded_tmp / "temp.pptx").write_text("skip")
    (excluded_gstack / "skip.pptx").write_text("skip")

    init_manifest = tmp_path / "sources-manifest.json"
    init_manifest.write_text(
        json.dumps(
            {
                "sources": {
                    "baseline": [str(baseline_root)],
                    "library": [str(tmp_path / "library")],
                    "exclude": [".stversions"],
                },
                "notes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "library").mkdir()
    manifest_result = main(
        ["--home-dir", str(tmp_path), "init", "--manifest", str(init_manifest), "--non-interactive", "--output", "json"]
    )
    manifest_payload = _read_json(capsys)
    assert manifest_result == 0
    assert manifest_payload["_errors"] == []
    assert manifest_payload["counts"]["baseline"] == 1

    add_result = main(
        [
            "--home-dir", str(tmp_path),
            "sources", "add", str(baseline_root / "extra"),
            "--role", "baseline",
            "--output", "json",
        ]
    )
    add_payload = _read_json(capsys)
    assert add_result == 0
    assert add_payload["operation"] == "add"
    assert add_payload["counts"]["baseline"] == 2
    assert str(baseline_root / "extra") in add_payload["sources"]["baseline"]

    list_result = main(["--home-dir", str(tmp_path), "sources", "list", "--role", "baseline", "--output", "json"])
    list_payload = _read_json(capsys)
    assert list_result == 0
    assert list_payload["operation"] == "list"
    assert list_payload["role"] == "baseline"
    assert len(list_payload["sources"]["baseline"]) == 2

    scan_result = main(["--home-dir", str(tmp_path), "sources", "scan", "--role", "baseline", "--output", "json"])
    scan_payload = _read_json(capsys)
    assert scan_result == 0
    assert scan_payload["operation"] == "scan"
    scan = scan_payload["scan"]
    assert scan["dry_run"] is True
    assert scan["file_count"] == 3
    assert scan["pptx_count"] == 2
    assert scan["estimated_pages"] == 3
    excluded = set(scan["excluded_directories"])
    assert str(excluded_stversions.resolve()) in excluded
    assert str(excluded_cache.resolve()) in excluded
    assert str(excluded_tmp.resolve()) in excluded
    assert str(excluded_gstack.resolve()) in excluded

    apply_scan_result = main([
        "--home-dir", str(tmp_path),
        "sources",
        "scan",
        "--role", "baseline",
        "--apply",
        "--output", "json",
    ])
    apply_scan_payload = _read_json(capsys)
    assert apply_scan_result == 0
    assert apply_scan_payload["scan"]["dry_run"] is False


def test_cli_sources_scan_dry_run_does_not_authorize_index(tmp_path: Path, capsys) -> None:
    library = tmp_path / "library"
    library.mkdir()
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    init_result = main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ])
    _read_json(capsys)
    scan_result = main(["--home-dir", str(tmp_path), "sources", "scan", "--dry-run", "--output", "json"])
    _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    payload = _read_json(capsys)

    assert init_result == 0
    assert scan_result == 0
    assert not (tmp_path / "sources" / "scan-state.json").exists()
    assert index_result == 1
    assert payload["_errors"][0]["code"] == "LIBRARY_BUILD_SCAN_REQUIRED"


def test_cli_sources_scan_apply_writes_scan_state_and_authorizes_index(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    indexed_paths: list[Path] = []
    def fake_index_file(path: Path, settings, full: bool = False) -> IndexResult:
        indexed_paths.append(path)
        return IndexResult(
            path,
            "indexed",
            1,
            [],
            [],
        )

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index_file)

    init_result = main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ])
    _read_json(capsys)
    scan_result = main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"])
    scan_payload = _read_json(capsys)
    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    index_payload = _read_json(capsys)

    assert init_result == 0
    assert scan_result == 0
    assert scan_payload["scan"]["dry_run"] is False
    assert (tmp_path / "sources" / "scan-state.json").exists()
    assert index_result == 0
    assert index_payload["pptx_count"] == 0
    assert indexed_paths == []


def test_cli_index_from_sources_rejects_stale_scan_state(tmp_path: Path, capsys) -> None:
    library = tmp_path / "library"
    extra = tmp_path / "extra"
    library.mkdir()
    extra.mkdir()
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"]) == 0
    _read_json(capsys)
    assert main([
        "--home-dir", str(tmp_path),
        "sources", "add", str(extra),
        "--role", "library",
        "--output", "json",
    ]) == 0
    _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    payload = _read_json(capsys)

    assert index_result == 1
    assert payload["_errors"][0]["code"] == "LIBRARY_BUILD_SCAN_STALE"


def test_cli_sources_scan_apply_requires_force_for_risky_paths(tmp_path: Path, capsys) -> None:
    risky = Path.home() / "Downloads" / "__ppt_lib_missing_risky_source__"
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(risky)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ]) == 0
    _read_json(capsys)

    blocked = main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"])
    blocked_payload = _read_json(capsys)
    assert not (tmp_path / "sources" / "scan-state.json").exists()

    forced = main([
        "--home-dir", str(tmp_path),
        "sources", "scan",
        "--apply",
        "--force-risky-sources",
        "--output", "json",
    ])
    forced_payload = _read_json(capsys)
    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    index_payload = _read_json(capsys)

    assert blocked == 1
    assert blocked_payload["_errors"][0]["code"] == "SOURCE_RISK_CONFIRMATION_REQUIRED"
    assert forced == 0
    assert forced_payload["scan"]["risk_warnings"]
    assert (tmp_path / "sources" / "scan-state.json").exists()
    assert index_result == 0
    assert index_payload["pptx_count"] == 0


def test_cli_sources_scan_apply_blocks_risky_paths_before_recursive_scan(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    risky = Path.home() / "Downloads" / "__ppt_lib_missing_risky_source__"
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(risky)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ]) == 0
    _read_json(capsys)

    def fail_scan(*args, **kwargs):
        raise AssertionError("scan_sources should not run for blocked risky apply")

    monkeypatch.setattr("ppt_lib.cli.scan_sources", fail_scan)
    exit_code = main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"])
    payload = _read_json(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "SOURCE_RISK_CONFIRMATION_REQUIRED"
    assert payload["scan"]["pptx_count"] == 0
    assert not (tmp_path / "sources" / "scan-state.json").exists()


def test_cli_index_with_ai_summary_requires_ready_profile(tmp_path: Path, capsys) -> None:
    library = tmp_path / "library"
    library.mkdir()
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "profile", "build", "--output", "json"]) == 0
    profile_payload = _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources", "--with-ai-summary"])
    payload = _read_json(capsys)

    assert profile_payload["ready"] is False
    assert index_result == 1
    assert payload["_errors"][0]["code"] == "LIBRARY_PROFILE_NOT_READY"


def test_cli_single_file_index_does_not_require_sources_scan(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    pptx_path = tmp_path / "single.pptx"
    pptx_path.write_text("pptx", encoding="utf-8")
    indexed_paths: list[Path] = []
    def fake_index_file(path: Path, settings, full: bool = False) -> IndexResult:
        indexed_paths.append(path)
        return IndexResult(
            path,
            "indexed",
            1,
            [],
            [],
        )

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index_file)

    exit_code = main(["--home-dir", str(tmp_path), "index", str(pptx_path)])
    payload = _read_json(capsys)

    assert exit_code == 0
    assert payload["result"]["status"] == "indexed"
    assert indexed_paths == [pptx_path.resolve()]
    assert not (tmp_path / "sources" / "scan-state.json").exists()
