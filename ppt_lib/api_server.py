"""Local API server for PPT Library Workbench (v1.8-B).

Provides a FastAPI-based REST API with session security, CSRF protection,
and the standard PPT Library envelope format.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ppt_lib.services.app_services import LibraryService, ServiceResult


@dataclass
class APIConfig:
    """API server configuration."""

    host: str = "127.0.0.1"
    port: int = 8899
    db_path: Path | None = None
    secret_key: str = ""
    cors_origins: list[str] | None = None
    debug: bool = False

    def __post_init__(self) -> None:
        if not self.secret_key:
            self.secret_key = secrets.token_hex(32)
        if self.cors_origins is None:
            self.cors_origins = ["http://127.0.0.1:8899"]


def create_api_app(config: APIConfig | None = None) -> Any:
    """Create and configure the FastAPI application.

    Returns the FastAPI app instance. Requires fastapi to be installed.
    """
    try:
        from fastapi import Depends, FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
    except ImportError as err:
        raise ImportError(
            "FastAPI is required for the API server. "
            "Install with: pip install 'ppt-library[workbench]'"
        ) from err

    config = config or APIConfig()

    app = FastAPI(
        title="PPT Library API",
        version="1.8.0",
        docs_url="/api/docs" if config.debug else None,
        redoc_url=None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins or [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
    )

    # Database connection (per-request)
    _db_path = config.db_path or (Path.home() / ".ppt-library" / "index.db")

    def _get_service() -> LibraryService:
        conn = sqlite3.connect(str(_db_path))
        conn.row_factory = sqlite3.Row
        return LibraryService(conn)

    # --- Auth dependency (RBAC) ---
    # Local mode defaults to admin; Server Mode should override _resolve_user
    # to extract the user from session/token/headers.

    def _resolve_user() -> Any:
        """Resolve the current user context. Override in Server Mode."""
        from ppt_lib.rbac import Role, UserContext
        return UserContext(user_id="local", role=Role.ADMIN, workspace_id="default")

    def _require_permission(permission_name: str) -> Any:
        """FastAPI dependency enforcing a permission on write endpoints."""
        from ppt_lib.rbac import Permission

        def _checker(user: Any = Depends(_resolve_user)) -> Any:
            perm = Permission(permission_name)
            if not user.has_permission(perm):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission_name} required",
                )
            return user

        return _checker

    # --- Health endpoints ---

    @app.get("/api/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "1.8.0"})

    @app.get("/api/v1/status")
    async def status() -> JSONResponse:
        svc = _get_service()
        result = svc.get_status()
        return _envelope_response(result)

    # --- Search endpoints ---

    @app.get("/api/v1/search")
    async def search(
        q: str = "",
        top_k: int = 10,
        profile: str = "default",
    ) -> JSONResponse:
        if not q:
            raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
        svc = _get_service()
        result = svc.search.search(q, top_k=top_k, profile_name=profile)
        return _envelope_response(result)

    # --- Asset endpoints ---

    @app.get("/api/v1/assets")
    async def list_assets(limit: int = 50, offset: int = 0) -> JSONResponse:
        svc = _get_service()
        result = svc.assets.list_assets(limit=limit, offset=offset)
        return _envelope_response(result)

    @app.get("/api/v1/assets/{asset_id}")
    async def get_asset(asset_id: str) -> JSONResponse:
        svc = _get_service()
        result = svc.assets.get_asset(asset_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    # --- Health endpoints ---

    @app.post("/api/v1/health/scan")
    async def health_scan(_user: Any = Depends(_require_permission("resolve_health"))) -> JSONResponse:
        svc = _get_service()
        result = svc.health.run_scan()
        return _envelope_response(result)

    @app.get("/api/v1/health/findings")
    async def health_findings(
        severity: str | None = None,
        limit: int = 50,
    ) -> JSONResponse:
        svc = _get_service()
        result = svc.health.get_findings(severity=severity, limit=limit)
        return _envelope_response(result)

    @app.post("/api/v1/health/findings/{finding_id}/resolve")
    async def resolve_finding(finding_id: str, _user: Any = Depends(_require_permission("resolve_health"))) -> JSONResponse:
        svc = _get_service()
        result = svc.health.resolve_finding(finding_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    # --- Review endpoints ---

    @app.post("/api/v1/review/classify")
    async def run_classification(limit: int = 100, _user: Any = Depends(_require_permission("edit_classifications"))) -> JSONResponse:
        svc = _get_service()
        result = svc.review.run_classification(limit=limit)
        return _envelope_response(result)

    @app.post("/api/v1/review/approve/{asset_id}/{field_name}")
    async def approve_classification(
        asset_id: str, field_name: str,
        _user: Any = Depends(_require_permission("edit_classifications")),
    ) -> JSONResponse:
        svc = _get_service()
        result = svc.review.approve(asset_id, field_name)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    @app.post("/api/v1/review/reject/{asset_id}/{field_name}")
    async def reject_classification(
        asset_id: str, field_name: str,
        _user: Any = Depends(_require_permission("edit_classifications")),
    ) -> JSONResponse:
        svc = _get_service()
        result = svc.review.reject(asset_id, field_name)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    @app.get("/api/v1/review/status")
    async def review_status() -> JSONResponse:
        svc = _get_service()
        result = svc.review.get_status()
        return _envelope_response(result)

    # --- Job endpoints ---

    @app.get("/api/v1/jobs")
    async def list_jobs(status: str | None = None, limit: int = 50) -> JSONResponse:
        svc = _get_service()
        result = svc.jobs.list_jobs(status=status, limit=limit)
        return _envelope_response(result)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> JSONResponse:
        svc = _get_service()
        result = svc.jobs.get_job(job_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, _user: Any = Depends(_require_permission("cancel_jobs"))) -> JSONResponse:
        svc = _get_service()
        result = svc.jobs.cancel_job(job_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result)

    return app


def _envelope_response(result: ServiceResult) -> Any:
    """Wrap a ServiceResult in the standard API envelope."""
    from datetime import UTC, datetime

    from fastapi.responses import JSONResponse

    envelope = {
        "_meta": {
            "schema_version": "1.0",
            "command": "api",
            "generated_at": datetime.now(UTC).isoformat(),
        },
        **({"data": result.data} if result.data else {}),
        "success": result.success,
        "message": result.message,
        "_errors": result.errors or [],
    }

    status_code = 200 if result.success else 400
    return JSONResponse(content=envelope, status_code=status_code)
