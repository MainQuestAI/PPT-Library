from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppt_lib.config import load_settings
from ppt_lib.discovery import DiscoveryError
from ppt_lib.sample_qa import (
    QA_HOME_SENTINEL,
    QA_HOME_SENTINEL_CONTENT,
    SAMPLE_MANIFEST_ENV,
    SEARCH_QUERIES,
    SampleQaManifestError,
    SampleQaSafetyError,
    SampleSpec,
    _evaluate_search_quality,
    _get_json,
    _model_ids,
    _overall_status,
    _reset_generated_home,
    _resolve_manifest_path,
    _run_searches,
    _sample_status_reason,
    build_local_sample_settings,
    load_samples,
    run_discovery_checks,
    run_local_sample_qa,
    select_samples,
    write_manifest,
    write_markdown_report,
)
from ppt_lib.searcher import SearchError


def test_search_queries_cover_acceptance_terms() -> None:
    assert SEARCH_QUERIES == ["AI 智能体", "数据治理", "CMS 部署", "SCRM", "微信小店", "营销自动化"]


def test_load_samples_from_manifest(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "label": "deck",
                    "phase": "baseline",
                    "path": str(deck),
                    "expected_complexity": "small",
                }
            ]
        ),
        encoding="utf-8",
    )

    samples = load_samples(manifest)

    assert samples == [SampleSpec("deck", "baseline", deck.resolve(strict=False), "small")]


def test_load_samples_rejects_invalid_manifest_shapes(tmp_path: Path) -> None:
    assert load_samples(tmp_path / "missing.json") == []
    invalid_payloads = [
        "{",
        "{}",
        "[1]",
        '[{"phase": "unknown", "path": "/tmp/deck.pptx"}]',
        '[{"phase": "baseline", "path": ""}]',
    ]
    for index, payload in enumerate(invalid_payloads):
        manifest = tmp_path / f"invalid-{index}.json"
        manifest.write_text(payload, encoding="utf-8")
        with pytest.raises(SampleQaManifestError):
            load_samples(manifest)


def test_select_samples_by_phase_and_limit() -> None:
    samples = [
        SampleSpec("one", "baseline", Path("/tmp/one.pptx"), "small"),
        SampleSpec("two", "baseline", Path("/tmp/two.pptx"), "medium"),
        SampleSpec("three", "complex", Path("/tmp/three.pptx"), "large"),
    ]

    selected = select_samples("baseline", max_files=1, samples=samples)

    assert selected == samples[:1]


def test_select_samples_all_includes_complex() -> None:
    samples = [
        SampleSpec("one", "baseline", Path("/tmp/one.pptx"), "small"),
        SampleSpec("two", "complex", Path("/tmp/two.pptx"), "large"),
    ]

    selected = select_samples("all", max_files=None, samples=samples)

    assert selected == samples


def test_select_samples_complex_phase() -> None:
    baseline = SampleSpec("one", "baseline", Path("/tmp/one.pptx"), "small")
    complex_sample = SampleSpec("two", "complex", Path("/tmp/two.pptx"), "large")

    assert select_samples("complex", samples=[baseline, complex_sample]) == [complex_sample]


def test_build_local_sample_settings_defaults_to_lmstudio(tmp_path: Path) -> None:
    settings = build_local_sample_settings(tmp_path)

    assert settings.home_dir == tmp_path
    assert settings.embedding_provider == "lmstudio"
    assert settings.lmstudio_embedding_model == "text-embedding-nomic-embed-text-v1.5"
    assert settings.embedding_dimensions == 768
    assert settings.vision_provider == "lmstudio"
    assert settings.lmstudio_vision_model == "google/gemma-4-26b-a4b"
    assert settings.vision_max_slides_per_file == 3


