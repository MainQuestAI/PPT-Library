from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.config import load_settings
from ppt_lib.db import connect, init_db, list_failed_jobs
from ppt_lib.embedding import FakeEmbeddingProvider
from ppt_lib.indexer import extract_pptx_text, index_batch, index_file, should_skip_file
from ppt_lib.screenshot import ScreenshotError, ScreenshotResult
from ppt_lib.vision import VisionResult


def make_pptx(path: Path, text: str = "Warehouse process") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    slide_xml = f"""
    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
           xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
    return path


def make_pptx_slides(path: Path, texts: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for index, text in enumerate(texts, start=1):
            slide_xml = f"""
            <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                   xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>
            """
            archive.writestr(f"ppt/slides/slide{index}.xml", slide_xml)
    return path


def patch_index_dependencies(monkeypatch: pytest.MonkeyPatch, screenshot_path: Path) -> None:
    screenshot_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + (2).to_bytes(4, "big")
        + (2).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(
        "ppt_lib.indexer.render_pptx_slides",
        lambda path, output_dir, max_workers=4: [
            ScreenshotResult(0, screenshot_path, "hash1", 2, 2, [])
        ],
    )
    monkeypatch.setattr(
        "ppt_lib.indexer.describe_slide_with_fallback",
        lambda image_path, fallback_text, settings: VisionResult(
            source="text_extraction",
            title="Slide title",
            text_content=fallback_text,
            metadata={"language": "en"},
            confidence=0.2,
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        "ppt_lib.indexer.build_embedding_provider",
        lambda settings: FakeEmbeddingProvider(),
    )


def test_index_single_pptx_roundtrip_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    result = index_file(pptx, settings)

    conn = sqlite3.connect(settings.db_path)
    assert result.status == "indexed"
    assert result.slides_indexed == 1
    assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 1
    assert conn.execute("SELECT text_content FROM slides").fetchone()[0] == "Warehouse process"
    metadata = conn.execute("SELECT metadata_json FROM slides").fetchone()[0]
    assert '"provider": "fake"' in metadata
    assert '"dimensions": 1536' in metadata
    assert conn.execute("SELECT COUNT(*) FROM asset_identity_map WHERE legacy_slide_id IS NOT NULL").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slide_assets").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slides_fts").fetchone()[0] == 1


def test_index_batch_scans_nested_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    make_pptx(tmp_path / "source" / "a" / "one.pptx", "one")
    make_pptx(tmp_path / "source" / "b" / "two.pptx", "two")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    results = index_batch(tmp_path / "source", settings)

    assert [result.status for result in results] == ["indexed", "indexed"]
    assert (settings.backups_dir).exists()


def test_index_file_auto_marks_text_duplicate_slides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    first = make_pptx(tmp_path / "source" / "first.pptx", "Content center architecture")
    second = make_pptx(tmp_path / "source" / "second.pptx", "Content center architecture")
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])
    monkeypatch.setattr("ppt_lib.indexer.build_embedding_provider", lambda settings: FakeEmbeddingProvider())

    first_result = index_file(first, settings)
    second_result = index_file(second, settings)

    conn = connect(settings.db_path)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT id, canonical_slide_id, text_hash
        FROM slides
        ORDER BY id
        """
    ).fetchall()
    duplicate_groups = conn.execute("SELECT canonical_slide_id FROM duplicate_groups").fetchall()
    members = conn.execute(
        """
        SELECT slide_id, canonical_slide_id, is_canonical
        FROM slide_duplicate_members
        ORDER BY slide_id
        """
    ).fetchall()

    assert first_result.status == "indexed"
    assert second_result.status == "indexed"
    assert len(rows) == 2
    assert rows[0][2] is not None
    assert rows[1][2] == rows[0][2]
    assert duplicate_groups == [(rows[0][0],)]
    assert rows[0][1] == rows[0][0]
    assert rows[1][1] == rows[0][0]
    assert members == [
        (rows[0][0], rows[0][0], 1),
        (rows[1][0], rows[0][0], 0),
    ]


