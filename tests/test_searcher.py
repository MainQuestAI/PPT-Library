from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.clustering import cluster_results
from ppt_lib.config import load_settings
from ppt_lib.db import (
    PresentationRecord,
    SlideRecord,
    connect,
    init_db,
    upsert_duplicate_group,
    upsert_duplicate_member,
    upsert_presentation,
    upsert_slide,
)
from ppt_lib.searcher import (
    SearchError,
    SearchOptions,
    _hybrid_score,
    _row_to_result,
    cosine_scores,
    get_search_index_stats,
    load_search_rows,
    search,
)
from ppt_lib.versioning import recompute_deck_versions


class StaticProvider:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector.astype(np.float32)
        self.model = "static"
        self.dimensions = int(self.vector.shape[0])

    def encode(self, text: str) -> np.ndarray:
        return self.vector

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


def seed_slide(tmp_path: Path, title: str, vector: np.ndarray, slide_index: int = 0) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    presentation_id = upsert_presentation(
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
    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=slide_index,
            title=title,
            text_content=f"{title} summary text",
            embedding=vector.astype(np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={"language": "en", "confidence": 0.5},
        ),
    )


def test_cosine_scores_known_vectors() -> None:
    matrix = np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)

    scores = cosine_scores(matrix, query)

    np.testing.assert_allclose(scores, np.array([1.0, 0.0, 0.70710677], dtype=np.float32))


def test_search_empty_library_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    assert search("query", SearchOptions(), settings) == []


def test_search_returns_top_k_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "best", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "second", np.r_[0.8, 0.2, np.zeros(1534)])
    seed_slide(tmp_path, "third", np.r_[0.1, 1.0, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=2, threshold=0.0), settings)

    assert [result.title for result in results] == ["best", "second"]
    assert results[0].score >= results[1].score


def test_search_boosts_exact_text_matches_over_close_semantic_neighbors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "generic", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "business", np.r_[0.95, 0.05, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    conn.execute("UPDATE slides SET text_content = ? WHERE title = ?", ("generic operations summary", "generic"))
    conn.execute("UPDATE slides SET text_content = ? WHERE title = ?", ("客户经营 数字化转型 DATSS 模型", "business"))
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("客户经营 数字化转型", SearchOptions(top_k=2, threshold=0.0), settings)

    assert [result.title for result in results] == ["business", "generic"]


def test_search_demotes_high_semantic_rows_without_business_term_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unit_vector(cosine: float) -> np.ndarray:
        return np.r_[cosine, np.sqrt(1 - cosine**2), np.zeros(1534)]

    seed_slide(tmp_path, "generic", unit_vector(0.95))
    seed_slide(tmp_path, "business", unit_vector(0.80))
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    conn.execute("UPDATE slides SET text_content = ? WHERE title = ?", ("general customer operations overview", "generic"))
    conn.execute("UPDATE slides SET text_content = ? WHERE title = ?", ("运营效率 人效分析 dashboard", "business"))
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("运营效率看板 人效分析与流程优化指标", SearchOptions(top_k=2, threshold=0.0), settings)

    assert [result.title for result in results] == ["business", "generic"]


def test_hybrid_score_penalizes_low_overlap_and_clamps() -> None:
    assert _hybrid_score(0.66, 0.0) == pytest.approx(0.342)
    assert _hybrid_score(0.66, 0.04) == pytest.approx(0.414)
    assert _hybrid_score(0.90, 0.30) == pytest.approx(0.72)


def test_search_score_does_not_saturate_for_keyword_heavy_partial_match() -> None:
    score = _hybrid_score(0.72, 0.90)

    assert score == pytest.approx(0.774)
    assert score < 1.0


def test_search_does_not_match_short_latin_terms_as_substrings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "Retail chain operations", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "AI architecture platform", np.r_[0.95, 0.05, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("AI", SearchOptions(top_k=2, threshold=0.0), settings)

    assert [result.title for result in results] == ["AI architecture platform", "Retail chain operations"]


def test_threshold_filters_semantic_score_before_lexical_rerank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "AI architecture platform", np.r_[0.0, 1.0, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("AI architecture", SearchOptions(top_k=1, threshold=0.5), settings)

    assert results == []


def test_threshold_filters_final_hybrid_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cosine = 0.66
    seed_slide(tmp_path, "semantic-only", np.r_[cosine, np.sqrt(1 - cosine**2), np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    conn.execute("UPDATE slides SET text_content = ? WHERE title = ?", ("general operations summary", "semantic-only"))
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("人效分析 流程优化", SearchOptions(top_k=1, threshold=0.65), settings)

    assert results == []


def test_threshold_filters_low_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "low", np.r_[0.0, 1.0, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=5, threshold=0.5), settings)

    assert results == []


def test_empty_query_raises_search_error(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    with pytest.raises(SearchError) as exc:
        search("   ", SearchOptions(), settings)

    assert exc.value.code == "SEARCH_EMPTY_QUERY"


def test_json_result_has_agent_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "agent", np.r_[1.0, np.zeros(1535)], slide_index=6)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    result = search("query", SearchOptions(), settings)[0]

    assert result.slide_id > 0
    assert result.source_file == tmp_path / "agent.pptx"
    assert result.page_number == 7
    assert result.screenshot_path is None
    assert result.source == "text_extraction"
    assert result.metadata["language"] == "en"
    assert result.confidence == 0.5


def test_search_uses_configured_embedding_dimensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "fake", "embedding_dimensions": 768},
        config_path=tmp_path / "config.yml",
    )
    conn = connect(settings.db_path)
    init_db(conn)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "local.pptx",
            filename="local.pptx",
            project_name="project",
            slide_count=1,
            content_hash="local",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="local",
            text_content="local embedding summary",
            embedding=np.r_[1.0, np.zeros(767)].astype(np.float32),
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(767)]))

    results = search("query", SearchOptions(top_k=1, threshold=0.0), settings)

    assert [result.title for result in results] == ["local"]