def test_sample_manifest_skips_missing_without_copying(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pptx"
    manifest = write_manifest([SampleSpec("missing", "baseline", missing, "missing sample")], tmp_path)

    data = json.loads(manifest.read_text())

    assert data[0]["exists"] is False
    assert data[0]["file_size"] is None
    assert not missing.exists()


def test_fresh_run_resets_generated_home_state(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / QA_HOME_SENTINEL).write_text(QA_HOME_SENTINEL_CONTENT, encoding="utf-8")
    stale_db = home / "index.db"
    stale_db.write_text("stale", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]", encoding="utf-8")

    monkeypatch.setattr("ppt_lib.sample_qa.run_preflight", lambda settings: [{"name": "embedding_smoke", "status": "ok"}])
    monkeypatch.setattr("ppt_lib.sample_qa.run_discovery_checks", lambda samples, settings: [])
    monkeypatch.setattr("ppt_lib.sample_qa._status_payload", lambda settings: {"failed_job_count": 0})
    monkeypatch.setattr(
        "ppt_lib.sample_qa._search_index_payload",
        lambda settings: {"searchable_embeddings": 0, "skipped_embeddings": 0, "dimension_counts": {}},
    )
    monkeypatch.setattr("ppt_lib.sample_qa._run_searches", lambda settings, enabled: [])

    report = run_local_sample_qa(home_dir=home, manifest_path=manifest, report_dir=tmp_path / "reports", fresh=True)

    assert report["fresh"] is True
    assert not stale_db.exists()


def test_fresh_reset_refuses_nonempty_home_without_sentinel(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    stale_db = home / "index.db"
    stale_db.write_text("must survive", encoding="utf-8")

    with pytest.raises(SampleQaSafetyError) as exc_info:
        _reset_generated_home(home)

    assert exc_info.value.code == "QA_FRESH_HOME_NOT_OWNED"
    assert stale_db.read_text(encoding="utf-8") == "must survive"


def test_fresh_reset_only_deletes_generated_allowlist(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / QA_HOME_SENTINEL).write_text(QA_HOME_SENTINEL_CONTENT, encoding="utf-8")
    (home / "index.db").write_text("stale", encoding="utf-8")
    screenshots = home / "screenshots"
    screenshots.mkdir()
    (screenshots / "slide.png").write_bytes(b"png")
    keep = home / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    _reset_generated_home(home)

    assert not (home / "index.db").exists()
    assert not screenshots.exists()
    assert keep.read_text(encoding="utf-8") == "keep"
    assert (home / QA_HOME_SENTINEL).read_text(encoding="utf-8") == QA_HOME_SENTINEL_CONTENT


def test_fresh_reset_unlinks_generated_symlink_without_deleting_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    external = tmp_path / "external-screenshots"
    home.mkdir()
    external.mkdir()
    external_file = external / "keep.png"
    external_file.write_bytes(b"keep")
    (home / QA_HOME_SENTINEL).write_text(QA_HOME_SENTINEL_CONTENT, encoding="utf-8")
    screenshots_link = home / "screenshots"
    screenshots_link.symlink_to(external, target_is_directory=True)

    _reset_generated_home(home)

    assert not screenshots_link.exists()
    assert external_file.read_bytes() == b"keep"


def test_fresh_reset_rejects_symlinked_sentinel(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    external_marker = tmp_path / "external-marker"
    external_marker.write_text(QA_HOME_SENTINEL_CONTENT, encoding="utf-8")
    (home / QA_HOME_SENTINEL).symlink_to(external_marker)
    stale_db = home / "index.db"
    stale_db.write_text("must survive", encoding="utf-8")

    with pytest.raises(SampleQaSafetyError):
        _reset_generated_home(home)

    assert stale_db.exists()


def test_fresh_reset_initializes_new_home_with_sentinel(tmp_path: Path) -> None:
    home = tmp_path / "new-home"

    _reset_generated_home(home)

    assert (home / QA_HOME_SENTINEL).read_text(encoding="utf-8") == QA_HOME_SENTINEL_CONTENT


def test_fresh_reset_rejects_root_symlink_file_primary_home_and_invalid_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SampleQaSafetyError):
        _reset_generated_home(root_link)

    file_home = tmp_path / "file-home"
    file_home.write_text("file", encoding="utf-8")
    with pytest.raises(SampleQaSafetyError):
        _reset_generated_home(file_home)

    invalid_home = tmp_path / "invalid-home"
    invalid_home.mkdir()
    (invalid_home / QA_HOME_SENTINEL).write_text("wrong-owner\n", encoding="utf-8")
    with pytest.raises(SampleQaSafetyError):
        _reset_generated_home(invalid_home)

    fake_user_home = tmp_path / "user"
    primary_home = fake_user_home / ".ppt-library"
    primary_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_user_home))
    with pytest.raises(SampleQaSafetyError):
        _reset_generated_home(primary_home)