def test_reindex_clears_stale_duplicate_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    first = make_pptx(tmp_path / "source" / "first.pptx", "Content center architecture")
    second = make_pptx(tmp_path / "source" / "second.pptx", "Content center architecture")
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])
    monkeypatch.setattr("ppt_lib.indexer.build_embedding_provider", lambda settings: FakeEmbeddingProvider())

    index_file(first, settings)
    index_file(second, settings)
    make_pptx(second, "")
    reindex_result = index_file(second, settings, full=True)

    conn = connect(settings.db_path)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT p.filename, s.canonical_slide_id, s.text_hash
        FROM slides s
        JOIN presentations p ON p.id = s.presentation_id
        ORDER BY p.filename
        """
    ).fetchall()

    assert reindex_result.status == "indexed"
    assert rows[0][1] is None
    assert rows[1][1] is None
    assert rows[1][2] is None
    assert conn.execute("SELECT COUNT(*) FROM duplicate_groups").fetchone()[0] == 0


def test_incremental_skips_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    first = index_file(pptx, settings)
    second = index_file(pptx, settings)

    assert first.status == "indexed"
    assert second.status == "skipped"


@pytest.mark.parametrize(
    "changed_settings",
    [
        {"embedding_provider": "openai"},
        {"embedding_model": "model-b"},
        {"embedding_dimensions": 8},
    ],
)
def test_incremental_reindexes_when_embedding_signature_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_settings: dict[str, object],
) -> None:
    home = tmp_path / "home"
    config_path = home / "config.yml"
    base_settings: dict[str, object] = {
        "home_dir": home,
        "embedding_provider": "fake",
        "embedding_model": "model-a",
        "embedding_dimensions": 4,
    }
    first_settings = load_settings(base_settings, config_path=config_path)
    second_settings = load_settings({**base_settings, **changed_settings}, config_path=config_path)
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    def build_configured_provider(settings):
        provider = FakeEmbeddingProvider(settings.embedding_dimensions)
        provider.model = settings.embedding_model
        return provider

    monkeypatch.setattr("ppt_lib.indexer.build_embedding_provider", build_configured_provider)

    first = index_file(pptx, first_settings)
    second = index_file(pptx, second_settings)

    assert first.status == "indexed"
    assert second.status == "indexed"
    conn = connect(second_settings.db_path)
    embedding_blob, metadata_json = conn.execute(
        "SELECT embedding, metadata_json FROM slides"
    ).fetchone()
    assert np.frombuffer(embedding_blob, dtype=np.float32).size == second_settings.embedding_dimensions
    assert json.loads(metadata_json)["embedding"] == {
        "provider": second_settings.embedding_provider,
        "model": second_settings.embedding_model,
        "dimensions": second_settings.embedding_dimensions,
    }


def test_full_reindexes_unchanged_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    first = index_file(pptx, settings)
    second = index_file(pptx, settings, full=True)

    assert first.status == "indexed"
    assert second.status == "indexed"


def test_incremental_reindexes_changed_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx", "old")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    index_file(pptx, settings)
    make_pptx(pptx, "new")
    second = index_file(pptx, settings)

    assert second.status == "indexed"

    conn = connect(settings.db_path)
    mappings = conn.execute(
        "SELECT slide_revision_id, legacy_slide_id FROM asset_identity_map ORDER BY updated_at"
    ).fetchall()
    assert len(mappings) == 2
    assert sum(1 for _revision, legacy_id in mappings if legacy_id is not None) == 1
    assert conn.execute("SELECT body_text FROM slides_fts").fetchone()[0] == "new"


def test_incremental_reindexes_changed_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx", "short")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    index_file(pptx, settings)
    make_pptx(pptx, "longer text content")
    second = index_file(pptx, settings)

    assert second.status == "indexed"


def test_missing_file_records_failed_job(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")

    result = index_file(tmp_path / "missing.pptx", settings)

    conn = connect(settings.db_path)
    init_db(conn)
    assert result.status == "failed"
    assert result.errors[0].code == "INDEX_FILE_NOT_FOUND"
    assert list_failed_jobs(conn)[0].file_path == tmp_path / "missing.pptx"


def test_corrupt_file_failed_job(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    bad = tmp_path / "source" / "bad.pptx"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a zip")

    result = index_file(bad, settings)

    conn = connect(settings.db_path)
    init_db(conn)
    assert result.status == "failed"
    assert list_failed_jobs(conn)[0].file_path == bad


def test_failed_reindex_does_not_leave_partial_new_slides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx_slides(tmp_path / "source" / "deck.pptx", ["old"])
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])

    first = index_file(pptx, settings)
    make_pptx_slides(pptx, ["new-one", "new-two"])

    class FailingOnSecondProvider(FakeEmbeddingProvider):
        def encode(self, text: str):
            if text == "new-two":
                raise RuntimeError("embedding down")
            return super().encode(text)

    monkeypatch.setattr("ppt_lib.indexer.build_embedding_provider", lambda settings: FailingOnSecondProvider())
    second = index_file(pptx, settings)

    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute("SELECT slide_index, text_content FROM slides ORDER BY slide_index").fetchall()
    assert first.status == "indexed"
    assert second.status == "failed"
    assert rows == [(0, "old")]


def test_reindex_removes_old_extra_slides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx_slides(tmp_path / "source" / "deck.pptx", ["one", "two"])
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])

    index_file(pptx, settings)
    make_pptx_slides(pptx, ["one"])
    second = index_file(pptx, settings)

    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute("SELECT slide_index, text_content FROM slides ORDER BY slide_index").fetchall()
    assert second.status == "indexed"
    assert rows == [(0, "one")]


def test_encrypted_like_office_file_failed_job(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    encrypted = tmp_path / "source" / "encrypted.pptx"
    encrypted.parent.mkdir(parents=True, exist_ok=True)
    encrypted.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

    result = index_file(encrypted, settings)

    assert result.status == "failed"
    assert result.errors[0].code == "INDEX_INVALID_PPTX"


def test_image_only_slide_indexed_with_screenshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "image-only.pptx", "")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    result = index_file(pptx, settings)

    assert result.status == "indexed"
    assert result.slides_indexed == 1


def test_missing_screenshot_uses_text_fallback_without_vision_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx", "fallback only")
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])
    monkeypatch.setattr(
        "ppt_lib.indexer.describe_slide_with_fallback",
        lambda image_path, fallback_text, settings: (_ for _ in ()).throw(RuntimeError("vision should not run")),
    )

    result = index_file(pptx, settings)

    assert result.status == "indexed"


def test_vision_max_slides_per_file_limits_model_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path / "home", "embedding_provider": "fake", "vision_max_slides_per_file": 1},
        config_path=tmp_path / "home" / "config.yml",
    )
    pptx = make_pptx_slides(tmp_path / "source" / "deck.pptx", ["first", "second"])
    screenshot = tmp_path / "slide.png"
    patch_index_dependencies(monkeypatch, screenshot)
    monkeypatch.setattr(
        "ppt_lib.indexer.render_pptx_slides",
        lambda path, output_dir, max_workers=4: [
            ScreenshotResult(0, screenshot, "hash1", 2, 2, []),
            ScreenshotResult(1, screenshot, "hash2", 2, 2, []),
        ],
    )
    calls: list[int] = []

    def describe(image_path, fallback_text, settings):
        calls.append(len(calls))
        return VisionResult(
            source="vision_model",
            title=None,
            text_content=fallback_text,
            metadata={},
            confidence=0.8,
            warnings=[],
        )

    monkeypatch.setattr("ppt_lib.indexer.describe_slide_with_fallback", describe)

    result = index_file(pptx, settings)

    assert result.status == "indexed"
    assert calls == [0]
    assert "VISION_SKIPPED_BY_LIMIT: 1 slides" in result.warnings


def test_partial_screenshot_warning_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    screenshot = tmp_path / "slide.png"
    patch_index_dependencies(monkeypatch, screenshot)
    monkeypatch.setattr(
        "ppt_lib.indexer.render_pptx_slides",
        lambda path, output_dir, max_workers=4: [
            ScreenshotResult(0, screenshot, "hash1", 2, 2, ["SCREENSHOT_RENDER_WARNING"])
        ],
    )

    result = index_file(pptx, settings)

    assert result.status == "indexed"
    assert "SCREENSHOT_RENDER_WARNING" in result.warnings


def test_screenshot_render_failure_warns_and_uses_text_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx", "text fallback")
    monkeypatch.setattr(
        "ppt_lib.indexer.render_pptx_slides",
        lambda path, output_dir, max_workers=4: (_ for _ in ()).throw(
            ScreenshotError("timeout", code="SCREENSHOT_RENDER_TIMEOUT")
        ),
    )

    result = index_file(pptx, settings)

    assert result.status == "indexed"
    assert result.warnings == ["SCREENSHOT_RENDER_TIMEOUT: timeout"]


def test_embedding_failure_records_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    pptx = make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    class FailingProvider:
        def encode(self, text: str):
            raise RuntimeError("embedding down")

    monkeypatch.setattr("ppt_lib.indexer.build_embedding_provider", lambda settings: FailingProvider())

    result = index_file(pptx, settings)

    assert result.status == "failed"
    assert result.errors[0].code == "INDEX_FAILED"
    assert "embedding down" in result.errors[0].message


def test_batch_continues_after_one_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    make_pptx(tmp_path / "source" / "good.pptx")
    bad = tmp_path / "source" / "bad.pptx"
    bad.write_bytes(b"not zip")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    results = index_batch(tmp_path / "source", settings)

    assert sorted(result.status for result in results) == ["failed", "indexed"]


def test_batch_triggers_backup_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings({"home_dir": tmp_path / "home", "embedding_provider": "fake"}, config_path=tmp_path / "home" / "config.yml")
    make_pptx(tmp_path / "source" / "deck.pptx")
    patch_index_dependencies(monkeypatch, tmp_path / "slide.png")

    index_batch(tmp_path / "source", settings)

    assert list(settings.backups_dir.glob("index-*.db"))


def test_extract_pptx_text_sorts_slide_numbers_numerically(tmp_path: Path) -> None:
    pptx = make_pptx_slides(tmp_path / "deck.pptx", [f"slide-{index}" for index in range(1, 11)])

    text_by_slide = extract_pptx_text(pptx)

    assert text_by_slide[1] == "slide-2"
    assert text_by_slide[9] == "slide-10"


def test_should_skip_file_requires_completed_job(tmp_path: Path) -> None:
    pptx = make_pptx(tmp_path / "deck.pptx")
    stat = pptx.stat()
    existing = {
        "file_size": stat.st_size,
        "file_mtime": stat.st_mtime,
        "content_hash": "wrong",
        "job_status": "completed",
    }

    assert should_skip_file(pptx, existing, full=False) is False
