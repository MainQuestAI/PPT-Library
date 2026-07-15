from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

import numpy as np

from ppt_lib.asset_schema import SlideRevision, insert_slide_revision, upsert_slide_asset
from ppt_lib.assets import content_hash as asset_content_hash
from ppt_lib.assets import normalize_text, normalized_text_hash
from ppt_lib.config import ensure_dirs
from ppt_lib.db import (
    PresentationRecord,
    ScreenshotRecord,
    SlideRecord,
    backup_db,
    connect,
    create_or_update_job,
    init_db,
    insert_screenshot,
    mark_job_completed,
    mark_job_failed,
    replace_presentation_slides,
    sync_presentation_source_links,
    upsert_duplicate_group,
    upsert_duplicate_member,
    upsert_presentation,
)
from ppt_lib.discovery import scan_presentations
from ppt_lib.embedding import EmbeddingProvider, build_embedding_provider
from ppt_lib.fts_search import index_from_slides
from ppt_lib.identity import FINGERPRINT_VERSION, compute_slide_revision_id, upsert_identity_mapping
from ppt_lib.screenshot import ScreenshotError, render_pptx_slides
from ppt_lib.settings import Settings
from ppt_lib.versioning import recompute_deck_versions
from ppt_lib.vision import TextExtractionVisionProvider, describe_slide_with_fallback

