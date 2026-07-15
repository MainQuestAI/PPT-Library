from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppt_lib.cli import main
from ppt_lib.indexer import ErrorRecord, IndexResult
from ppt_lib.sources import (
    SourceError,
    SourceProfile,
    add_source,
    classify_source_path,
    collect_pptx_files,
    load_index_progress_state,
    load_scan_state,
    load_sources_manifest,
    load_sources_profile,
    normalize_role,
    parse_sources_manifest_payload,
    risky_source_details,
    scan_sources,
    scan_state_path_for_home,
    source_profile_hash,
    validate_scan_state_for_index,
)


def _read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_source_validation_rejects_invalid_roles_and_manifest_shapes(tmp_path: Path) -> None:
    with pytest.raises(SourceError) as role_error:
        normalize_role("unknown")
    assert role_error.value.code == "SOURCE_ROLE_INVALID"

    invalid_payloads = [
        None,
        {"sources": []},
        {},
        {"library": "not-a-list"},
        {"library": [{"label": "missing-path"}]},
        {"library": [123]},
    ]
    for payload in invalid_payloads:
        with pytest.raises(SourceError) as manifest_error:
            parse_sources_manifest_payload(payload)
        assert manifest_error.value.code == "SOURCE_MANIFEST_INVALID"

    missing_manifest = tmp_path / "missing.json"
    with pytest.raises(SourceError) as missing_error:
        load_sources_manifest(missing_manifest)
    assert missing_error.value.code == "SOURCE_MANIFEST_READ_FAILED"

    invalid_manifest = tmp_path / "invalid.json"
    invalid_manifest.write_text("{", encoding="utf-8")
    with pytest.raises(SourceError) as invalid_error:
        load_sources_manifest(invalid_manifest)
    assert invalid_error.value.code == "SOURCE_MANIFEST_INVALID"