def test_search_reports_when_all_embeddings_have_wrong_dimensions(tmp_path: Path) -> None:
    seed_slide(tmp_path, "wrong-dim", np.ones(1536, dtype=np.float32))
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "fake", "embedding_dimensions": 768},
        config_path=tmp_path / "config.yml",
    )

    with pytest.raises(SearchError) as exc:
        search("query", SearchOptions(top_k=1, threshold=0.0), settings)

    assert exc.value.code == "SEARCH_EMBEDDING_DIMENSION_MISMATCH"
    assert "768" in str(exc.value)


def test_search_uses_matching_rows_when_index_has_mixed_dimensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "fake", "embedding_dimensions": 768},
        config_path=tmp_path / "config.yml",
    )
    conn = connect(settings.db_path)
    init_db(conn)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "mixed.pptx",
            filename="mixed.pptx",
            project_name="project",
            slide_count=2,
            content_hash="mixed-search",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    for slide_index, (title, vector) in enumerate([("matching", np.r_[1.0, np.zeros(767)]), ("wrong", np.ones(1536))]):
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=slide_index,
                title=title,
                text_content=f"{title} dimensions",
                embedding=vector.astype(np.float32),
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(767)]))

    results = search("query", SearchOptions(top_k=2, threshold=0.0), settings)

    assert [result.title for result in results] == ["matching"]


def test_search_excludes_assembled_output_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "original", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "assembled", np.r_[1.0, np.zeros(1535)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute("UPDATE slides SET origin_type = 'assembled_output' WHERE title = 'assembled'")
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=5, threshold=0.0), settings)

    assert [result.title for result in results] == ["original"]


def test_search_prefers_readable_ai_or_visual_summary_over_raw_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "Untitled", np.r_[1.0, np.zeros(1535)], slide_index=0)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute(
        """
        UPDATE slides
        SET title = 'Untitled',
            text_content = 'legacy body summary',
            raw_text = 'RAW_TEXT should be lower priority',
            ai_summary = 'AI summary is concise and readable.',
            visual_summary = 'visual summary should rank below AI summary'
        WHERE title = 'Untitled'
        """,
    )
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=1, threshold=0.0), settings)

    assert results[0].title == "Untitled · P1"
    assert results[0].text_summary == "AI summary is concise and readable."


def test_search_hides_duplicate_rows_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "canonical", np.r_[1.0, np.zeros(1535)], slide_index=0)
    seed_slide(tmp_path, "duplicate", np.r_[1.0, np.zeros(1535)], slide_index=1)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    canonical_id = conn.execute("SELECT id FROM slides WHERE title = 'canonical'").fetchone()[0]
    conn.execute("UPDATE slides SET canonical_slide_id = ? WHERE title = 'duplicate'", (canonical_id,))
    conn.execute("UPDATE slides SET canonical_slide_id = ? WHERE title = 'canonical'", (canonical_id,))
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=10, threshold=0.0), settings)
    all_results = search("query", SearchOptions(top_k=10, threshold=0.0, include_duplicates=True), settings)

    assert [result.title for result in results] == ["canonical"]
    assert [result.title for result in all_results] == ["canonical", "duplicate"]
    assert results[0].duplicate_count == 2
    assert results[0].canonical_slide_id == canonical_id