IndexStatus = Literal["indexed", "skipped", "failed"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ErrorRecord:
    code: str
    message: str
    source_module: str
    severity: str = "error"


@dataclass(frozen=True)
class IndexResult:
    file_path: Path
    status: IndexStatus
    slides_indexed: int
    warnings: list[str]
    errors: list[ErrorRecord]


@dataclass(frozen=True)
class _PendingSlide:
    slide_index: int
    title: str | None
    text_content: str
    embedding: np.ndarray | None
    screenshot_hash: str | None
    source: str
    extraction_warnings: list[str]
    metadata_json: dict[str, object]


def index_file(path: Path, settings: Settings, *, full: bool = False, refresh_versions: bool = True) -> IndexResult:
    ensure_dirs(settings)
    path = _normalize_path(path)
    assert settings.db_path is not None
    assert settings.screenshots_dir is not None
    conn = connect(settings.db_path)
    init_db(conn)
    job_id: int | None = None

    try:
        if not path.exists():
            job_id = create_or_update_job(conn, path, "processing")
            raise FileNotFoundError(path)
        text_by_slide = extract_pptx_text(path)
        provider = build_embedding_provider(settings)
        embedding_signature = _embedding_signature(settings, provider)
        existing = _existing_state(conn, path)
        if should_skip_file(path, existing, full=full, embedding_signature=embedding_signature):
            job_id = create_or_update_job(conn, path, "completed")
            mark_job_completed(conn, job_id)
            return IndexResult(path, "skipped", 0, [], [])

        job_id = create_or_update_job(conn, path, "processing")
        file_hash = content_hash(path)
        warnings: list[str] = []
        try:
            screenshots = render_pptx_slides(path, settings.screenshots_dir, max_workers=settings.max_workers)
        except ScreenshotError as exc:
            if exc.code in {"SCREENSHOT_RENDERER_MISSING", "SCREENSHOT_INPUT_NOT_FOUND"}:
                raise
            warnings.append(f"{exc.code}: {exc}")
            screenshots = []
        screenshot_by_index = {item.slide_index: item for item in screenshots}
        total = max(len(text_by_slide), len(screenshots))
        pending_slides: list[_PendingSlide] = []
        pending_screenshots: list[ScreenshotRecord] = []
        vision_skipped_count = 0
        for slide_index in range(total):
            fallback_text = text_by_slide.get(slide_index, "")
            screenshot = screenshot_by_index.get(slide_index)
            vision_skipped_by_limit = False
            if screenshot and _should_use_vision(slide_index, settings):
                vision = describe_slide_with_fallback(screenshot.png_path, fallback_text, settings)
            elif screenshot:
                vision_skipped_by_limit = True
                vision_skipped_count += 1
                vision = TextExtractionVisionProvider().describe_slide(path, fallback_text)
            else:
                vision = TextExtractionVisionProvider().describe_slide(path, fallback_text)
            warnings.extend(vision.warnings)
            if screenshot:
                warnings.extend(screenshot.warnings)
                pending_screenshots.append(
                    ScreenshotRecord(
                        hash=screenshot.sha256,
                        file_path=screenshot.png_path,
                        width=screenshot.width,
                        height=screenshot.height,
                    ),
                )
            pending_slides.append(
                _PendingSlide(
                    slide_index=slide_index,
                    title=vision.title,
                    text_content=vision.text_content,
                    embedding=provider.encode(vision.text_content),
                    screenshot_hash=screenshot.sha256 if screenshot else None,
                    source=vision.source,
                    extraction_warnings=(
                        vision.warnings
                        + (["VISION_SKIPPED_BY_LIMIT"] if vision_skipped_by_limit else [])
                        + (screenshot.warnings if screenshot else [])
                    ),
                    metadata_json=_metadata_with_embedding(vision.metadata, embedding_signature),
                )
            )
        if vision_skipped_count:
            warnings.append(f"VISION_SKIPPED_BY_LIMIT: {vision_skipped_count} slides")

        try:
            conn.execute("BEGIN")
            presentation_id = upsert_presentation(
                conn,
                PresentationRecord(
                    path=path,
                    filename=path.name,
                    project_name=path.parent.name if path.parent else None,
                    slide_count=total,
                    content_hash=file_hash,
                    file_size=path.stat().st_size,
                    file_mtime=path.stat().st_mtime,
                ),
                commit=False,
            )
            sync_presentation_source_links(conn, presentation_id, path, commit=False)
            for screenshot_record in pending_screenshots:
                insert_screenshot(conn, screenshot_record, commit=False)
            replace_presentation_slides(
                conn,
                presentation_id,
                [
                    SlideRecord(
                        presentation_id=presentation_id,
                        slide_index=slide.slide_index,
                        title=slide.title,
                        text_content=slide.text_content,
                        embedding=slide.embedding,
                        screenshot_hash=slide.screenshot_hash,
                        source=slide.source,
                        extraction_warnings=slide.extraction_warnings,
                        metadata_json=slide.metadata_json,
                    )
                    for slide in pending_slides
                ],
                commit=False,
            )
            _refresh_duplicate_groups(conn, presentation_id)
            _sync_slide_identities(conn, path, presentation_id)
            current_slide_ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM slides WHERE presentation_id = ? ORDER BY slide_index",
                    (presentation_id,),
                ).fetchall()
            ]
            index_from_slides(conn, slide_ids=current_slide_ids, commit=False)
            if refresh_versions:
                recompute_deck_versions(conn, dry_run=False, commit=False)
            mark_job_completed(conn, job_id, commit=False)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return IndexResult(path, "indexed", len(pending_slides), warnings, [])
    except Exception as exc:
        conn.rollback()
        if job_id is None:
            job_id = create_or_update_job(conn, path, "processing")
        mark_job_failed(conn, job_id, str(exc))
        return IndexResult(
            path,
            "failed",
            0,
            [],
            [ErrorRecord(code=_error_code(exc), message=str(exc), source_module="indexer")],
        )


def index_batch(root: Path, settings: Settings, full: bool = False) -> list[IndexResult]:
    ensure_dirs(settings)
    assert settings.db_path is not None
    assert settings.backups_dir is not None
    items = scan_presentations(_normalize_path(root), settings)
    results = [index_file(item.path, settings, full=full, refresh_versions=False) for item in items]
    conn = connect(settings.db_path)
    init_db(conn)
    recompute_deck_versions(conn, dry_run=False)
    backup_db(conn, settings.backups_dir)
    return results


