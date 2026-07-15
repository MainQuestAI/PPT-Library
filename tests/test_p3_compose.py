"""Tests for ppt-lib compose command (P3-C1/C2/C3)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ppt_lib.config import load_settings
from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, insert_deal, upsert_presentation, upsert_slide


class StaticProvider:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector.astype(np.float32)
        self.model = "static"
        self.dimensions = int(self.vector.shape[0])

    def encode(self, text: str) -> np.ndarray:
        return self.vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


def _seed_db(tmp_path: Path) -> None:
    """Create a minimal DB with opener + case slides."""
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    for title, role in [("opener_a", "opener"), ("case_a", "case"), ("solution_a", "solution")]:
        pres_id = upsert_presentation(
            conn,
            PresentationRecord(
                path=tmp_path / f"{title}.pptx",
                filename=f"{title}.pptx",
                project_name="project",
                slide_count=1,
                content_hash=title,
                file_size=100,
                file_mtime=1.0,
            ),
        )
        slide_id = upsert_slide(
            conn,
            SlideRecord(
                presentation_id=pres_id,
                slide_index=0,
                title=title,
                text_content=f"{title} retail digital transformation",
                embedding=np.ones(1536, dtype=np.float32),
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
        conn.execute("UPDATE slides SET narrative_role = ? WHERE id = ?", (role, slide_id))
    conn.commit()
    conn.close()


# --- compose --roles (C1) ---

def test_compose_roles_no_llm_full_path(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    from ppt_lib.composer import compose
    result = compose(
        settings,
        roles=["opener", "case"],
        brief="retail digital",
        dry_run=True,  # dry-run to avoid actual pptx assemble
    )

    assert result.dry_run is True
    assert result.selection_report.total_slides == 2
    assert result.gaps == []
    assert (result.run_dir / "selection-report.json").exists()
    assert (result.run_dir / "narrative-plan.json").exists()
    assert (result.run_dir / "manifest.json").exists()


# --- compose --dry-run (C2) ---

def test_compose_dry_run_does_not_produce_pptx(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    from ppt_lib.composer import compose
    result = compose(settings, roles=["opener"], brief="test", dry_run=True)

    assert result.assemble_report is None
    # No pptx file in run dir
    pptx_files = list(result.run_dir.glob("*.pptx"))
    assert pptx_files == []


# --- compose --confirm (C3) ---

def test_compose_confirm_from_plan(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    # First do dry-run to generate plan
    from ppt_lib.composer import compose, compose_confirm
    dry_result = compose(settings, roles=["opener", "case"], brief="retail", dry_run=True)
    plan_path = dry_result.run_dir / "narrative-plan.json"
    assert plan_path.exists()

    # Now confirm — but we patch assemble since we don't have real pptx files
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport
    fake_report = AssembleReport(
        schema_version="1.0",
        run_id="test",
        status="completed",
        output_path=tmp_path / "output.pptx",
        slide_count=2,
        slides=[],
        errors=[],
        fidelity=AssembleFidelityReport(
            source_screenshots_dir="",
            output_screenshots_dir="",
            manual_review_required=False,
            warnings=[],
        ),
    )
    monkeypatch.setattr("ppt_lib.composer.run_assemble", lambda m: fake_report)
    monkeypatch.setattr(
        "ppt_lib.composer.select_slides",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("confirm must not reselect")),
    )

    confirm_result = compose_confirm(settings, plan_path=plan_path)
    assert confirm_result.dry_run is False
    assert confirm_result.assemble_report is not None
    assert confirm_result.assemble_report.status == "completed"
    assert confirm_result.run_dir == dry_result.run_dir
    assert confirm_result.manifest == dry_result.manifest
    assert [item.role for item in confirm_result.selection_report.roles] == ["opener", "case"]

    # D2: verify plan source is 'confirmed'
    plan_data = json.loads((confirm_result.run_dir / "narrative-plan.json").read_text())
    assert plan_data["source"] == "confirmed"


def test_compose_failed_assembly_does_not_record_usage(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))
    conn = connect(settings.db_path)
    deal_id = insert_deal(conn, deal_name="failed-compose", outcome="pending")
    conn.commit()
    conn.close()

    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport
    from ppt_lib.composer import compose

    monkeypatch.setattr(
        "ppt_lib.composer.run_assemble",
        lambda manifest: AssembleReport(
            schema_version="1.0",
            run_id="failed",
            status="failed",
            output_path=manifest.output_path,
            slide_count=0,
            slides=[],
            errors=["package_error: invalid pptx"],
            fidelity=AssembleFidelityReport("", "", True, []),
        ),
    )

    result = compose(
        settings,
        roles=["opener"],
        brief="retail",
        deal_id=deal_id,
    )

    assert result.assemble_report is not None
    assert result.assemble_report.status == "failed"
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM slide_usage").fetchone()[0] == 0
    conn.close()


def test_compose_records_only_slides_present_in_assembly_report(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))
    conn = connect(settings.db_path)
    deal_id = insert_deal(conn, deal_name="partial-compose", outcome="pending")
    conn.commit()
    opener_id = conn.execute("SELECT id FROM slides WHERE narrative_role = 'opener'").fetchone()[0]
    conn.close()

    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport, AssembleSlideReport
    from ppt_lib.composer import compose

    monkeypatch.setattr(
        "ppt_lib.composer.run_assemble",
        lambda manifest: AssembleReport(
            schema_version="1.0",
            run_id="partial",
            status="partial",
            output_path=manifest.output_path,
            slide_count=1,
            slides=[AssembleSlideReport(1, str(tmp_path / "opener_a.pptx"), 1, "copied", "low", [], opener_id)],
            errors=[],
            fidelity=AssembleFidelityReport("", "", True, []),
        ),
    )

    compose(settings, roles=["opener", "case"], brief="retail", deal_id=deal_id)

    conn = connect(settings.db_path)
    rows = conn.execute("SELECT slide_id, position FROM slide_usage ORDER BY position").fetchall()
    conn.close()
    assert rows == [(opener_id, 1)]


# --- compose gap detection ---

def test_compose_with_gaps(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    from ppt_lib.composer import compose
    result = compose(settings, roles=["opener", "roi"], brief="test", dry_run=True)

    assert "roi" in result.gaps
    assert (result.run_dir / "gaps.json").exists()
    gaps_data = json.loads((result.run_dir / "gaps.json").read_text())
    assert "roi" in gaps_data["gaps"]


# --- compose --verbose timings ---

def test_compose_verbose_writes_timing(tmp_path: Path, monkeypatch) -> None:
    _seed_db(tmp_path)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    from ppt_lib.composer import compose
    result = compose(settings, roles=["opener"], brief="test", dry_run=True, verbose=True)

    timing_file = result.run_dir / "compose-timing.json"
    assert timing_file.exists()
    timings = json.loads(timing_file.read_text())
    assert "select_slides_ms" in timings
    assert "total_ms" in timings


# --- CLI compose command ---

def test_cli_compose_dry_run(tmp_path: Path, monkeypatch, capsys) -> None:
    _seed_db(tmp_path)
    monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

    from ppt_lib.cli import main
    exit_code = main(["--home-dir", str(tmp_path), "compose", "--roles", "opener,case", "--brief", "retail", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["total_slides"] == 2


def test_cli_compose_brief_auto_reaches_composer(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main
    from ppt_lib.composer import ComposeResult, ComposeTimings
    from ppt_lib.selector import SelectionReport

    seen: dict[str, object] = {}

    def fake_compose(settings, **kwargs):
        seen.update(kwargs)
        return ComposeResult(
            run_id="run-1",
            run_dir=tmp_path / "composed" / "run-1",
            selection_report=SelectionReport(
                query="retail brief",
                options={},
                roles=[],
                total_slides=0,
                gaps=[],
                timestamp="2026-05-25T00:00:00+00:00",
            ),
            manifest={},
            assemble_report=None,
            gaps=[],
            timings=ComposeTimings(total_ms=1),
            dry_run=False,
        )

    monkeypatch.setattr("ppt_lib.composer.compose", fake_compose)

    exit_code = main(["--home-dir", str(tmp_path), "compose", "--brief", "retail brief", "--auto"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert seen["brief"] == "retail brief"
    assert seen["roles"] is None
    assert seen["dry_run"] is False
    assert payload["result"]["run_id"] == "run-1"


def test_cli_compose_defaults_to_reviewable_dry_run_without_auto(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main
    from ppt_lib.composer import ComposeResult, ComposeTimings
    from ppt_lib.selector import SelectionReport

    seen: dict[str, object] = {}

    def fake_compose(settings, **kwargs):
        seen.update(kwargs)
        return ComposeResult(
            run_id="run-preview",
            run_dir=tmp_path / "composed" / "run-preview",
            selection_report=SelectionReport("brief", {}, [], 0, [], "2026-07-13T00:00:00+00:00"),
            manifest={},
            assemble_report=None,
            gaps=[],
            timings=ComposeTimings(),
            dry_run=True,
        )

    monkeypatch.setattr("ppt_lib.composer.compose", fake_compose)

    exit_code = main(["--home-dir", str(tmp_path), "compose", "--brief", "retail brief"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert seen["dry_run"] is True
    assert payload["result"]["dry_run"] is True


def test_cli_compose_failed_assembly_exits_one(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.assembler import AssembleFidelityReport, AssembleReport
    from ppt_lib.cli import main
    from ppt_lib.composer import ComposeResult, ComposeTimings
    from ppt_lib.selector import SelectionReport

    monkeypatch.setattr(
        "ppt_lib.composer.compose",
        lambda settings, **kwargs: ComposeResult(
            run_id="run-failed",
            run_dir=tmp_path / "composed" / "run-failed",
            selection_report=SelectionReport("brief", {}, [], 0, [], "2026-07-13T00:00:00+00:00"),
            manifest={},
            assemble_report=AssembleReport(
                schema_version="1.0",
                run_id="assemble-failed",
                status="failed",
                output_path=tmp_path / "failed.pptx",
                slide_count=0,
                slides=[],
                errors=["package_error: invalid pptx"],
                fidelity=AssembleFidelityReport("", "", True, []),
            ),
            gaps=[],
            timings=ComposeTimings(),
        ),
    )

    exit_code = main(["--home-dir", str(tmp_path), "compose", "--brief", "retail", "--auto"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["result"]["assemble_status"] == "failed"
    assert payload["_errors"][0]["code"] == "COMPOSE_ASSEMBLE_FAILED"


def test_cli_compose_brief_dry_run_wins_over_auto(tmp_path: Path, monkeypatch, capsys) -> None:
    from ppt_lib.cli import main
    from ppt_lib.composer import ComposeResult, ComposeTimings
    from ppt_lib.selector import SelectionReport

    seen: dict[str, object] = {}

    def fake_compose(settings, **kwargs):
        seen.update(kwargs)
        return ComposeResult(
            run_id="run-2",
            run_dir=tmp_path / "composed" / "run-2",
            selection_report=SelectionReport(
                query="retail brief",
                options={},
                roles=[],
                total_slides=0,
                gaps=[],
                timestamp="2026-05-25T00:00:00+00:00",
            ),
            manifest={},
            assemble_report=None,
            gaps=[],
            timings=ComposeTimings(total_ms=1),
            dry_run=True,
        )

    monkeypatch.setattr("ppt_lib.composer.compose", fake_compose)

    exit_code = main(["--home-dir", str(tmp_path), "compose", "--brief", "retail brief", "--auto", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert seen["dry_run"] is True
    assert payload["result"]["dry_run"] is True