def test_source_manifest_list_normalizes_blanks_dicts_and_duplicates(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"

    profile = parse_sources_manifest_payload([" ", {"path": str(deck)}, str(deck)])

    assert profile.baseline == [str(deck.resolve())]
    assert profile.library == []


def test_sources_profile_and_state_loaders_reject_invalid_json_shapes(tmp_path: Path) -> None:
    profile_path = tmp_path / "sources" / "profile"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("{", encoding="utf-8")
    with pytest.raises(SourceError) as profile_json_error:
        load_sources_profile(tmp_path)
    assert profile_json_error.value.code == "SOURCE_PROFILE_INVALID"

    profile_path.write_text("[]", encoding="utf-8")
    with pytest.raises(SourceError) as profile_shape_error:
        load_sources_profile(tmp_path)
    assert profile_shape_error.value.code == "SOURCE_PROFILE_INVALID"

    profile_path.write_text(json.dumps({"library": [123]}), encoding="utf-8")
    with pytest.raises(SourceError) as profile_item_error:
        load_sources_profile(tmp_path)
    assert profile_item_error.value.code == "SOURCE_PROFILE_INVALID"

    index_state = tmp_path / "sources" / "index-progress.json"
    index_state.write_text("{", encoding="utf-8")
    with pytest.raises(SourceError) as index_json_error:
        load_index_progress_state(tmp_path)
    assert index_json_error.value.code == "SOURCE_INDEX_PROGRESS_INVALID"

    index_state.write_text("[]", encoding="utf-8")
    with pytest.raises(SourceError) as index_shape_error:
        load_index_progress_state(tmp_path)
    assert index_shape_error.value.code == "SOURCE_INDEX_PROGRESS_INVALID"

    scan_state = scan_state_path_for_home(tmp_path)
    scan_state.write_text("{", encoding="utf-8")
    with pytest.raises(SourceError) as scan_json_error:
        load_scan_state(tmp_path)
    assert scan_json_error.value.code == "SOURCE_SCAN_STATE_INVALID"

    scan_state.write_text("[]", encoding="utf-8")
    with pytest.raises(SourceError) as scan_shape_error:
        load_scan_state(tmp_path)
    assert scan_shape_error.value.code == "SOURCE_SCAN_STATE_INVALID"


def test_scan_state_validation_covers_authorization_failures(tmp_path: Path) -> None:
    profile = SourceProfile(baseline=[], library=[str(tmp_path / "library")], exclude=[])
    state_path = scan_state_path_for_home(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    valid_state = {
        "dry_run": False,
        "roles": ["library"],
        "source_profile_hash": source_profile_hash(profile),
        "risk_warnings": [],
        "force_risky_sources": False,
    }
    cases = [
        ({**valid_state, "dry_run": True}, "LIBRARY_BUILD_SCAN_REQUIRED"),
        ({**valid_state, "roles": "library"}, "SOURCE_SCAN_STATE_INVALID"),
        ({**valid_state, "roles": ["baseline"]}, "LIBRARY_BUILD_SCAN_REQUIRED"),
        ({**valid_state, "source_profile_hash": "stale"}, "LIBRARY_BUILD_SCAN_STALE"),
        ({**valid_state, "risk_warnings": ["blocked"]}, "LIBRARY_BUILD_RISK_NOT_CONFIRMED"),
    ]
    for state, expected_code in cases:
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(SourceError) as exc_info:
            validate_scan_state_for_index(tmp_path, profile)
        assert exc_info.value.code == expected_code

    forced_state = {**valid_state, "risk_warnings": ["blocked"], "force_risky_sources": True}
    state_path.write_text(json.dumps(forced_state), encoding="utf-8")
    assert validate_scan_state_for_index(tmp_path, profile) == forced_state


def test_source_classification_and_details_cover_safe_boundaries(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"deck")
    profile = SourceProfile(
        baseline=[],
        library=[str(home), str(tmp_path / "candidate")],
        exclude=[str(tmp_path / "ignored")],
    )

    assert classify_source_path(home, user_home=home).category == "blocked"
    assert classify_source_path(home / "Library" / "Caches" / "deck.pptx", user_home=home).category == "blocked"
    assert classify_source_path(deck, user_home=home).reason == "pptx file"
    assert classify_source_path(tmp_path / "candidate", user_home=home).category == "candidate"
    assert classify_source_path(tmp_path / "ignored", role="exclude", user_home=home).category == "trusted"
    details = risky_source_details(profile, roles=["library", "exclude"], user_home=home)
    assert [item.category for item in details] == ["blocked"]


def test_add_source_deduplicates_normalized_paths(tmp_path: Path) -> None:
    profile = SourceProfile.empty()

    once = add_source(profile, "library", str(tmp_path / "library"))
    twice = add_source(once, "library", str(tmp_path / "library"))

    assert once.library == twice.library


def test_source_scan_skips_symlinks_that_escape_the_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "library"
    outside = tmp_path / "outside"
    source_root.mkdir()
    outside.mkdir()
    safe_deck = source_root / "safe.pptx"
    escaped_deck = outside / "escaped.pptx"
    safe_deck.write_bytes(b"safe")
    escaped_deck.write_bytes(b"escaped")
    escaped_dir_link = source_root / "external-library"
    escaped_file_link = source_root / "external-deck.pptx"
    escaped_dir_link.symlink_to(outside, target_is_directory=True)
    escaped_file_link.symlink_to(escaped_deck)
    profile = SourceProfile(baseline=[], library=[str(source_root)], exclude=[])

    files = collect_pptx_files(profile, roles=["library"])
    scan = scan_sources(profile, roles=["library"])

    assert files == [safe_deck.resolve()]
    assert scan["file_count"] == 1
    assert scan["pptx_count"] == 1
    assert str(escaped_dir_link) in scan["excluded_directories"]
    assert str(escaped_file_link) in scan["excluded_directories"]


def test_source_scan_skips_symlink_cycles(tmp_path: Path) -> None:
    source_root = tmp_path / "library"
    source_root.mkdir()
    deck = source_root / "deck.pptx"
    deck.write_bytes(b"deck")
    loop = source_root / "loop"
    loop.symlink_to(source_root, target_is_directory=True)
    profile = SourceProfile(baseline=[], library=[str(source_root)], exclude=[])

    files = collect_pptx_files(profile, roles=["library"])
    scan = scan_sources(profile, roles=["library"])

    assert files == [deck.resolve()]
    assert str(loop) in scan["excluded_directories"]


def test_source_scan_handles_direct_files_missing_roots_and_explicit_excludes(tmp_path: Path) -> None:
    source_root = tmp_path / "library"
    source_root.mkdir()
    included = source_root / "included.pptx"
    included.write_bytes(b"deck")
    (source_root / "notes.txt").write_text("notes", encoding="utf-8")
    (source_root / "~$lock.pptx").write_bytes(b"lock")
    hidden_tmp = source_root / ".tmp-render"
    hidden_tmp.mkdir()
    (hidden_tmp / "hidden.pptx").write_bytes(b"hidden")
    excluded = source_root / "excluded"
    excluded.mkdir()
    (excluded / "excluded.pptx").write_bytes(b"excluded")
    direct = tmp_path / "direct.pptx"
    direct.write_bytes(b"direct")
    direct_lock = tmp_path / ".~direct.pptx"
    direct_lock.write_bytes(b"lock")
    missing = tmp_path / "missing"
    source_link = tmp_path / "library-link"
    source_link.symlink_to(source_root, target_is_directory=True)
    profile = SourceProfile(
        baseline=[],
        library=[str(source_root), str(direct), str(direct_lock), str(missing), str(source_link)],
        exclude=[str(excluded)],
    )

    files = collect_pptx_files(profile, roles=["library"])
    scan = scan_sources(profile, roles=["library"])

    assert files == sorted([included.resolve(), direct.resolve()])
    assert scan["file_count"] == 3
    assert str(excluded.resolve()) in scan["excluded_directories"]
    assert str(hidden_tmp.resolve()) in scan["excluded_directories"]
    assert str(missing.resolve()) in scan["excluded_directories"]
    assert str(source_link) in scan["excluded_directories"]


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


def test_cli_sources_manifest_writes_manifest_and_summary(tmp_path: Path, capsys) -> None:
    library = tmp_path / "library"
    baseline = tmp_path / "baseline.pptx"
    exclude = tmp_path / "library" / "exports"
    library.mkdir()
    exclude.mkdir()
    baseline.write_text("pptx", encoding="utf-8")
    manifest_output = tmp_path / "home" / "sources" / "sources-manifest.json"
    summary_output = tmp_path / "home" / "sources" / "onboarding-summary.md"

    exit_code = main([
        "--home-dir", str(tmp_path / "home"),
        "sources", "manifest",
        "--library", str(library),
        "--library", str(library),
        "--baseline", str(baseline),
        "--exclude", str(exclude),
        "--manifest-output", str(manifest_output),
        "--summary-output", str(summary_output),
        "--output", "json",
    ])
    payload = _read_json(capsys)
    manifest = json.loads(manifest_output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["operation"] == "manifest"
    assert payload["counts"] == {"baseline": 1, "library": 1, "exclude": 1}
    assert payload["rejected_sources"] == []
    assert payload["risk_warnings"] == []
    assert manifest["sources"]["library"] == [str(library.resolve())]
    assert manifest["sources"]["baseline"] == [str(baseline.resolve())]
    assert summary_output.exists()
    assert "ppt-lib init --manifest" in payload["next_commands"][0]


def test_cli_sources_manifest_rejects_missing_and_risky_paths(tmp_path: Path, capsys) -> None:
    safe_library = tmp_path / "library"
    safe_library.mkdir()
    missing = tmp_path / "missing"
    risky = Path.home() / "Downloads" / "__ppt_lib_manifest_risky__"
    manifest_output = tmp_path / "home" / "sources" / "sources-manifest.json"

    exit_code = main([
        "--home-dir", str(tmp_path / "home"),
        "sources", "manifest",
        "--library", str(safe_library),
        "--library", str(missing),
        "--baseline", str(risky),
        "--manifest-output", str(manifest_output),
        "--output", "json",
    ])
    payload = _read_json(capsys)
    manifest = json.loads(manifest_output.read_text(encoding="utf-8"))

    assert exit_code == 0
    rejected_categories = {item["category"] for item in payload["rejected_sources"]}
    assert rejected_categories == {"missing", "blocked"}
    assert payload["risk_warnings"]
    assert manifest["sources"]["library"] == [str(safe_library.resolve())]
    assert manifest["sources"]["baseline"] == []


def test_source_path_classifier_covers_noisy_and_blocked_paths(tmp_path: Path) -> None:
    cases = [
        (Path.home() / "Downloads" / "deck.pptx", "blocked"),
        (Path.home() / ".Trash" / "deck.pptx", "blocked"),
        (tmp_path / "site-packages" / "template.pptx", "blocked"),
        (tmp_path / "node_modules" / "template.pptx", "blocked"),
        (tmp_path / "微信" / "cache.pptx", "blocked"),
        (tmp_path / "WPS Cloud Files" / "deck.pptx", "blocked"),
        (tmp_path / "project" / "outputs", "noisy"),
        (tmp_path / "project" / "exports", "noisy"),
        (tmp_path / "project" / "artifacts", "noisy"),
    ]

    for path, expected in cases:
        assert classify_source_path(path, role="library").category == expected


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


def test_cli_index_from_sources_writes_progress_and_status_reports_it(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    pptx_path = library / "deck.pptx"
    pptx_path.write_text("pptx", encoding="utf-8")
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False), encoding="utf-8")

    def fake_index_file(path: Path, settings, full: bool = False) -> IndexResult:
        return IndexResult(path, "indexed", 1, [], [])

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index_file)
    assert main(["--home-dir", str(tmp_path), "init", "--manifest", str(manifest), "--non-interactive", "--output", "json"]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"]) == 0
    _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    index_payload = _read_json(capsys)
    status_result = main(["--home-dir", str(tmp_path), "status", "--output", "json"])
    status_payload = _read_json(capsys)

    progress_path = tmp_path / "sources" / "index-progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert index_result == 0
    assert index_payload["index_progress_path"] == str(progress_path.resolve())
    assert progress["status"] == "completed"
    assert progress["total_pptx"] == 1
    assert progress["processed_pptx"] == 1
    assert progress["failed_pptx"] == 0
    assert status_result == 0
    assert status_payload["sources_health"]["index_progress"]["status"] == "completed"


def test_cli_index_from_sources_supports_parallel_file_workers(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    first = library / "first.pptx"
    second = library / "second.pptx"
    first.write_text("pptx", encoding="utf-8")
    second.write_text("pptx", encoding="utf-8")
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False), encoding="utf-8")
    indexed_paths: list[Path] = []

    def fake_index_file(path: Path, settings, full: bool = False) -> IndexResult:
        indexed_paths.append(path)
        return IndexResult(path, "indexed", 1, [], [])

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index_file)
    assert main(["--home-dir", str(tmp_path), "init", "--manifest", str(manifest), "--non-interactive", "--output", "json"]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"]) == 0
    _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources", "--file-workers", "2"])
    payload = _read_json(capsys)
    progress = json.loads((tmp_path / "sources" / "index-progress.json").read_text(encoding="utf-8"))

    assert index_result == 0
    assert payload["pptx_count"] == 2
    assert sorted(path.name for path in indexed_paths) == ["first.pptx", "second.pptx"]
    assert progress["status"] == "completed"
    assert progress["processed_pptx"] == 2
    assert progress["file_workers"] == 2


def test_cli_index_from_sources_progress_records_failed_count(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    pptx_path = library / "deck.pptx"
    pptx_path.write_text("pptx", encoding="utf-8")
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(json.dumps({"sources": {"library": [str(library)]}}, ensure_ascii=False), encoding="utf-8")

    def fake_index_file(path: Path, settings, full: bool = False) -> IndexResult:
        return IndexResult(path, "failed", 0, [], [ErrorRecord("FAKE_INDEX_FAILED", "bad", "indexer")])

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index_file)
    assert main(["--home-dir", str(tmp_path), "init", "--manifest", str(manifest), "--non-interactive", "--output", "json"]) == 0
    _read_json(capsys)
    assert main(["--home-dir", str(tmp_path), "sources", "scan", "--apply", "--output", "json"]) == 0
    _read_json(capsys)

    index_result = main(["--home-dir", str(tmp_path), "index", "--from-sources"])
    payload = _read_json(capsys)
    progress = json.loads((tmp_path / "sources" / "index-progress.json").read_text(encoding="utf-8"))

    assert index_result == 1
    assert payload["_errors"][0]["code"] == "FAKE_INDEX_FAILED"
    assert progress["status"] == "completed"
    assert progress["processed_pptx"] == 1
    assert progress["failed_pptx"] == 1


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
