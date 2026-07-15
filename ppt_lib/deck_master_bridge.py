from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from ppt_lib.contracts import get_registry
from ppt_lib.db import connect, init_db
from ppt_lib.readiness import build_readiness
from ppt_lib.searcher import load_search_rows
from ppt_lib.selector import SelectionReport, select_slides
from ppt_lib.settings import Settings


class DeckMasterBridgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_deck_master_selection_v2(
    settings: Settings,
    *,
    plan_path: Path,
    run_id: str,
    max_per_role: int,
    ranking: str,
    threshold: float,
) -> dict[str, object]:
    plan = _load_bridge_plan(plan_path, run_id)
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn, backups_dir=settings.backups_dir)
    try:
        readiness = build_readiness(conn, settings)
        selections: list[dict[str, object]] = []
        gaps: list[str] = []
        for request in plan["requests"]:
            assert isinstance(request, dict)
            role = str(request["role_mapped"])
            role_available = _active_role_available(conn, settings, role)
            report = select_slides(
                settings,
                roles=[role],
                brief=str(request["query"]),
                max_per_role=max_per_role,
                ranking=ranking,
                threshold=threshold,
                scope="active",
            )
            candidates = _candidate_payloads(conn, report, request)
            if candidates:
                retrieval_method = "role_selection"
                fallback_reason = None
            else:
                retrieval_method = "none"
                fallback_reason = "ROLE_SELECTION_NO_MATCH" if role_available else "ROLE_SELECTION_UNAVAILABLE"
                gaps.append(str(request["beat_id"]))
            selections.append({
                "beat_id": str(request["beat_id"]),
                "page_task_id": str(request["page_task_id"]),
                "query_trace_id": str(request["query_trace_id"]),
                "role_original": str(request["role_original"]),
                "role_strategy": str(request["role_strategy"]),
                "role_mapped": role,
                "retrieval_method": retrieval_method,
                "fallback_reason": fallback_reason,
                "preview_status": _selection_preview_status(candidates),
                "candidates": candidates,
            })
        snapshot_keys = (
            "schema_version",
            "overall_status",
            "semantic_search_ready",
            "role_selection_ready",
            "preview_status",
            "data_hygiene_status",
            "reason_codes",
        )
        payload: dict[str, object] = {
            "schema_version": "deck_master_ppt_library_selection.v2",
            "run_id": run_id,
            "source": "ppt-library",
            "producer_version": _producer_version(),
            "identity_scope": "ppt_library_database_lifecycle",
            "generated_at": datetime.now(UTC).isoformat(),
            "capability_snapshot": {key: readiness[key] for key in snapshot_keys},
            "selections": selections,
            "gaps": gaps,
        }
        _validate_contract("deck-master-selection.v2", payload)
        return payload
    finally:
        conn.close()


