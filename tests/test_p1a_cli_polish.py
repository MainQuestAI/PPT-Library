"""Tests for P1-A CLI polish features: compose summary, search narrative_role, status health."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.config import load_settings
from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide


class StaticProvider:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector.astype(np.float32)
        self.model = "static"
        self.dimensions = int(self.vector.shape[0])

    def encode(self, text: str) -> np.ndarray:
        return self.vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


def _seed_db(tmp_path: Path, *, with_deal: bool = False, with_usage: bool = False) -> None:
    """Create a minimal DB with slides, optionally deals and usage."""
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    roles = [("opener_a", "opener"), ("case_a", "case"), ("unannotated_a", None)]
    for title, role in roles:
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
        if role is not None:
            conn.execute("UPDATE slides SET narrative_role = ? WHERE id = ?", (role, slide_id))

    if with_deal:
        conn.execute(
            "INSERT INTO deals (deal_name, client_type, outcome) VALUES (?, ?, ?)",
            ("Test Deal", "enterprise", "won"),
        )
    if with_usage:
        # Insert a slide_usage record
        conn.execute(
            "INSERT INTO slide_usage (slide_id, deal_id, deck_presentation_id, position, is_original) VALUES (?, ?, ?, ?, ?)",
            (1, 1, 1, 1, 1),
        )
    conn.commit()
    conn.close()


# --- A1: compose() prints summary to stderr ---

class TestComposeSummary:
    def test_compose_prints_summary_to_stderr(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _seed_db(tmp_path)
        settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
        monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

        from ppt_lib.composer import compose
        compose(settings, roles=["opener", "case"], brief="retail", dry_run=True)

        stderr_output = capsys.readouterr().err
        assert "Compose Summary" in stderr_output
        assert "dry-run" in stderr_output
        assert "opener" in stderr_output
        assert "case" in stderr_output
        assert "Total slides:" in stderr_output
        assert "Timing:" in stderr_output

    def test_compose_summary_shows_gaps(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _seed_db(tmp_path)
        settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
        monkeypatch.setattr("ppt_lib.selector.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

        from ppt_lib.composer import compose
        compose(settings, roles=["opener", "roi"], brief="test", dry_run=True)

        stderr_output = capsys.readouterr().err
        assert "roi" in stderr_output
        assert "Gaps:" in stderr_output


# --- A2: search JSON output includes narrative_role ---

class TestSearchNarrativeRole:
    def test_search_result_includes_narrative_role(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _seed_db(tmp_path)
        monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

        from ppt_lib.cli import main
        exit_code = main(["--home-dir", str(tmp_path), "search", "opener retail", "--threshold", "0.0"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert exit_code == 0
        results = payload["results"]
        assert len(results) > 0
        # At least one result should have narrative_role
        roles_found = [r["narrative_role"] for r in results if r["narrative_role"] is not None]
        assert len(roles_found) > 0
        assert "opener" in roles_found or "case" in roles_found

    def test_search_result_narrative_role_key_present(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _seed_db(tmp_path)
        monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda s: StaticProvider(np.ones(1536)))

        from ppt_lib.cli import main
        exit_code = main(["--home-dir", str(tmp_path), "search", "retail", "--threshold", "0.0"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert exit_code == 0
        for result in payload["results"]:
            assert "narrative_role" in result


# --- A3: status command shows health info ---

class TestStatusHealth:
    def test_status_health_fields(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _seed_db(tmp_path, with_deal=True, with_usage=True)

        from ppt_lib.cli import main
        exit_code = main(["--home-dir", str(tmp_path), "status"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert exit_code == 0
        assert "health" in payload
        health = payload["health"]
        assert health["total_slides"] == 3
        assert health["annotated_count"] == 2  # opener and case annotated, one NULL
        assert health["annotated_pct"] == pytest.approx(66.7, abs=0.1)
        assert health["deals_count"] == 1
        assert health["slide_usage_count"] == 1

    def test_status_health_empty_db(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """Status works on an empty library without errors."""
        settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
        conn = connect(settings.db_path)
        init_db(conn)
        conn.close()

        from ppt_lib.cli import main
        exit_code = main(["--home-dir", str(tmp_path), "status"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert exit_code == 0
        health = payload["health"]
        assert health["total_slides"] == 0
        assert health["annotated_count"] == 0
        assert health["annotated_pct"] == 0.0
        assert health["deals_count"] == 0
        assert health["slide_usage_count"] == 0
