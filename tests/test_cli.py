from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from ppt_lib.cli import _config_overview_for_mode, build_envelope, main
from ppt_lib.indexer import ErrorRecord, IndexResult
from ppt_lib.searcher import SearchError, SearchResult
from ppt_lib.watch import WatchRuntimeError


def read_stdout(capsys):
    return json.loads(capsys.readouterr().out)


def test_build_envelope_has_meta_and_errors() -> None:
    envelope = build_envelope(
        "status",
        {"ok": True},
        [ErrorRecord("X", "bad", "test", "warning")],
        schema_version="1.0",
    )

    assert envelope["_meta"]["command"] == "status"
    assert envelope["ok"] is True
    assert envelope["_errors"][0]["code"] == "X"


def test_cli_index_single_calls_indexer(monkeypatch, capsys, tmp_path: Path) -> None:
    called: list[Path] = []

    def fake_index(path, settings, full=False):
        called.append(path)
        return IndexResult(path, "indexed", 1, [], [])

    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index)

    exit_code = main(["--home-dir", str(tmp_path), "index", str(tmp_path / "deck.pptx")])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert called == [tmp_path / "deck.pptx"]
    assert payload["result"]["status"] == "indexed"


def test_cli_index_batch_calls_index_batch(monkeypatch, capsys, tmp_path: Path) -> None:
    seen_full: list[bool] = []

    def fake_batch(root, settings, full=False):
        seen_full.append(full)
        return [IndexResult(root / "a.pptx", "indexed", 1, [], [])]

    monkeypatch.setattr(
        "ppt_lib.cli.index_batch",
        fake_batch,
    )

    exit_code = main(["--home-dir", str(tmp_path), "index", "--batch", "--full", str(tmp_path)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert seen_full == [True]
    assert payload["results"][0]["status"] == "indexed"


def test_cli_search_outputs_envelope(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.search",
        lambda query, options, settings: [
            SearchResult(1, 0.9, "Title", "summary", Path("/tmp/a.pptx"), 2, None, "text_extraction", 0.5, {})
        ],
    )

    exit_code = main(["--home-dir", str(tmp_path), "search", "query", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["results"][0]["title"] == "Title"
    assert payload["_meta"]["command"] == "search"


def test_cli_search_text_output_is_human_readable(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.search",
        lambda query, options, settings: [
            SearchResult(1, 0.9, "Title", "summary", Path("/tmp/a.pptx"), 2, None, "text_extraction", 0.5, {})
        ],
    )

    exit_code = main(["--home-dir", str(tmp_path), "search", "query", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("Search Results")
    assert "Title | score 0.900 | page 2" in output
    assert "_errors" not in output


def test_cli_search_text_output_uses_filename_for_missing_title(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.search",
        lambda query, options, settings: [
            SearchResult(1, 0.9, None, "summary", Path("/tmp/source deck.pptx"), 3, None, "text_extraction", 0.5, {})
        ],
    )

    exit_code = main(["--home-dir", str(tmp_path), "search", "query", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "source deck · P3 | score 0.900 | page 3" in output
    assert "来源: source deck.pptx" in output
    assert "/tmp/source deck.pptx" not in output


def test_cli_version_flag_outputs_version(capsys) -> None:
    exit_code = main(["--version"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("ppt-lib ")


def test_cli_search_preserves_search_error_code(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.search",
        lambda query, options, settings: (_ for _ in ()).throw(SearchError("empty", code="SEARCH_EMPTY_QUERY")),
    )

    exit_code = main(["--home-dir", str(tmp_path), "search", " "])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["results"] == []
    assert payload["_errors"][0]["code"] == "SEARCH_EMPTY_QUERY"


def test_cli_search_html_returns_html_path(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.search",
        lambda query, options, settings: [
            SearchResult(1, 0.9, "Title", "summary", Path("/tmp/a.pptx"), 2, None, "text_extraction", 0.5, {})
        ],
    )
    monkeypatch.setattr("ppt_lib.cli.render_search_review", lambda results, options, output_dir: output_dir / "review.html")

    exit_code = main(["--home-dir", str(tmp_path), "search", "query", "--html"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["html_path"].endswith("review.html")


def test_cli_search_forwards_assembled_view_flags(monkeypatch, capsys, tmp_path: Path) -> None:
    seen_options = []

    def fake_search(query, options, settings):
        seen_options.append(options)
        return []

    monkeypatch.setattr("ppt_lib.cli.search", fake_search)

    exit_code = main([
        "--home-dir", str(tmp_path),
        "search", "query",
        "--include-assembled",
        "--dedupe-lineage",
    ])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["results"] == []
    assert seen_options[0].include_assembled is True
    assert seen_options[0].dedupe_lineage is True


def test_cli_search_forwards_business_ranking_and_narrative_role(monkeypatch, capsys, tmp_path: Path) -> None:
    seen_options = []

    def fake_search(query, options, settings):
        seen_options.append(options)
        return []

    monkeypatch.setattr("ppt_lib.cli.search", fake_search)

    exit_code = main([
        "--home-dir", str(tmp_path),
        "search", "query",
        "--ranking", "business",
        "--narrative-role", "case",
    ])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["results"] == []
    assert seen_options[0].ranking == "business"
    assert seen_options[0].narrative_role == "case"


def test_cli_select_slides_outputs_report(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.selector import RoleSelection, SelectionReport

    monkeypatch.setattr(
        "ppt_lib.cli.select_slides",
        lambda settings, **kwargs: SelectionReport(
            query="retail",
            options={"roles": ["case"]},
            roles=[RoleSelection("case", [], True)],
            total_slides=0,
            gaps=["case"],
            timestamp="2026-05-25T00:00:00+00:00",
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "select-slides", "--roles", "case", "--brief", "retail"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "select-slides"
    assert payload["report"]["gaps"] == ["case"]


def test_cli_build_manifest_writes_manifest(monkeypatch, capsys, tmp_path: Path) -> None:
    selection = {
        "roles": [
            {
                "role": "case",
                "gap": False,
                "slides": [
                    {
                        "slide_id": 7,
                        "title": "Case",
                        "source_file": str(tmp_path / "case.pptx"),
                        "page_number": 2,
                    }
                ],
            }
        ],
        "gaps": [],
    }
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "manifest.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")

    exit_code = main([
        "--home-dir", str(tmp_path),
        "build-manifest",
        "--selection", str(selection_path),
        "--output", str(output_path),
        "--output-pptx", str(tmp_path / "output.pptx"),
        "--overwrite",
    ])
    payload = read_stdout(capsys)
    manifest = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["_meta"]["command"] == "build-manifest"
    assert payload["slide_count"] == 1
    assert manifest["slides"][0]["source_slide_id"] == 7
    assert manifest["output"]["overwrite"] is True


def test_cli_discover_outputs_items(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.discovery import DiscoveredPresentation

    monkeypatch.setattr(
        "ppt_lib.cli.scan_presentations",
        lambda root, settings: [
            DiscoveredPresentation(root / "a.pptx", None, "a.pptx", None, 1, 1.0, True, "candidate")
        ],
    )
    monkeypatch.setattr("ppt_lib.cli.deduplicate_versions", lambda items: items)
    monkeypatch.setattr("ppt_lib.cli.create_symlink_view", lambda items, settings: [])

    exit_code = main(["--home-dir", str(tmp_path), "discover", str(tmp_path)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["items"][0]["filename"] == "a.pptx"
    assert Path(payload["items"][0]["path"]).is_absolute()


def test_cli_status_includes_failed_jobs_and_orphans(capsys, tmp_path: Path) -> None:
    from ppt_lib.config import load_settings
    from ppt_lib.db import PresentationRecord, connect, create_or_update_job, init_db, upsert_presentation

    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "missing.pptx",
            filename="missing.pptx",
            project_name=None,
            slide_count=0,
            content_hash="hash",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    create_or_update_job(conn, tmp_path / "bad.pptx", "failed", error_msg="bad")

    exit_code = main(["--home-dir", str(tmp_path), "status", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["failed_jobs"][0]["file_path"].endswith("bad.pptx")
    assert payload["orphan_presentations"][0]["path"].endswith("missing.pptx")


def test_cli_status_text_output_is_human_readable(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "status", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library Status")
    assert "- PPT: 0" in output
    assert "_errors" not in output


def test_cli_versions_recompute_and_status(capsys, tmp_path: Path) -> None:
    from ppt_lib.config import load_settings
    from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide

    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    for filename in ["星河商学院数字化方案_v1.pptx", "星河商学院数字化方案_终稿.pptx"]:
        presentation_id = upsert_presentation(
            conn,
            PresentationRecord(
                path=tmp_path / filename,
                filename=filename,
                project_name="星河商学院",
                slide_count=1,
                content_hash=filename,
                file_size=1,
                file_mtime=1.0,
            ),
        )
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=0,
                title="星河商学院 数字化方案",
                text_content="星河商学院 数字化方案",
                embedding=None,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )

    recompute_exit = main(["--home-dir", str(tmp_path), "versions", "recompute", "--apply"])
    recompute_payload = read_stdout(capsys)
    status_exit = main(["--home-dir", str(tmp_path), "versions", "status", "--output", "json"])
    status_payload = read_stdout(capsys)

    assert recompute_exit == 0
    assert recompute_payload["result"]["family_count"] == 1
    assert status_exit == 0
    assert status_payload["status"]["presentation_version_count"] == 2
    assert status_payload["status"]["representative_count"] == 1


def test_cli_enrich_decks_writes_summary(capsys, tmp_path: Path) -> None:
    from ppt_lib.config import load_settings
    from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide

    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name="project",
            slide_count=1,
            content_hash="deck",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="内容中台方案",
            text_content="内容中台方案 架构 价值",
            embedding=None,
            screenshot_hash="hash",
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "enrich-decks", "--pending", "--limit", "1", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["result"]["processed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM deck_insights").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slide_importance").fetchone()[0] == 1


def test_cli_vision_test_outputs_report(monkeypatch, capsys, tmp_path: Path) -> None:
    class Report:
        def to_json(self):
            return {"checks": [], "recommended_chain": ["text_extraction"], "can_index": True, "can_use_vision": False, "_errors": []}

    monkeypatch.setattr("ppt_lib.cli.run_diagnostics", lambda settings: Report())

    exit_code = main(["--home-dir", str(tmp_path), "vision", "--test"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["recommended_chain"] == ["text_extraction"]


def test_cli_watch_outputs_structured_watch_error(monkeypatch, capsys, tmp_path: Path) -> None:
    def fail_watch(root, settings, callback):
        raise WatchRuntimeError("WATCH_OBSERVER_STOPPED", "observer stopped")

    monkeypatch.setattr("ppt_lib.cli.watch_directory", fail_watch)

    exit_code = main(["--home-dir", str(tmp_path), "watch", str(tmp_path)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["status"] == "stopped"
    assert payload["_errors"][0]["code"] == "WATCH_OBSERVER_STOPPED"


def test_cli_watch_missing_root_outputs_structured_error(monkeypatch, capsys, tmp_path: Path) -> None:
    def fail_watch(root, settings, callback):
        raise FileNotFoundError(root)

    monkeypatch.setattr("ppt_lib.cli.watch_directory", fail_watch)

    exit_code = main(["--home-dir", str(tmp_path), "watch", str(tmp_path / "missing")])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["_errors"][0]["code"] == "WATCH_ROOT_NOT_FOUND"


def test_cli_schema_outputs_json_schema(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "schema", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["schema"]["schema_version"] == "1.0"
    assert "init" in payload["schema"]["commands"]
    assert "sources" in payload["schema"]["commands"]
    assert "setup" in payload["schema"]["commands"]
    assert "doctor" in payload["schema"]["commands"]
    assert "config" in payload["schema"]["commands"]
    assert "qa sample" in payload["schema"]["commands"]
    assert "eval-search" in payload["schema"]["commands"]
    assert "prune" in payload["schema"]["commands"]
    assert "assemble" in payload["schema"]["commands"]
    assert "spike-assemble" in payload["schema"]["commands"]
    assert "record-deal" in payload["schema"]["commands"]
    assert "record-usage" in payload["schema"]["commands"]
    assert "recompute-stats" in payload["schema"]["commands"]
    assert "select-slides" in payload["schema"]["commands"]
    assert "build-manifest" in payload["schema"]["commands"]
    assert "models" in payload["schema"]["commands"]


def test_cli_schema_text_output_lists_commands(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "schema", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library Commands")
    assert "- search" in output
    assert "Agent/脚本需要机器输出时使用: --output json" in output


def test_cli_record_deal_creates_deal(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import connect, init_db

    exit_code = main([
        "--home-dir", str(tmp_path),
        "record-deal",
        "--name", "Retail Renewal",
        "--client-type", "retail",
        "--stage", "proposal",
        "--outcome", "won",
        "--notes", "pilot",
    ])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "record-deal"
    assert payload["deal"]["deal_name"] == "Retail Renewal"
    assert payload["deal"]["outcome"] == "won"
    conn = connect(tmp_path / "index.db")
    init_db(conn)
    row = conn.execute(
        "SELECT deal_name, client_type, deal_stage, outcome, notes FROM deals WHERE id = ?",
        (payload["deal"]["id"],),
    ).fetchone()
    assert row == ("Retail Renewal", "retail", "proposal", "won", "pilot")


def test_cli_record_usage_records_usage_and_recomputes(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import (
        PresentationRecord,
        SlideRecord,
        connect,
        init_db,
        insert_deal,
        upsert_presentation,
        upsert_slide,
    )

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    deck_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="hash",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=deck_id,
            slide_index=0,
            title="ROI",
            text_content="roi evidence",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Won Deal", outcome="won")

    exit_code = main([
        "--home-dir", str(tmp_path),
        "record-usage",
        "--deal-id", str(deal_id),
        "--slide-id", str(slide_id),
        "--deck-presentation-id", str(deck_id),
        "--position", "2",
    ])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "record-usage"
    assert payload["usage"]["slide_id"] == slide_id
    assert payload["usage"]["position"] == 2
    assert payload["stats"] == {"updated": 1}
    row = conn.execute(
        "SELECT reuse_count, won_count, lost_count, win_rate, last_deal_outcome FROM slides WHERE id = ?",
        (slide_id,),
    ).fetchone()
    assert row == (1, 1, 0, 1.0, "won")


def test_cli_record_usage_error_is_structured(capsys, tmp_path: Path) -> None:
    exit_code = main([
        "--home-dir", str(tmp_path),
        "record-usage",
        "--deal-id", "999",
        "--slide-id", "999",
        "--deck-presentation-id", "999",
    ])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["usage"] is None
    assert payload["_errors"][0]["code"] == "RECORD_USAGE_ERROR"


def test_cli_recompute_stats_updates_cache(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import (
        PresentationRecord,
        SlideRecord,
        connect,
        init_db,
        insert_deal,
        upsert_presentation,
        upsert_slide,
    )

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    deck_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="hash",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=deck_id,
            slide_index=0,
            title="Architecture",
            text_content="architecture",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Lost Deal", outcome="lost")
    conn.execute(
        """
        INSERT INTO slide_usage (slide_id, deal_id, deck_presentation_id, position, is_original, used_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (slide_id, deal_id, deck_id, 1, 1, "2026-05-25T00:00:00+00:00"),
    )
    conn.commit()

    exit_code = main(["--home-dir", str(tmp_path), "recompute-stats", "--slide-id", str(slide_id)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "recompute-stats"
    assert payload["result"] == {"updated": 1}
    row = conn.execute(
        "SELECT reuse_count, won_count, lost_count, win_rate, last_deal_outcome FROM slides WHERE id = ?",
        (slide_id,),
    ).fetchone()
    assert row == (1, 0, 1, 0.0, "lost")


def test_cli_import_metadata_updates_slide_columns(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import (
        PresentationRecord,
        SlideRecord,
        connect,
        init_db,
        upsert_presentation,
        upsert_slide,
    )

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    deck_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="hash",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=deck_id,
            slide_index=0,
            title="Case",
            text_content="case evidence",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    jsonl = tmp_path / "metadata.jsonl"
    jsonl.write_text(
        json.dumps({
            "slide_id": slide_id,
            "industry": "retail",
            "scenario": "renewal",
            "narrative_role": "case",
            "quality_rating": 4,
        }) + "\n",
        encoding="utf-8",
    )

    exit_code = main(["--home-dir", str(tmp_path), "import-metadata", "--jsonl", str(jsonl)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "import-metadata"
    assert payload["result"] == {"imported": 1, "skipped": 0, "updated_slide_ids": [slide_id]}
    row = conn.execute(
        "SELECT industry, scenario, narrative_role, quality_rating FROM slides WHERE id = ?",
        (slide_id,),
    ).fetchone()
    assert row == ("retail", "renewal", "case", 4)


def test_cli_import_metadata_error_is_structured(capsys, tmp_path: Path) -> None:
    jsonl = tmp_path / "bad.jsonl"
    jsonl.write_text("{bad json}\n", encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path), "import-metadata", "--jsonl", str(jsonl)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["result"] is None
    assert payload["_errors"][0]["code"] == "METADATA_IMPORT_ERROR"


def test_cli_export_metadata_writes_sanitized_jsonl(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import (
        PresentationRecord,
        SlideRecord,
        connect,
        init_db,
        upsert_presentation,
        upsert_slide,
    )

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    deck_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "sensitive-client" / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="hash",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=deck_id,
            slide_index=0,
            title="Private title",
            text_content="private content",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    conn.execute(
        """
        UPDATE slides
        SET industry = ?, scenario = ?, narrative_role = ?, quality_rating = ?
        WHERE id = ?
        """,
        ("retail", "renewal", "case", 5, slide_id),
    )
    conn.commit()
    output = tmp_path / "exported.jsonl"

    exit_code = main(["--home-dir", str(tmp_path), "export-metadata", "--output", str(output)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "export-metadata"
    assert payload["result"]["exported"] == 1
    exported = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert exported == [{
        "slide_id": slide_id,
        "industry": "retail",
        "scenario": "renewal",
        "narrative_role": "case",
        "quality_rating": 5,
        "win_rate": None,
        "won_count": 0,
        "lost_count": 0,
        "reuse_count": 0,
        "last_deal_outcome": None,
        "origin_type": "original",
    }]
    assert "sensitive-client" not in output.read_text(encoding="utf-8")
    assert "Private title" not in output.read_text(encoding="utf-8")


def test_cli_setup_lmstudio_writes_non_sensitive_config(monkeypatch, capsys, tmp_path: Path) -> None:
    class Report:
        def to_json(self):
            return {
                "checks": [{"name": "lmstudio", "status": "ok"}],
                "recommended_chain": ["lmstudio", "text_extraction"],
                "can_index": True,
                "can_use_vision": True,
                "_errors": [],
            }

    monkeypatch.setattr("ppt_lib.cli.run_diagnostics", lambda settings: Report())
    monkeypatch.setattr("ppt_lib.cli.detect_lmstudio_chat_model", lambda base_url: "qwen/qwen3.6-27b")

    exit_code = main(["--home-dir", str(tmp_path), "setup", "--mode", "lmstudio", "--non-interactive"])
    payload = read_stdout(capsys)
    config = yaml.safe_load((tmp_path / "config.yml").read_text())

    assert exit_code == 0
    assert payload["_meta"]["command"] == "setup"
    assert payload["mode"] == "lmstudio"
    assert payload["diagnostics"]["recommended_chain"] == ["lmstudio", "text_extraction"]
    assert "ppt-lib index --from-sources" in payload["next_commands"]
    assert config["embedding_provider"] == "lmstudio"
    assert config["embedding_dimensions"] == 768
    assert config["vision_provider"] == "auto"
    assert config["lmstudio_vision_model"] == "qwen/qwen3.6-27b"
    assert "openai_api_key" not in config


def test_cli_setup_text_output_is_human_readable(monkeypatch, capsys, tmp_path: Path) -> None:
    class Report:
        def to_json(self):
            return {
                "checks": [{"name": "lmstudio", "status": "ok", "message": "ready"}],
                "recommended_chain": ["lmstudio", "text_extraction"],
                "can_index": True,
                "can_use_vision": True,
                "_errors": [],
            }

    monkeypatch.setattr("ppt_lib.cli.run_diagnostics", lambda settings: Report())
    monkeypatch.setattr("ppt_lib.cli.detect_lmstudio_chat_model", lambda base_url: None)

    exit_code = main(["--home-dir", str(tmp_path), "setup", "--mode", "lmstudio", "--non-interactive", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library Setup")
    assert "- lmstudio: ok - ready" in output
    assert "ppt-lib sources scan --apply" in output
    assert "ppt-lib index --from-sources" in output
    assert "--with-ai-summary" not in output
    assert "_errors" not in output


def test_setup_overview_distinguishes_vision_model_from_indexing_limit() -> None:
    overview = _config_overview_for_mode("lmstudio", vision_model="google/gemma-4-26b-a4b")

    assert "google/gemma-4-26b-a4b" in overview
    assert "vision calls during indexing=disabled by default" in overview
    assert "vision=off" not in overview


def test_cli_models_test_returns_error_exit_when_gate_fails(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.models_test.run_models_test",
        lambda settings: {
            "summary": {"status": "error", "total": 1, "ok": 0, "error": 1, "warning": 0},
            "probes": [{"capability": "chat", "status": "error"}],
        },
    )

    exit_code = main(["--home-dir", str(tmp_path), "models", "test"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["summary"]["status"] == "error"
    assert payload["_errors"][0]["code"] == "MODEL_COMPATIBILITY_CHECK_FAILED"


def test_cli_models_test_passes_when_gate_passes(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.models_test.run_models_test",
        lambda settings: {
            "summary": {"status": "ok", "total": 1, "ok": 1, "error": 0, "warning": 0},
            "probes": [{"capability": "chat", "status": "ok"}],
        },
    )

    exit_code = main(["--home-dir", str(tmp_path), "models", "test"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["summary"]["status"] == "ok"
    assert payload["_errors"] == []


def test_cli_doctor_aggregates_diagnostics_and_index_health(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.config import load_settings
    from ppt_lib.db import PresentationRecord, connect, create_or_update_job, init_db, upsert_presentation

    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "missing.pptx",
            filename="missing.pptx",
            project_name=None,
            slide_count=0,
            content_hash="hash",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    create_or_update_job(conn, tmp_path / "bad.pptx", "failed", error_msg="bad")

    class Report:
        def to_json(self):
            return {
                "checks": [],
                "recommended_chain": ["text_extraction"],
                "chains": {
                    "embedding": {"provider": "fake", "status": "ok", "message": "ready"},
                    "vision": {"provider": "text_extraction", "status": "skipped", "message": "disabled"},
                    "fallback": {"provider": "text_extraction", "status": "ok", "message": "ready"},
                },
                "can_index": True,
                "can_use_vision": False,
                "_errors": [],
            }

    monkeypatch.setattr("ppt_lib.doctor.run_diagnostics", lambda settings: Report())

    exit_code = main(["--home-dir", str(tmp_path), "doctor", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_meta"]["command"] == "doctor"
    assert payload["summary"]["status"] == "error"
    assert payload["index"]["stats"]["failed_job_count"] == 1
    assert payload["index"]["stats"]["orphan_presentation_count"] == 1
    assert payload["diagnostics"]["chains"]["embedding"]["status"] == "ok"
    assert payload["recommendations"]
    assert payload["_errors"][0]["code"] == "DOCTOR_ERROR"


def test_cli_doctor_text_output_is_human_readable(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.run_doctor",
        lambda settings: {
            "summary": {"status": "warning", "can_index": True, "can_use_vision": False},
            "diagnostics": {"checks": [{"name": "lmstudio", "status": "warning", "message": "not ready"}]},
            "index": {"stats": {"presentation_count": 0, "slide_count": 0, "failed_job_count": 0}},
            "recommendations": ["Start LM Studio."],
        },
    )

    exit_code = main(["--home-dir", str(tmp_path), "doctor", "--output", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library Doctor")
    assert "- 总体状态: warning" in output
    assert "Start LM Studio." in output


def test_cli_doctor_warning_returns_success(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.run_doctor",
        lambda settings: {
            "summary": {"status": "warning", "can_index": True, "can_use_vision": False},
            "config": {},
            "diagnostics": {},
            "index": {},
            "recommendations": ["Vision is unavailable."],
        },
    )

    exit_code = main(["--home-dir", str(tmp_path), "doctor", "--output", "json"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["summary"]["status"] == "warning"
    assert payload["_errors"] == []


def test_cli_config_path_and_get_outputs_masked_values(capsys, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PPT_LIB_OPENAI_API_KEY", "secret-key")

    path_exit = main(["--home-dir", str(tmp_path), "config", "path"])
    path_payload = read_stdout(capsys)
    get_exit = main(["--home-dir", str(tmp_path), "config", "get", "openai_api_key"])
    get_payload = read_stdout(capsys)

    assert path_exit == 0
    assert path_payload["config_path"].endswith("config.yml")
    assert get_exit == 0
    assert get_payload["key"] == "openai_api_key"
    assert get_payload["value"] == "present"
    assert get_payload["source"] == "effective"


def test_cli_config_path_uses_actual_loaded_file_not_config_home_dir(capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(f"home_dir: {tmp_path / 'other-home'}\n", encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path), "config", "path"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert Path(payload["config_path"]) == config_path.resolve(strict=False)


def test_cli_config_get_without_key_outputs_full_masked_config(capsys, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PPT_LIB_OPENAI_API_KEY", "secret-key")

    exit_code = main(["--home-dir", str(tmp_path), "config", "get"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["config"]["embedding_provider"] == "openai"
    assert payload["config"]["openai_api_key"] == "present"


def test_cli_config_set_writes_yaml_typed_value(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "search_top_k", "9"])
    payload = read_stdout(capsys)
    config = yaml.safe_load((tmp_path / "config.yml").read_text())

    assert exit_code == 0
    assert payload["key"] == "search_top_k"
    assert payload["old_value"] == 5
    assert payload["new_value"] == 9
    assert payload["changed"] is True
    assert config["search_top_k"] == 9


def test_cli_config_set_rejects_sensitive_key(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "openai_api_key", "secret"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "CONFIG_SENSITIVE_KEY_REJECTED"
    assert not (tmp_path / "config.yml").exists()


def test_cli_config_set_rejects_unknown_key(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "unknown_key", "1"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "CONFIG_UNKNOWN_KEY"


def test_cli_config_set_rejects_home_dir(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "home_dir", str(tmp_path / "other")])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "CONFIG_KEY_NOT_WRITABLE"


def test_cli_config_set_rejects_invalid_value_without_writing(capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    main(["--home-dir", str(tmp_path), "config", "set", "search_top_k", "5"])
    read_stdout(capsys)

    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "search_top_k", "0"])
    payload = read_stdout(capsys)
    config = yaml.safe_load(config_path.read_text())

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "CONFIG_VALIDATION_ERROR"
    assert config["search_top_k"] == 5


def test_cli_config_set_invalid_value_does_not_create_config(capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"

    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "search_top_k", "0"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "CONFIG_VALIDATION_ERROR"
    assert not config_path.exists()


def test_cli_config_set_can_repair_invalid_existing_config(capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("search_top_k: 0\n", encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path), "config", "set", "search_top_k", "5"])
    payload = read_stdout(capsys)
    config = yaml.safe_load(config_path.read_text())

    assert exit_code == 0
    assert payload["new_value"] == 5
    assert config["search_top_k"] == 5


def test_cli_usage_errors_are_enveloped(capsys) -> None:
    exit_code = main(["config", "set", "search_top_k"])
    payload = read_stdout(capsys)

    assert exit_code == 2
    assert payload["_errors"][0]["code"] == "CLI_USAGE_ERROR"


def test_cli_no_args_outputs_human_help(capsys) -> None:
    exit_code = main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library CLI ")
    assert "常用命令：" in output
    assert "ppt-lib doctor --output json" in output
    assert "ppt-lib index --from-sources" in output
    assert "--with-ai-summary" not in output
    assert "_errors" not in output


def test_cli_no_command_with_home_dir_outputs_human_help(capsys, tmp_path: Path) -> None:
    exit_code = main(["--home-dir", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("PPT Library CLI ")
    assert "ppt-lib sources scan --apply" in output
    assert "_errors" not in output


def test_cli_qa_sample_forwards_arguments(monkeypatch, capsys, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run_local_sample_qa(**kwargs):
        seen.update(kwargs)
        return {
            "overall_status": "warning",
            "report_path": str(tmp_path / "reports" / "report.md"),
            "json_path": str(tmp_path / "reports" / "latest.json"),
            "selection_path": str(tmp_path / "reports" / "manifest.json"),
            "phase": kwargs["phase"],
            "fresh": kwargs["fresh"],
        }

    monkeypatch.setattr("ppt_lib.cli.run_local_sample_qa", fake_run_local_sample_qa)

    exit_code = main(
        [
            "--home-dir",
            str(tmp_path / "home"),
            "qa",
            "sample",
            "--phase",
            "complex",
            "--max-files",
            "2",
            "--report-dir",
            str(tmp_path / "reports"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--vision-limit",
            "1",
            "--no-full",
            "--fresh",
        ]
    )
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "qa"
    assert payload["overall_status"] == "warning"
    assert payload["phase"] == "complex"
    assert payload["fresh"] is True
    assert seen["max_files"] == 2
    assert seen["vision_limit"] == 1
    assert seen["full"] is False


def test_cli_qa_sample_failed_report_returns_error(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ppt_lib.cli.run_local_sample_qa",
        lambda **kwargs: {
            "overall_status": "failed",
            "report_path": str(tmp_path / "report.md"),
            "json_path": str(tmp_path / "latest.json"),
            "selection_path": str(tmp_path / "manifest.json"),
            "phase": "baseline",
            "fresh": False,
        },
    )

    exit_code = main(["--home-dir", str(tmp_path), "qa", "sample"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "QA_SAMPLE_FAILED"


def test_cli_qa_sample_manifest_error_is_structured(capsys, tmp_path: Path) -> None:
    manifest = tmp_path / "bad-manifest.json"
    manifest.write_text("{", encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path / "home"), "qa", "sample", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "QA_SAMPLE_MANIFEST_ERROR"


def test_cli_qa_sample_manifest_missing_path_is_structured(capsys, tmp_path: Path) -> None:
    manifest = tmp_path / "bad-manifest.json"
    manifest.write_text('[{"phase":"baseline"}]', encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path / "home"), "qa", "sample", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "QA_SAMPLE_MANIFEST_ERROR"
    assert "missing path" in payload["_errors"][0]["message"]


def test_cli_qa_sample_manifest_empty_path_is_structured(capsys, tmp_path: Path) -> None:
    manifest = tmp_path / "bad-manifest.json"
    manifest.write_text('[{"phase":"baseline","path":"  "}]', encoding="utf-8")

    exit_code = main(["--home-dir", str(tmp_path / "home"), "qa", "sample", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "QA_SAMPLE_MANIFEST_ERROR"
    assert "missing path" in payload["_errors"][0]["message"]


def test_cli_eval_search_outputs_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.evaluation import SearchEvaluationReport, SearchEvaluationSummary

    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"version":"1.0","queries":[{"id":"q1","query":"x","expected_title_keywords":["x"]}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_evaluation_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.evaluate_search_manifest",
        lambda manifest, settings, top_k, threshold: SearchEvaluationReport(
            manifest_version="1.0",
            summary=SearchEvaluationSummary(1, 1, 0, 1.0, 1.0, 1.0, True, "passed"),
            query_results=[],
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "eval-search", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["summary"]["quality_status"] == "passed"


def test_cli_eval_search_calibrate_outputs_threshold(monkeypatch, capsys, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"version":"1.0","queries":[{"id":"q1","query":"x","expected_title_keywords":["x"]}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_evaluation_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.calibrate_search_thresholds",
        lambda manifest, settings, top_k: {"recommended_threshold": 0.35, "target_met": True},
    )

    exit_code = main(["--home-dir", str(tmp_path), "eval-search", "--manifest", str(manifest), "--calibrate"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["recommended_threshold"] == 0.35


def test_cli_eval_search_preserves_embedding_error(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.embedding import EmbeddingProviderError

    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"version":"1.0","queries":[{"id":"q1","query":"x","expected_title_keywords":["x"]}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_evaluation_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.evaluate_search_manifest",
        lambda manifest, settings, top_k, threshold: (_ for _ in ()).throw(
            EmbeddingProviderError("missing", code="EMBEDDING_AUTH_MISSING")
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "eval-search", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "EMBEDDING_AUTH_MISSING"


def test_cli_prune_defaults_to_dry_run(monkeypatch, capsys, tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class Result:
        dry_run: bool = True
        backup_path: str | None = None
        presentation_count: int = 1
        slide_count: int = 1
        job_count: int = 0
        screenshot_count: int = 0
        removed_presentations: list[str] = field(default_factory=lambda: ["/tmp/missing.pptx"])
        warnings: list[str] = field(default_factory=list)

    seen_dry_run: list[bool] = []

    def fake_prune(conn, settings, dry_run=True):
        seen_dry_run.append(dry_run)
        return Result()

    monkeypatch.setattr("ppt_lib.cli.prune_orphans", fake_prune)

    exit_code = main(["--home-dir", str(tmp_path), "prune"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert seen_dry_run == [True]
    assert payload["result"]["presentation_count"] == 1


def test_cli_prune_apply_sets_dry_run_false(monkeypatch, capsys, tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class Result:
        dry_run: bool = False
        backup_path: str | None = str(tmp_path / "backups" / "index.db")
        presentation_count: int = 1
        slide_count: int = 1
        job_count: int = 0
        screenshot_count: int = 0
        removed_presentations: list[str] = field(default_factory=lambda: ["/tmp/missing.pptx"])
        warnings: list[str] = field(default_factory=list)

    seen_dry_run: list[bool] = []

    def fake_prune(conn, settings, dry_run=True):
        seen_dry_run.append(dry_run)
        return Result()

    monkeypatch.setattr("ppt_lib.cli.prune_orphans", fake_prune)

    exit_code = main(["--home-dir", str(tmp_path), "prune", "--apply"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert seen_dry_run == [False]
    assert payload["result"]["dry_run"] is False


def test_cli_purge_assembled_output_apply(monkeypatch, capsys, tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class Result:
        dry_run: bool = False
        backup_path: str | None = str(tmp_path / "backups" / "index.db")
        presentation_count: int = 1
        slide_count: int = 1
        lineage_count: int = 1
        assemble_run_count: int = 1
        job_count: int = 1
        screenshot_count: int = 0
        warnings: list[str] = field(default_factory=list)

    seen_dry_run: list[bool] = []

    def fake_purge(conn, settings, dry_run=True):
        seen_dry_run.append(dry_run)
        return Result()

    monkeypatch.setattr("ppt_lib.cli.purge_assembled_output", fake_purge)

    exit_code = main(["--home-dir", str(tmp_path), "purge", "--type", "assembled_output", "--apply"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert seen_dry_run == [False]
    assert payload["result"]["lineage_count"] == 1


def test_cli_spike_assemble_outputs_report(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assemble_spike import AssembleSpikeReport

    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"samples":[{"id":"s1","path":"/tmp/a.pptx","slides":[1]}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_assemble_spike_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.run_assemble_spike",
        lambda manifest, output_dir: AssembleSpikeReport(
            generated_at="2026-05-23T00:00:00+00:00",
            manifest_version="1.0",
            sample_count=1,
            route_results=[],
            recommendation="review",
            report_path=str(output_dir / "report.json"),
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "spike-assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["report"]["recommendation"] == "review"


def test_cli_spike_assemble_defaults_output_dir_next_to_manifest(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assemble_spike import AssembleSpikeReport

    gstack = tmp_path / ".gstack"
    gstack.mkdir()
    manifest = gstack / "assemble-spike-manifest.json"
    manifest.write_text('{"samples":[{"id":"s1","path":"/tmp/a.pptx","slides":[1]}]}', encoding="utf-8")
    seen_output_dirs: list[Path] = []

    monkeypatch.setattr("ppt_lib.cli.load_assemble_spike_manifest", lambda path: object())

    def fake_run(manifest, output_dir):
        seen_output_dirs.append(output_dir)
        return AssembleSpikeReport(
            generated_at="2026-05-23T00:00:00+00:00",
            manifest_version="1.0",
            sample_count=1,
            route_results=[],
            recommendation="review",
            report_path=str(output_dir / "report.json"),
        )

    monkeypatch.setattr("ppt_lib.cli.run_assemble_spike", fake_run)

    exit_code = main(["--home-dir", str(tmp_path), "spike-assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert seen_output_dirs == [gstack / "assemble-spike-reports"]
    assert payload["report"]["report_path"].endswith(".gstack/assemble-spike-reports/report.json")


def test_cli_spike_assemble_manifest_error_is_structured(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assemble_spike import AssembleSpikeManifestError

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "ppt_lib.cli.load_assemble_spike_manifest",
        lambda path: (_ for _ in ()).throw(AssembleSpikeManifestError("bad")),
    )

    exit_code = main(["--home-dir", str(tmp_path), "spike-assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "ASSEMBLE_SPIKE_MANIFEST_ERROR"


def test_cli_assemble_outputs_report(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport

    manifest = tmp_path / "assemble-manifest.json"
    manifest.write_text('{"slides":[{"source_file":"/tmp/a.pptx","page_number":1}]}', encoding="utf-8")
    output_path = tmp_path / "assembled" / "output.pptx"

    monkeypatch.setattr("ppt_lib.cli.load_assemble_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.run_assemble",
        lambda manifest: AssembleReport(
            schema_version="1.0",
            run_id="run-1",
            status="needs_manual_review",
            output_path=output_path,
            slide_count=1,
            slides=[],
            errors=[],
            fidelity=AssembleFidelityReport("", "", True, ["fidelity_render_failed: missing libreoffice"]),
            report_path=tmp_path / "assembled" / "assemble-report.json",
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["_meta"]["command"] == "assemble"
    assert payload["report"]["status"] == "needs_manual_review"
    assert payload["report"]["output_path"].endswith("output.pptx")
    assert payload["_errors"] == []


def test_cli_assemble_ingest_creates_lineage(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport, AssembleSlideReport
    from ppt_lib.db import (
        PresentationRecord,
        SlideRecord,
        connect,
        init_db,
        upsert_presentation,
        upsert_slide,
    )

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    source_presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "source.pptx",
            filename="source.pptx",
            project_name=None,
            slide_count=1,
            content_hash="source",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    source_slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=source_presentation_id,
            slide_index=0,
            title="Source",
            text_content="source body",
            embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    manifest = tmp_path / "assemble-manifest.json"
    output_path = tmp_path / "assembled" / "output.pptx"
    manifest.write_text(
        json.dumps({
            "run_name": "p0c-smoke",
            "output": {"path": str(output_path), "overwrite": True},
            "options": {"render_fidelity_baseline": False},
            "slides": [{
                "source_file": str(tmp_path / "source.pptx"),
                "page_number": 1,
                "source_slide_id": source_slide_id,
            }],
        }),
        encoding="utf-8",
    )

    def fake_run(assemble_manifest):
        return AssembleReport(
            schema_version="1.0",
            run_id="run-1",
            status="needs_manual_review",
            output_path=assemble_manifest.output_path,
            slide_count=1,
            slides=[AssembleSlideReport(1, str(tmp_path / "source.pptx"), 1, "copied", "low", [])],
            errors=[],
            fidelity=AssembleFidelityReport("", "", True, []),
            report_path=assemble_manifest.output_path.parent / "assemble-report.json",
        )

    def fake_index(path, settings, full=False):
        output_presentation_id = upsert_presentation(
            conn,
            PresentationRecord(
                path=path,
                filename=path.name,
                project_name=None,
                slide_count=1,
                content_hash="output",
                file_size=100,
                file_mtime=1.0,
            ),
        )
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=output_presentation_id,
                slide_index=0,
                title="Output",
                text_content="source body",
                embedding=np.ones(1536, dtype=np.float32),
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
        return IndexResult(path, "indexed", 1, [], [])

    monkeypatch.setattr("ppt_lib.cli.run_assemble", fake_run)
    monkeypatch.setattr("ppt_lib.cli.index_file", fake_index)

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest), "--ingest-output"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["ingest"]["status"] == "completed"
    assert payload["ingest"]["lineage_count"] == 1
    derived = conn.execute("SELECT id, origin_type FROM slides WHERE title = 'Output'").fetchone()
    assert derived[1] == "assembled_output"
    lineage = conn.execute(
        "SELECT derived_slide_id, source_slide_id FROM slide_lineage"
    ).fetchone()
    assert lineage == (derived[0], source_slide_id)


def test_cli_assemble_ingest_index_failure_keeps_pending_run(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport, AssembleSlideReport
    from ppt_lib.db import connect, init_db

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    manifest = tmp_path / "assemble-manifest.json"
    output_path = tmp_path / "assembled" / "output.pptx"
    manifest.write_text(
        json.dumps({
            "run_name": "p0c-failed-index",
            "output": {"path": str(output_path), "overwrite": True},
            "options": {"render_fidelity_baseline": False},
            "slides": [{"source_file": str(tmp_path / "source.pptx"), "page_number": 1, "source_slide_id": 1}],
        }),
        encoding="utf-8",
    )

    def fake_run(assemble_manifest):
        return AssembleReport(
            schema_version="1.0",
            run_id="run-1",
            status="needs_manual_review",
            output_path=assemble_manifest.output_path,
            slide_count=1,
            slides=[AssembleSlideReport(1, str(tmp_path / "source.pptx"), 1, "copied", "low", [])],
            errors=[],
            fidelity=AssembleFidelityReport("", "", True, []),
            report_path=assemble_manifest.output_path.parent / "assemble-report.json",
        )

    monkeypatch.setattr("ppt_lib.cli.run_assemble", fake_run)
    monkeypatch.setattr(
        "ppt_lib.cli.index_file",
        lambda path, settings, full=False: IndexResult(path, "failed", 0, [], [ErrorRecord("INDEX_FAILED", "bad", "indexer")]),
    )

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest), "--ingest-output"])
    payload = read_stdout(capsys)

    assert exit_code == 0
    assert payload["ingest"]["status"] == "completed_pending_ingest"
    assert payload["_errors"][0]["code"] == "ASSEMBLE_INGEST_PENDING"
    assert payload["_errors"][0]["severity"] == "warning"
    row = conn.execute("SELECT run_name, status FROM assemble_runs").fetchone()
    assert row == ("p0c-failed-index", "completed_pending_ingest")


def test_cli_assemble_manifest_error_is_structured(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assembler import AssembleManifestError

    manifest = tmp_path / "assemble-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "ppt_lib.cli.load_assemble_manifest",
        lambda path: (_ for _ in ()).throw(AssembleManifestError("bad")),
    )

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["report"] is None
    assert payload["_errors"][0]["code"] == "ASSEMBLE_MANIFEST_ERROR"


def test_cli_assemble_failed_report_returns_run_error(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport

    manifest = tmp_path / "assemble-manifest.json"
    manifest.write_text('{"slides":[{"source_file":"/tmp/a.pptx","page_number":1}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_assemble_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.run_assemble",
        lambda manifest: AssembleReport(
            schema_version="1.0",
            run_id="run-1",
            status="failed",
            output_path=tmp_path / "assembled" / "output.pptx",
            slide_count=0,
            slides=[],
            errors=["package_error: bad pptx"],
            fidelity=AssembleFidelityReport("", "", True, []),
            report_path=tmp_path / "assembled" / "assemble-report.json",
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["report"]["status"] == "failed"
    assert payload["_errors"][0]["code"] == "ASSEMBLE_RUN_FAILED"


def test_cli_assemble_package_error_is_not_internal_error(monkeypatch, capsys, tmp_path: Path) -> None:
    from ppt_lib.pptx_package import PptxPackageError

    manifest = tmp_path / "assemble-manifest.json"
    manifest.write_text('{"slides":[{"source_file":"/tmp/a.pptx","page_number":1}]}', encoding="utf-8")

    monkeypatch.setattr("ppt_lib.cli.load_assemble_manifest", lambda path: object())
    monkeypatch.setattr(
        "ppt_lib.cli.run_assemble",
        lambda manifest: (_ for _ in ()).throw(PptxPackageError("bad pptx package")),
    )

    exit_code = main(["--home-dir", str(tmp_path), "assemble", "--manifest", str(manifest)])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["report"] is None
    assert payload["_errors"][0]["code"] == "ASSEMBLE_RUN_FAILED"


def test_cli_assets_prune_removes_orphan_slide_assets(capsys, tmp_path: Path) -> None:
    from ppt_lib.db import connect, init_db

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    conn.close()

    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    orphan_file = asset_dir / "orphan.png"
    orphan_file.write_bytes(b"preview")
    unsafe_file = tmp_path / "outside.png"
    unsafe_file.write_bytes(b"outside")

    raw_conn = sqlite3.connect(tmp_path / "index.db")
    raw_conn.execute("PRAGMA foreign_keys = OFF")
    raw_conn.execute(
        "INSERT INTO slide_assets (slide_id, asset_type, asset_uri) VALUES (?, ?, ?)",
        (999, "thumbnail", str(orphan_file)),
    )
    raw_conn.execute(
        "INSERT INTO slide_assets (slide_id, asset_type, asset_uri) VALUES (?, ?, ?)",
        (1000, "thumbnail", str(unsafe_file)),
    )
    raw_conn.commit()
    raw_conn.close()

    dry_exit = main(["--home-dir", str(tmp_path), "assets", "prune", "--dry-run", "--output", "json"])
    dry_payload = read_stdout(capsys)

    assert dry_exit == 0
    assert dry_payload["result"]["orphan_slide_assets"] == 2
    assert dry_payload["result"]["unsafe_orphan_slide_assets"] == 1
    assert dry_payload["result"]["deleted"] == 0
    assert orphan_file.exists()
    assert unsafe_file.exists()

    apply_exit = main(["--home-dir", str(tmp_path), "assets", "prune", "--apply", "--output", "json"])
    apply_payload = read_stdout(capsys)

    assert apply_exit == 0
    assert apply_payload["result"]["orphan_slide_assets"] == 2
    assert apply_payload["result"]["unsafe_orphan_slide_assets"] == 1
    assert apply_payload["result"]["deleted"] == 1
    assert not orphan_file.exists()
    assert unsafe_file.exists()

    check_conn = sqlite3.connect(tmp_path / "index.db")
    assert check_conn.execute("SELECT asset_uri FROM slide_assets").fetchone()[0] == str(unsafe_file)
    check_conn.close()


def test_cli_profile_build_reports_partial_when_baseline_cannot_be_read(
    capsys,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "broken.pptx"
    baseline.write_bytes(b"not a valid pptx")
    manifest = tmp_path / "sources-manifest.json"
    manifest.write_text(
        json.dumps({"sources": {"baseline": [str(baseline)]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    init_exit = main([
        "--home-dir", str(tmp_path),
        "init",
        "--manifest", str(manifest),
        "--non-interactive",
        "--output", "json",
    ])
    read_stdout(capsys)
    assert init_exit == 0

    profile_exit = main(["--home-dir", str(tmp_path), "profile", "build", "--output", "json"])
    payload = read_stdout(capsys)

    assert profile_exit == 0
    assert payload["status"] == "partial"
    assert payload["ready"] is False
    assert payload["_errors"][0]["code"] == "PROFILE_BASELINE_READ_WARNING"


def test_cli_errors_enveloped(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.cli.search", lambda query, options, settings: (_ for _ in ()).throw(RuntimeError("boom")))

    exit_code = main(["--home-dir", str(tmp_path), "search", "query"])
    payload = read_stdout(capsys)

    assert exit_code == 1
    assert payload["_errors"][0]["code"] == "INTERNAL_ERROR"


def test_cli_exit_codes_for_argparse_error() -> None:
    assert main(["search"]) == 2
