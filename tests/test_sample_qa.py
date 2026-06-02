from __future__ import annotations

import json
from pathlib import Path

from ppt_lib.config import load_settings
from ppt_lib.sample_qa import (
    SEARCH_QUERIES,
    SampleSpec,
    _evaluate_search_quality,
    _overall_status,
    _run_searches,
    build_local_sample_settings,
    load_samples,
    run_discovery_checks,
    run_local_sample_qa,
    select_samples,
    write_manifest,
    write_markdown_report,
)


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


def test_searches_warn_when_query_returns_no_results(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")

    rows = _run_searches(settings, enabled=True)

    assert rows
    assert {row["status"] for row in rows} == {"warning"}
    assert all(row["error"] == "no search results" for row in rows)


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