def should_skip_file(
    path: Path,
    existing: dict[str, object] | None,
    full: bool,
    *,
    embedding_signature: tuple[str, str, int] | None = None,
) -> bool:
    if full or not existing or not path.exists():
        return False
    stat = path.stat()
    embedding_matches = embedding_signature is None or (
        existing.get("embedding_metadata_complete") is True
        and existing.get("embedding_signatures") == (embedding_signature,)
    )
    return (
        existing.get("file_size") == stat.st_size
        and existing.get("file_mtime") == stat.st_mtime
        and existing.get("content_hash") == content_hash(path)
        and existing.get("job_status") == "completed"
        and embedding_matches
    )


def _refresh_duplicate_groups(conn, presentation_id: int) -> None:
    for slide_id, text_content in conn.execute(
        "SELECT id, text_content FROM slides WHERE presentation_id = ?",
        (presentation_id,),
    ).fetchall():
        text = str(text_content or "")
        normalized = normalize_text(text)
        conn.execute(
            """
            UPDATE slides
            SET raw_text = ?,
                text_hash = ?,
                content_hash = ?
            WHERE id = ?
            """,
            (
                text,
                normalized_text_hash(text) if normalized else None,
                asset_content_hash(text) if normalized else None,
                int(slide_id),
            ),
        )

    conn.execute("DELETE FROM slide_duplicate_members")
    conn.execute("DELETE FROM duplicate_groups")
    conn.execute("UPDATE slides SET canonical_slide_id = NULL")

    rows = conn.execute(
        """
        SELECT id, screenshot_hash, text_hash
        FROM slides
        ORDER BY id
        """
    ).fetchall()
    duplicate_components = _duplicate_components(
        [(int(row[0]), row[1], row[2]) for row in rows]
    )
    for component in duplicate_components:
        canonical_id = min(component)
        group_id = upsert_duplicate_group(conn, canonical_slide_id=canonical_id, commit=False)
        upsert_duplicate_member(
            conn,
            duplicate_group_id=group_id,
            slide_id=canonical_id,
            is_canonical=True,
            commit=False,
        )
        for slide_id in sorted(item for item in component if item != canonical_id):
            upsert_duplicate_member(
                conn,
                duplicate_group_id=group_id,
                slide_id=slide_id,
                commit=False,
            )


def _sync_slide_identities(conn, path: Path, presentation_id: int) -> None:
    rows = conn.execute(
        """SELECT id, slide_index, text_hash, screenshot_hash
           FROM slides WHERE presentation_id = ? ORDER BY slide_index""",
        (presentation_id,),
    ).fetchall()
    for slide_id_raw, slide_index_raw, text_hash, screenshot_hash in rows:
        slide_id = int(slide_id_raw)
        revision_id = compute_slide_revision_id(path, int(slide_index_raw) + 1)
        current = conn.execute(
            """SELECT canonical_asset_id, slide_revision_id
               FROM asset_identity_map WHERE legacy_slide_id = ?""",
            (slide_id,),
        ).fetchone()
        canonical_id = (
            str(current[0])
            if current is not None
            else f"asset_{uuid.uuid5(uuid.NAMESPACE_URL, f'slide:{slide_id}')}"
        )
        if current is not None and str(current[1]) != revision_id:
            conn.execute(
                "UPDATE asset_identity_map SET legacy_slide_id = NULL, updated_at = ? WHERE legacy_slide_id = ?",
                (_now_iso(), slide_id),
            )
        upsert_identity_mapping(
            conn,
            canonical_asset_id=canonical_id,
            slide_revision_id=revision_id,
            legacy_slide_id=slide_id,
            identity_status="resolved",
        )
        upsert_slide_asset(conn, canonical_id, commit=False)
        insert_slide_revision(
            conn,
            SlideRevision(
                slide_revision_id=revision_id,
                canonical_asset_id=canonical_id,
                fingerprint=revision_id,
                algorithm_version=FINGERPRINT_VERSION,
                text_hash=str(text_hash or ""),
                visual_hash=str(screenshot_hash) if screenshot_hash else None,
                layout_hash=None,
                created_at=_now_iso(),
            ),
            commit=False,
        )