def write_selection_v2_atomic(
    output_path: Path,
    payload: dict[str, object],
    *,
    replace_existing: bool = False,
) -> str:
    _validate_contract("deck-master-selection.v2", payload)
    try:
        output_path = output_path.expanduser().resolve(strict=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DeckMasterBridgeError("CONTRACT_OUTPUT_PARENT_INVALID", str(exc)) from exc
    if not output_path.parent.is_dir():
        raise DeckMasterBridgeError("CONTRACT_OUTPUT_PARENT_INVALID", "Output parent is not a directory.")

    lock_path = output_path.parent / f".{output_path.name}.lock"
    try:
        with FileLock(lock_path, timeout=5):
            return _write_selection_v2_locked(output_path, payload, replace_existing=replace_existing)
    except Timeout as exc:
        raise DeckMasterBridgeError(
            "CONTRACT_WRITE_LOCK_TIMEOUT",
            f"Timed out waiting for output lock: {lock_path}",
        ) from exc
    except OSError as exc:
        raise DeckMasterBridgeError("CONTRACT_WRITE_FAILED", str(exc)) from exc


def _write_selection_v2_locked(
    output_path: Path,
    payload: dict[str, object],
    *,
    replace_existing: bool,
) -> str:
    output_existed = output_path.exists()
    if output_existed:
        existing = _read_existing_contract(output_path)
        try:
            _validate_contract("deck-master-selection.v2", existing)
        except DeckMasterBridgeError as exc:
            raise DeckMasterBridgeError("CONTRACT_EXISTING_INVALID", str(exc)) from exc
        if existing.get("run_id") != payload.get("run_id"):
            raise DeckMasterBridgeError(
                "CONTRACT_RUN_ID_MISMATCH",
                "Existing selection belongs to a different run_id.",
            )
        if _semantic_payload(existing) == _semantic_payload(payload):
            return "unchanged"
        if not replace_existing:
            raise DeckMasterBridgeError(
                "CONTRACT_IDEMPOTENCY_CONFLICT",
                "Existing selection differs for the same run_id; use --replace-existing to update it.",
            )

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                raise DeckMasterBridgeError("CONTRACT_FSYNC_FAILED", str(exc)) from exc
        try:
            os.replace(temp_path, output_path)
        except OSError as exc:
            raise DeckMasterBridgeError("CONTRACT_WRITE_FAILED", str(exc)) from exc
        try:
            _fsync_directory(output_path.parent)
        except OSError as exc:
            raise DeckMasterBridgeError("CONTRACT_FSYNC_FAILED", str(exc)) from exc
        return "replaced" if output_existed else "written"
    except DeckMasterBridgeError:
        raise
    except OSError as exc:
        raise DeckMasterBridgeError("CONTRACT_WRITE_FAILED", str(exc)) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _load_bridge_plan(plan_path: Path, run_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeckMasterBridgeError("BRIDGE_PLAN_INVALID", f"Cannot read bridge plan: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeckMasterBridgeError("BRIDGE_PLAN_INVALID", "Bridge plan must be a JSON object.")
    _validate_contract("deck-master-bridge-plan.v1", payload)
    if payload.get("run_id") != run_id:
        raise DeckMasterBridgeError("BRIDGE_PLAN_RUN_ID_MISMATCH", "CLI run_id does not match the bridge plan.")
    return payload


def _candidate_payloads(
    conn: sqlite3.Connection,
    report: SelectionReport,
    request: dict[str, Any],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for role_selection in report.roles:
        for result in role_selection.slides:
            row = conn.execute(
                """
                SELECT p.content_hash, s.screenshot_hash, sc.file_path
                FROM slides s
                JOIN presentations p ON p.id = s.presentation_id
                LEFT JOIN screenshots sc ON sc.hash = s.screenshot_hash
                WHERE s.id = ?
                """,
                (result.slide_id,),
            ).fetchone()
            content_hash = str(row[0]) if row and row[0] else None
            screenshot_hash = str(row[1]) if row and row[1] else None
            screenshot_path = Path(row[2]) if row and row[2] else None
            asset_key = _asset_key(
                canonical_slide_id=result.canonical_slide_id,
                source_file=result.source_file,
                content_hash=content_hash,
                page_number=result.page_number,
                slide_id=result.slide_id,
            )
            source_hash = content_hash or _path_hash(result.source_file)
            preview_status = _candidate_preview_status(screenshot_path)
            candidates.append({
                "candidate_id": f"ppt-library:{asset_key}",
                "asset_key": asset_key,
                "slide_id": result.slide_id,
                "canonical_slide_id": result.canonical_slide_id,
                "source_asset_id": (
                    f"pptx-sha256:{source_hash}" if content_hash else f"source-path-sha256:{source_hash}"
                ),
                "source_display_name": result.source_file.name,
                "source_locator": str(result.source_file.expanduser().resolve(strict=False)),
                "title": result.title,
                "text_summary": result.text_summary,
                "page_number": result.page_number,
                "score": result.score,
                "confidence": result.confidence,
                "screenshot_ref": (
                    f"ppt-library://screenshots/{screenshot_hash}" if screenshot_hash else None
                ),
                "preview_status": preview_status,
                "candidate_origin": "ppt_library",
                "reuse_policy": str(request["reuse_policy"]),
            })
    return candidates


def _active_role_available(conn: sqlite3.Connection, settings: Settings, role: str) -> bool:
    return bool(load_search_rows(conn, settings.embedding_dimensions, narrative_role=role, scope="active"))


def _asset_key(
    *,
    canonical_slide_id: int | None,
    source_file: Path,
    content_hash: str | None,
    page_number: int,
    slide_id: int | None,
) -> str:
    if canonical_slide_id is not None:
        return f"canonical:{canonical_slide_id}"
    source_hash = content_hash or _path_hash(source_file)
    if source_hash:
        return f"source-page:{source_hash}:{page_number}"
    if slide_id is not None:
        return f"slide:{slide_id}"
    raise DeckMasterBridgeError("CANDIDATE_IDENTITY_MISSING", "Candidate has no stable identity.")


def _path_hash(path: Path) -> str:
    normalized = str(path.expanduser().resolve(strict=False))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _candidate_preview_status(screenshot_path: Path | None) -> str:
    if screenshot_path is None:
        return "missing"
    return "ready" if screenshot_path.is_file() else "invalid"


def _selection_preview_status(candidates: list[dict[str, object]]) -> str:
    states = {candidate["preview_status"] for candidate in candidates}
    if "ready" in states:
        return "ready"
    if "invalid" in states:
        return "invalid"
    return "missing"


def _validate_contract(name: str, payload: dict[str, object]) -> None:
    errors = get_registry().validate(name, payload, strict=True)
    if errors:
        details = "; ".join(f"{item.details.get('path')}: {item.message}" for item in errors[:5])
        raise DeckMasterBridgeError("CONTRACT_VALIDATION_FAILED", details)


def _read_existing_contract(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeckMasterBridgeError("CONTRACT_EXISTING_INVALID", str(exc)) from exc
    if not isinstance(payload, dict):
        raise DeckMasterBridgeError("CONTRACT_EXISTING_INVALID", "Existing selection must be a JSON object.")
    return payload


def _semantic_payload(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "generated_at"}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _producer_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "2.1.0.dev0"