def test_search_hides_non_representative_versions_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "星河商学院数字化方案_v1", np.r_[1.0, np.zeros(1535)], slide_index=0)
    seed_slide(tmp_path, "星河商学院数字化方案_终稿", np.r_[1.0, np.zeros(1535)], slide_index=1)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    recompute_deck_versions(conn)
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    default_results = search("数字化方案", SearchOptions(top_k=10, threshold=0.0), settings)
    all_results = search("数字化方案", SearchOptions(top_k=10, threshold=0.0, include_versions=True), settings)

    assert [result.title for result in default_results] == ["星河商学院数字化方案_终稿"]
    assert {result.title for result in all_results} == {"星河商学院数字化方案_v1", "星河商学院数字化方案_终稿"}
    assert default_results[0].version_role == "final"
    assert default_results[0].is_representative_version is True
    assert default_results[0].family_duplicate_count == 2


def test_duplicate_count_includes_canonical_when_member_table_omits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_slide(tmp_path, "canonical", np.r_[1.0, np.zeros(1535)], slide_index=0)
    seed_slide(tmp_path, "duplicate", np.r_[1.0, np.zeros(1535)], slide_index=1)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    canonical_id = int(conn.execute("SELECT id FROM slides WHERE title = 'canonical'").fetchone()[0])
    duplicate_id = int(conn.execute("SELECT id FROM slides WHERE title = 'duplicate'").fetchone()[0])
    group_id = upsert_duplicate_group(conn, canonical_slide_id=canonical_id)
    upsert_duplicate_member(conn, duplicate_group_id=group_id, slide_id=duplicate_id)
    conn.close()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=10, threshold=0.0), settings)

    assert [result.title for result in results] == ["canonical"]
    assert results[0].duplicate_count == 2


def test_duplicate_count_does_not_double_count_canonical_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_slide(tmp_path, "canonical", np.r_[1.0, np.zeros(1535)], slide_index=0)
    seed_slide(tmp_path, "duplicate", np.r_[1.0, np.zeros(1535)], slide_index=1)
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    canonical_id = int(conn.execute("SELECT id FROM slides WHERE title = 'canonical'").fetchone()[0])
    duplicate_id = int(conn.execute("SELECT id FROM slides WHERE title = 'duplicate'").fetchone()[0])
    group_id = upsert_duplicate_group(conn, canonical_slide_id=canonical_id)
    upsert_duplicate_member(conn, duplicate_group_id=group_id, slide_id=canonical_id, is_canonical=True)
    upsert_duplicate_member(conn, duplicate_group_id=group_id, slide_id=duplicate_id)
    conn.close()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=10, threshold=0.0), settings)

    assert [result.title for result in results] == ["canonical"]
    assert results[0].duplicate_count == 2