def _duplicate_components(rows: list[tuple[int, str | None, str | None]]) -> list[set[int]]:
    parent: dict[int, int] = {}

    def find(item: int) -> int:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_key: dict[tuple[str, str], list[int]] = {}
    for slide_id, screenshot_hash, text_hash in rows:
        if screenshot_hash:
            by_key.setdefault(("screenshot", screenshot_hash), []).append(slide_id)
        if text_hash:
            by_key.setdefault(("text", text_hash), []).append(slide_id)

    for slide_ids in by_key.values():
        if len(slide_ids) < 2:
            continue
        first = slide_ids[0]
        for slide_id in slide_ids[1:]:
            union(first, slide_id)

    components: dict[int, set[int]] = {}
    for slide_id in parent:
        components.setdefault(find(slide_id), set()).add(slide_id)
    return [component for component in components.values() if len(component) > 1]


def extract_pptx_text(path: Path) -> dict[int, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            slide_names = sorted(
                (name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")),
                key=_slide_sort_key,
            )
            texts: dict[int, str] = {}
            for index, name in enumerate(slide_names):
                root = ElementTree.fromstring(archive.read(name))
                parts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
                texts[index] = " ".join(part.strip() for part in parts if part.strip())
            if not texts:
                return {0: ""}
            return texts
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ValueError(f"Invalid PPTX file: {path}") from exc


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_state(conn, path: Path) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT p.file_size, p.file_mtime, p.content_hash, j.status
        FROM presentations p
        LEFT JOIN index_jobs j ON j.file_path = p.path
        WHERE p.path = ?
        """,
        (str(path),),
    ).fetchone()
    if not row:
        return None
    metadata_rows = conn.execute(
        """SELECT s.metadata_json
           FROM slides s
           JOIN presentations p ON p.id = s.presentation_id
           WHERE p.path = ?
           ORDER BY s.id""",
        (str(path),),
    ).fetchall()
    signatures: set[tuple[str, str, int]] = set()
    metadata_complete = bool(metadata_rows)
    for (metadata_json,) in metadata_rows:
        signature = _embedding_signature_from_metadata(metadata_json)
        if signature is None:
            metadata_complete = False
            continue
        signatures.add(signature)
    return {
        "file_size": row[0],
        "file_mtime": row[1],
        "content_hash": row[2],
        "job_status": row[3],
        "embedding_metadata_complete": metadata_complete,
        "embedding_signatures": tuple(sorted(signatures)),
    }


def _error_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "INDEX_FILE_NOT_FOUND"
    if isinstance(exc, ValueError):
        return "INDEX_INVALID_PPTX"
    return "INDEX_FAILED"


def _normalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _should_use_vision(slide_index: int, settings: Settings) -> bool:
    limit = settings.vision_max_slides_per_file
    return limit is None or slide_index < limit


def _embedding_signature(settings: Settings, provider: EmbeddingProvider) -> tuple[str, str, int]:
    configured_model = (
        settings.lmstudio_embedding_model
        if settings.embedding_provider == "lmstudio"
        else settings.embedding_model
    )
    model = str(getattr(provider, "model", configured_model))
    dimensions = int(getattr(provider, "dimensions", settings.embedding_dimensions))
    return (settings.embedding_provider, model, dimensions)


def _embedding_signature_from_metadata(metadata_json: object) -> tuple[str, str, int] | None:
    if not isinstance(metadata_json, str):
        return None
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    embedding = metadata.get("embedding")
    if not isinstance(embedding, dict):
        return None
    provider = embedding.get("provider")
    model = embedding.get("model")
    dimensions = embedding.get("dimensions")
    if not isinstance(provider, str) or not isinstance(model, str):
        return None
    if isinstance(dimensions, bool) or not isinstance(dimensions, int):
        return None
    return (provider, model, dimensions)


def _metadata_with_embedding(
    metadata: dict[str, object],
    embedding_signature: tuple[str, str, int],
) -> dict[str, object]:
    provider, model, dimensions = embedding_signature
    enriched = dict(metadata)
    enriched["embedding"] = {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
    }
    return enriched


def _slide_sort_key(name: str) -> tuple[int, str]:
    stem = Path(name).stem
    digits = "".join(char for char in stem if char.isdigit())
    return (int(digits) if digits else 0, name)