def test_discovery_checks_find_sample_and_ignore_locks(tmp_path: Path) -> None:
    root = tmp_path / "source"
    deck = root / "deck.pptx"
    deck.parent.mkdir(parents=True)
    deck.write_bytes(b"pptx")
    (root / "~$deck.pptx").write_bytes(b"lock")
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")

    rows = run_discovery_checks([SampleSpec("deck", "baseline", deck, "small")], settings)

    assert rows[0]["status"] == "ok"
    assert rows[0]["discovered_count"] == 1


def test_discovery_checks_report_missing_warning_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home"}, config_path=tmp_path / "home" / "config.yml")
    missing = SampleSpec("missing", "baseline", tmp_path / "missing.pptx", "small")
    existing_path = tmp_path / "existing.pptx"
    existing_path.write_bytes(b"deck")
    existing = SampleSpec("existing", "baseline", existing_path, "small")

    monkeypatch.setattr("ppt_lib.sample_qa.scan_presentations", lambda root, settings: [])
    rows = run_discovery_checks([missing, existing], settings)
    assert [row["status"] for row in rows] == ["missing", "warning"]

    def fail_discovery(root, settings):
        raise DiscoveryError("blocked", code="DISCOVERY_BLOCKED")

    monkeypatch.setattr("ppt_lib.sample_qa.scan_presentations", fail_discovery)
    failed = run_discovery_checks([existing], settings)
    assert failed[0]["status"] == "failed"
    assert "DISCOVERY_BLOCKED" in failed[0]["error"]