def test_load_search_rows_handles_legacy_slide_schema_without_optional_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE presentations (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            filename TEXT NOT NULL,
            project_name TEXT,
            slide_count INTEGER,
            content_hash TEXT,
            file_size INTEGER,
            file_mtime REAL,
            indexed_at TEXT,
            last_validated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER NOT NULL,
            slide_index INTEGER NOT NULL,
            title TEXT,
            text_content TEXT,
            embedding BLOB,
            screenshot_hash TEXT,
            source TEXT NOT NULL,
            extraction_warnings TEXT,
            metadata_json TEXT,
            industry TEXT,
            scenario TEXT,
            narrative_role TEXT,
            win_rate REAL,
            won_count INTEGER,
            lost_count INTEGER,
            reuse_count INTEGER,
            last_deal_outcome TEXT,
            origin_type TEXT
        )
        """
    )
    vector = np.r_[1.0, np.zeros(1535)].astype(np.float32).tobytes()
    conn.execute(
        """
        INSERT INTO presentations (id, path, filename, project_name, slide_count, content_hash, file_size, file_mtime)
        VALUES (1, ?, ?, ?, 1, 'legacy', 1, 1.0)
        """,
        (str(tmp_path / "legacy.pptx"), "legacy.pptx", "legacy"),
    )
    conn.execute(
        """
        INSERT INTO slides (
            id, presentation_id, slide_index, title, text_content, embedding, screenshot_hash,
            source, extraction_warnings, metadata_json, industry, scenario, narrative_role, win_rate, won_count, lost_count,
            reuse_count, last_deal_outcome, origin_type
        ) VALUES (
            1, 1, 0, 'legacy', 'legacy text content', ?, NULL,
            'text_extraction', '[]', '{}', NULL, NULL, NULL, NULL, 0, 0, 0, NULL, 'original'
        )
        """,
        (vector,),
    )
    conn.commit()

    rows = load_search_rows(conn, 1536, include_assembled=False, dedupe_lineage=False)
    result = _row_to_result(rows[0], 0.9, score_breakdown=None)

    assert len(rows) == 1
    assert result.text_summary == "legacy text content"
    assert result.canonical_slide_id is None

    rows_with_duplicates = load_search_rows(conn, 1536, include_assembled=False, dedupe_lineage=False, include_duplicates=True)
    assert len(rows_with_duplicates) == 1


def test_search_includes_assembled_output_when_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "original", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "assembled", np.r_[1.0, np.zeros(1535)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute("UPDATE slides SET origin_type = 'assembled_output' WHERE title = 'assembled'")
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(top_k=5, threshold=0.0, include_assembled=True), settings)

    assert {result.title for result in results} == {"original", "assembled"}
    assert {result.metadata["origin_type"] for result in results} == {"original", "assembled_output"}


def test_search_excludes_cache_paths_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    for title, path in [
        ("curated", tmp_path / "curated" / "deck.pptx"),
        ("cached", Path("/Users/test/Downloads/WXWork Files/Caches/WXWork Files/Caches/Files/deck.pptx")),
    ]:
        presentation_id = upsert_presentation(
            conn,
            PresentationRecord(
                path=path,
                filename=path.name,
                project_name="project",
                slide_count=1,
                content_hash=title,
                file_size=100,
                file_mtime=1.0,
            ),
        )
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=0,
                title=title,
                text_content=f"{title} 内容中心 技术架构",
                embedding=np.r_[1.0, np.zeros(1535)].astype(np.float32),
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    default_results = search("内容中心 技术架构", SearchOptions(top_k=5, threshold=0.0), settings)
    included_results = search("内容中心 技术架构", SearchOptions(top_k=5, threshold=0.0, include_cache=True), settings)

    assert [result.title for result in default_results] == ["curated"]
    assert {result.title for result in included_results} == {"curated", "cached"}


def test_search_dedupe_lineage_keeps_original_representative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "original", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "assembled", np.r_[1.0, np.zeros(1535)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    source_id = conn.execute("SELECT id FROM slides WHERE title = 'original'").fetchone()[0]
    derived_id = conn.execute("SELECT id FROM slides WHERE title = 'assembled'").fetchone()[0]
    conn.execute("UPDATE slides SET origin_type = 'assembled_output' WHERE id = ?", (derived_id,))
    conn.execute(
        """
        INSERT INTO assemble_runs (run_name, slide_count, created_at, status)
        VALUES (?, ?, ?, ?)
        """,
        ("run", 1, "2026-05-25T00:00:00+00:00", "completed"),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO slide_lineage (derived_slide_id, source_slide_id, assemble_run_id, derivation_type, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (derived_id, source_id, run_id, "copied", "2026-05-25T00:00:00+00:00"),
    )
    conn.commit()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search(
        "query",
        SearchOptions(top_k=5, threshold=0.0, include_assembled=True, dedupe_lineage=True),
        settings,
    )

    assert [result.title for result in results] == ["original"]


def _set_business_fields(
    settings,
    title: str,
    *,
    win_rate: float,
    won_count: int = 5,
    lost_count: int = 0,
    reuse_count: int = 5,
    last_deal_outcome: str | None = "won",
) -> None:
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute(
        """
        UPDATE slides
        SET win_rate = ?, won_count = ?, lost_count = ?, reuse_count = ?, last_deal_outcome = ?
        WHERE title = ?
        """,
        (win_rate, won_count, lost_count, reuse_count, last_deal_outcome, title),
    )
    conn.commit()
    conn.close()


def _set_narrative_role(settings, title: str, role: str) -> None:
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute("UPDATE slides SET narrative_role = ? WHERE title = ?", (role, title))
    conn.commit()
    conn.close()


def test_business_ranking_boosts_high_win_rate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "high_win", np.r_[0.85, 0.15, np.zeros(1534)])
    seed_slide(tmp_path, "low_win", np.r_[0.90, 0.10, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    _set_business_fields(settings, "high_win", win_rate=1.0, won_count=10, reuse_count=20)
    _set_business_fields(settings, "low_win", win_rate=0.0, won_count=5, lost_count=5, reuse_count=10)
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    classic = search("test", SearchOptions(top_k=2, threshold=0.0, ranking="classic"), settings)
    business = search("test", SearchOptions(top_k=2, threshold=0.0, ranking="business"), settings)

    assert [result.title for result in classic] == ["low_win", "high_win"]
    assert [result.title for result in business] == ["high_win", "low_win"]
    assert business[0].score_breakdown is not None
    assert business[0].score_breakdown["business_score"] is not None


def test_business_ranking_without_deals_keeps_classic_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "a", np.r_[0.70, 0.30, np.zeros(1534)])
    seed_slide(tmp_path, "b", np.r_[0.80, 0.20, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    classic = search("test", SearchOptions(top_k=2, threshold=0.0, ranking="classic"), settings)
    business = search("test", SearchOptions(top_k=2, threshold=0.0, ranking="business"), settings)

    assert [result.title for result in business] == [result.title for result in classic]
    assert all(result.score_breakdown is not None for result in business)
    assert all(result.score_breakdown["business_score"] is None for result in business if result.score_breakdown)


def test_business_score_uses_confidence_decay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "high_win_low_use", np.r_[0.85, 0.15, np.zeros(1534)])
    seed_slide(tmp_path, "moderate_moderate", np.r_[0.82, 0.18, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    _set_business_fields(settings, "high_win_low_use", win_rate=1.0, won_count=1, reuse_count=1)
    _set_business_fields(settings, "moderate_moderate", win_rate=0.6, won_count=3, lost_count=2, reuse_count=5)
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    business = search("test", SearchOptions(top_k=2, threshold=0.0, ranking="business"), settings)

    assert [result.title for result in business] == ["moderate_moderate", "high_win_low_use"]


def test_narrative_role_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "opener_slide", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "solution_slide", np.r_[0.95, 0.05, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    _set_narrative_role(settings, "opener_slide", "opener")
    _set_narrative_role(settings, "solution_slide", "solution")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("slide", SearchOptions(top_k=5, threshold=0.0, narrative_role="opener"), settings)

    assert [result.title for result in results] == ["opener_slide"]


def test_narrative_role_filter_respects_include_assembled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "orig_opener", np.ones(1536, dtype=np.float32))
    seed_slide(tmp_path, "assembled_opener", np.ones(1536, dtype=np.float32))
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    conn = connect(settings.db_path)
    init_db(conn)
    conn.execute("UPDATE slides SET origin_type = 'assembled_output', narrative_role = 'opener' WHERE title = 'assembled_opener'")
    conn.execute("UPDATE slides SET narrative_role = 'opener' WHERE title = 'orig_opener'")
    conn.commit()
    conn.close()
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.ones(1536)))

    default_results = search("opener", SearchOptions(top_k=5, threshold=0.0, narrative_role="opener"), settings)
    included_results = search(
        "opener",
        SearchOptions(top_k=5, threshold=0.0, narrative_role="opener", include_assembled=True),
        settings,
    )

    assert [result.title for result in default_results] == ["orig_opener"]
    assert {result.title for result in included_results} == {"orig_opener", "assembled_opener"}


def test_search_index_stats_reports_skipped_embedding_dimensions(tmp_path: Path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "fake", "embedding_dimensions": 768},
        config_path=tmp_path / "config.yml",
    )
    conn = connect(settings.db_path)
    init_db(conn)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "mixed.pptx",
            filename="mixed.pptx",
            project_name="project",
            slide_count=2,
            content_hash="mixed",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    for slide_index, vector in enumerate([np.ones(768, dtype=np.float32), np.ones(1536, dtype=np.float32)]):
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=slide_index,
                title=f"slide-{slide_index}",
                text_content="mixed dimensions",
                embedding=vector,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )

    stats = get_search_index_stats(settings)

    assert stats.configured_dimensions == 768
    assert stats.total_embeddings == 2
    assert stats.searchable_embeddings == 1
    assert stats.skipped_embeddings == 1
    assert stats.dimension_counts == {768: 1, 1536: 1}


def test_cluster_single_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "only", np.r_[1.0, np.zeros(1535)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = search("query", SearchOptions(cluster=True), settings)

    assert results[0].cluster_id == 0


def test_cluster_distinct_groups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_slide(tmp_path, "a", np.r_[1.0, np.zeros(1535)])
    seed_slide(tmp_path, "b", np.r_[0.0, 1.0, np.zeros(1534)])
    settings = load_settings({"home_dir": tmp_path, "embedding_provider": "fake"}, config_path=tmp_path / "config.yml")
    monkeypatch.setattr("ppt_lib.searcher.build_embedding_provider", lambda settings: StaticProvider(np.r_[1.0, np.zeros(1535)]))

    results = cluster_results(search("query", SearchOptions(top_k=2, threshold=0.0), settings), threshold=0.01)

    assert len({result.cluster_id for result in results}) == 2