def test_searches_warn_when_query_returns_no_results(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")

    rows = _run_searches(settings, enabled=True)

    assert rows
    assert {row["status"] for row in rows} == {"warning"}
    assert all(row["error"] == "no search results" for row in rows)


def test_searches_cover_disabled_and_provider_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")

    disabled = _run_searches(settings, enabled=False)
    assert {row["status"] for row in disabled} == {"skipped"}

    def fail_search(*args, **kwargs):
        raise SearchError("failed", code="SEARCH_FAILED")

    monkeypatch.setattr("ppt_lib.sample_qa.search", fail_search)
    failed = _run_searches(settings, enabled=True)
    assert {row["status"] for row in failed} == {"failed"}


def test_search_quality_records_expected_and_off_target_results() -> None:
    matched = _evaluate_search_quality(
        "SCRM",
        [{"source_file": "/materials/示例卤味品牌SCRM项目方案建议书.pptx", "title": None}],
    )
    off_target = _evaluate_search_quality(
        "SCRM",
        [{"source_file": "/materials/cloud-native-best-practice.pptx", "title": "AI native"}],
    )

    assert matched["quality_status"] == "matched"
    assert matched["matched_expected_source"] is True
    assert off_target["quality_status"] == "off_target"
    assert off_target["matched_expected_source"] is False

    not_evaluated = _evaluate_search_quality("untracked-query", [{"title": "anything"}])
    assert not_evaluated["quality_status"] == "not_evaluated"


def test_sample_status_reasons_cover_known_and_unknown_values() -> None:
    assert _sample_status_reason("indexed") == "indexed in this run"
    assert _sample_status_reason("skipped") == "unchanged from existing index"
    assert _sample_status_reason("failed") == "indexing failed"
    assert _sample_status_reason("custom") == "custom"


def test_overall_status_warns_for_search_warning_and_skipped_embeddings() -> None:
    report = {
        "preflight": [{"name": "embedding_smoke", "status": "ok"}],
        "samples": [{"status": "indexed", "warnings": []}],
        "discovery": [{"status": "ok"}],
        "searches": [{"status": "warning"}],
        "status": {"failed_job_count": 0},
        "search_index": {"skipped_embeddings": 0},
    }

    assert _overall_status(report) == "warning"

    report["searches"] = [{"status": "ok"}]
    report["search_index"] = {"skipped_embeddings": 1}
    assert _overall_status(report) == "warning"


def test_overall_status_warns_for_preflight_warning() -> None:
    report = {
        "preflight": [{"name": "lmstudio_models", "status": "warning"}],
        "samples": [{"status": "indexed", "warnings": []}],
        "discovery": [{"status": "ok"}],
        "searches": [{"status": "ok"}],
        "status": {"failed_job_count": 0},
        "search_index": {"skipped_embeddings": 0},
    }

    assert _overall_status(report) == "warning"


def test_overall_status_fails_when_failed_jobs_exist() -> None:
    report = {
        "preflight": [{"name": "embedding_smoke", "status": "ok"}],
        "samples": [{"status": "indexed", "warnings": []}],
        "discovery": [{"status": "ok"}],
        "searches": [{"status": "ok"}],
        "status": {"failed_job_count": 1},
        "search_index": {"skipped_embeddings": 0},
    }

    assert _overall_status(report) == "failed"


def test_overall_status_covers_each_remaining_terminal_path() -> None:
    base = {
        "preflight": [{"status": "ok"}],
        "samples": [{"status": "indexed", "warnings": []}],
        "discovery": [{"status": "ok"}],
        "searches": [{"status": "ok"}],
        "status": {"failed_job_count": 0},
        "search_index": {"skipped_embeddings": 0},
    }
    assert _overall_status(base) == "passed"
    assert _overall_status({**base, "preflight": [{"status": "error"}]}) == "failed"
    assert _overall_status({**base, "samples": [{"status": "failed", "warnings": []}]}) == "failed"
    assert _overall_status({**base, "searches": [{"status": "failed"}]}) == "failed"
    assert _overall_status({**base, "discovery": [{"status": "failed"}]}) == "failed"
    assert _overall_status({**base, "samples": [{"status": "indexed", "warnings": ["warning"]}]}) == "warning"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_json_probe_model_ids_and_manifest_resolution_cover_validation_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ppt_lib.sample_qa.urllib.request.urlopen", lambda url, timeout: _FakeResponse(b'{"data": []}'))
    assert _get_json("http://example.test") == {"data": []}

    monkeypatch.setattr("ppt_lib.sample_qa.urllib.request.urlopen", lambda url, timeout: _FakeResponse(b"[]"))
    with pytest.raises(RuntimeError, match="non-object JSON"):
        _get_json("http://example.test")

    def fail_urlopen(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr("ppt_lib.sample_qa.urllib.request.urlopen", fail_urlopen)
    with pytest.raises(RuntimeError, match="offline"):
        _get_json("http://example.test")

    assert _model_ids({"data": "invalid"}) == []
    assert _model_ids({"data": [{"id": "z"}, {"id": "a"}, {"missing": True}, "ignored"]}) == ["a", "z"]

    explicit = tmp_path / "explicit.json"
    assert _resolve_manifest_path(explicit) == explicit.resolve(strict=False)
    configured = tmp_path / "configured.json"
    monkeypatch.setenv(SAMPLE_MANIFEST_ENV, str(configured))
    assert _resolve_manifest_path(None) == configured.resolve(strict=False)


def test_write_markdown_report_contains_failures(tmp_path: Path) -> None:
    report = {
        "phase": "baseline",
        "fresh": True,
        "source_manifest_path": "/tmp/manifest.json",
        "preflight": [{"name": "embedding", "status": "ok", "message": "ready"}],
        "discovery": [{"label": "bad", "status": "missing", "discovered_count": 0, "path": "/tmp/missing.pptx"}],
        "samples": [
            {
                "label": "bad",
                "phase": "baseline",
                "path": "/tmp/missing.pptx",
                "exists": False,
                "status": "missing",
                "slides_indexed": 0,
                "duration_seconds": 0.0,
                "warnings": [],
                "errors": ["missing"],
            }
        ],
        "searches": [{"query": "AI 智能体", "status": "skipped", "top_results": []}],
        "search_index": {"skipped_embeddings": 0},
        "status": {"presentation_count": 0, "slide_count": 0},
    }

    report_path = write_markdown_report(report, tmp_path)

    text = report_path.read_text()
    assert "missing" in text
    assert "/tmp/missing.pptx" in text
