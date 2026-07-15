"""FastAPI server for the local PPT Library Workbench."""

import ipaddress
import secrets
import sqlite3
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ppt_lib.services.app_services import LibraryService, ServiceResult
from ppt_lib.settings import Settings


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_for_host(host: str, port: int) -> str:
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{authority}:{port}"


def _is_wildcard_host(host: str) -> bool:
    return host.strip().lower() in {"0.0.0.0", "::", "[::]"}


def _normalize_hostname(host: str) -> str:
    return host.strip().strip("[]").rstrip(".").lower()


def _normalize_cors_origin(origin: str) -> str:
    value = origin.strip()
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid Workbench CORS origin: {origin}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or "*" in parsed.hostname
        or any(character.isspace() for character in parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Invalid Workbench CORS origin: {origin}")
    hostname = _normalize_hostname(parsed.hostname)
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _host_from_header(value: str) -> str | None:
    if not value or "," in value:
        return None
    try:
        parsed = urlsplit(f"//{value}")
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in parsed.hostname)
    ):
        return None
    return _normalize_hostname(parsed.hostname)


def _package_version() -> str:
    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "0+unknown"


@dataclass
class APIConfig:
    """API server configuration with safe local defaults."""

    host: str = "127.0.0.1"
    port: int = 8899
    db_path: Path | None = None
    secret_key: str = ""
    auth_token: str | None = None
    allow_remote: bool = False
    workspace_id: str = "default"
    settings: Settings | None = None
    cors_origins: list[str] | None = None
    debug: bool = False

    def __post_init__(self) -> None:
        loopback = _is_loopback_host(self.host)
        if not loopback and not self.allow_remote:
            raise ValueError("Non-loopback Workbench binding requires allow_remote=True")
        if not loopback and not self.auth_token:
            raise ValueError("Non-loopback Workbench binding requires an auth token")
        if not self.secret_key:
            self.secret_key = secrets.token_hex(32)
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must not be empty")
        if self.cors_origins is None:
            if loopback:
                self.cors_origins = sorted({
                    _origin_for_host(self.host, self.port),
                    _origin_for_host("127.0.0.1", self.port),
                    _origin_for_host("localhost", self.port),
                    _origin_for_host("::1", self.port),
                })
            elif _is_wildcard_host(self.host):
                raise ValueError(
                    "Wildcard Workbench binding requires at least one explicit CORS origin"
                )
            else:
                self.cors_origins = [_origin_for_host(self.host, self.port)]
        self.cors_origins = sorted({
            _normalize_cors_origin(origin)
            for origin in self.cors_origins
        })


def create_api_app(config: APIConfig | None = None) -> Any:
    """Create a Workbench application.

    Local mode is restricted to a loopback host. Remote binding is an explicit
    opt-in and requires a bearer token. The v2.0.1 Workbench serves one fixed
    namespace per process; it is not a multi-tenant isolation boundary. A
    configured bearer token is a shared administrator credential for the
    entire database.
    """
    try:
        from fastapi import Depends, FastAPI, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    except ImportError as err:
        raise ImportError(
            "FastAPI is required for the API server. "
            "Install with: pip install 'ppt-library[workbench]'"
        ) from err

    config = config or APIConfig()
    package_version = _package_version()
    app = FastAPI(
        title="PPT Library API",
        version=package_version,
        docs_url="/api/docs" if config.debug else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins or [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-CSRF-Token",
            "X-Workspace-ID",
            "Authorization",
        ],
    )

    db_path = config.db_path or (Path.home() / ".ppt-library" / "index.db")
    allowed_origins = set(config.cors_origins or [])
    allowed_hosts = {_normalize_hostname(config.host)}
    for origin in config.cors_origins or []:
        origin_hostname = urlsplit(origin).hostname
        if origin_hostname:
            allowed_hosts.add(_normalize_hostname(origin_hostname))
    if _is_loopback_host(config.host):
        allowed_hosts.update({"127.0.0.1", "localhost", "::1"})
    safe_methods = {"GET", "HEAD", "OPTIONS"}
    read_only_post_paths = {"/api/v2/search"}

    def _error_response(status_code: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail})

    def _secure_response(response: Any) -> Any:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'"
        )
        return response

    @app.middleware("http")
    async def security_boundary(request: Request, call_next: Any) -> Any:
        """Enforce workspace, remote auth, CSRF and browser hardening."""
        request_host = _host_from_header(request.headers.get("Host", ""))
        if request_host not in allowed_hosts:
            return _secure_response(_error_response(400, "Invalid Host header"))
        if request.url.path.startswith("/api/"):
            requested_workspace = request.headers.get("X-Workspace-ID")
            if requested_workspace and requested_workspace != config.workspace_id:
                return _secure_response(_error_response(403, "Workspace access denied"))

            if config.auth_token:
                expected = f"Bearer {config.auth_token}"
                supplied = request.headers.get("Authorization", "")
                if not secrets.compare_digest(supplied, expected):
                    return _secure_response(_error_response(401, "Bearer token required"))

            if request.method.upper() not in safe_methods and request.url.path not in read_only_post_paths:
                origin = request.headers.get("Origin")
                if origin and origin not in allowed_origins:
                    return _secure_response(_error_response(403, "Origin is not allowed"))
                csrf = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(csrf, config.secret_key):
                    return _secure_response(_error_response(403, "CSRF validation failed"))

        response = await call_next(request)
        return _secure_response(response)

    async def _get_service() -> AsyncGenerator[LibraryService, None]:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield LibraryService(conn, settings=config.settings)
        finally:
            conn.close()

    def _resolve_user(request: Request) -> Any:
        from ppt_lib.rbac import Role, UserContext

        requested_workspace = request.headers.get("X-Workspace-ID", config.workspace_id)
        if requested_workspace != config.workspace_id:
            raise HTTPException(status_code=403, detail="Workspace access denied")
        return UserContext(
            user_id="local",
            role=Role.ADMIN,
            workspace_id=config.workspace_id,
        )

    def _require_permission(permission_name: str) -> Any:
        from ppt_lib.rbac import Permission

        def _checker(user: Any = Depends(_resolve_user)) -> Any:
            permission = Permission(permission_name)
            if not user.has_permission(permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission_name} required",
                )
            return user

        return _checker

    def _audit_write(
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        user: Any,
        details: dict[str, object] | None = None,
    ) -> None:
        from ppt_lib.audit import log_action

        conn = sqlite3.connect(str(db_path))
        try:
            log_action(
                conn,
                action,
                entity_type,
                entity_id,
                actor=str(user.user_id),
                details={
                    "workspace_id": config.workspace_id,
                    **(details or {}),
                },
            )
        finally:
            conn.close()

    def _run_audited_write(
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        user: Any,
        operation: Callable[[], ServiceResult],
        details: dict[str, object] | None = None,
    ) -> ServiceResult:
        common_details = details or {}
        _audit_write(
            action=f"{action}.intent",
            entity_type=entity_type,
            entity_id=entity_id,
            user=user,
            details={"phase": "intent", **common_details},
        )
        try:
            result = operation()
        except Exception as exc:
            try:
                _audit_write(
                    action=f"{action}.failed",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    user=user,
                    details={
                        "phase": "outcome",
                        "success": False,
                        "error_type": type(exc).__name__,
                        **common_details,
                    },
                )
            except Exception:
                # The durable intent still marks an incomplete operation.
                pass
            raise
        _audit_write(
            action=action if result.success else f"{action}.failed",
            entity_type=entity_type,
            entity_id=entity_id,
            user=user,
            details={
                "phase": "outcome",
                "success": result.success,
                **common_details,
            },
        )
        return result

    @app.get("/", response_class=HTMLResponse)
    async def workbench_shell() -> HTMLResponse:
        from ppt_lib.workbench import get_dashboard_html

        return HTMLResponse(
            get_dashboard_html(
                csrf_token=config.secret_key,
                workspace_id=config.workspace_id,
                auth_required=bool(config.auth_token),
            )
        )

    @app.get("/api/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": package_version,
                "workspace_id": config.workspace_id,
            }
        )

    @app.get("/api/v1/status")
    async def status(
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_assets")),
    ) -> JSONResponse:
        return _envelope_response(svc.get_status(), workspace_id=config.workspace_id)

    @app.get("/api/v1/search")
    async def search(
        q: str = "",
        top_k: int = 10,
        profile: str = "default",
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("search")),
    ) -> JSONResponse:
        if not q:
            raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
        result = svc.search.search(q, top_k=top_k, profile_name=profile)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v2/search")
    async def search_v2(
        request: Request,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("search")),
    ) -> JSONResponse:
        from ppt_lib.contracts.errors import INVALID_INPUT, ContractError, error
        from ppt_lib.contracts.registry import build_envelope_v2, get_registry

        try:
            raw_payload = await request.json()
        except (UnicodeDecodeError, ValueError):
            raw_payload = None
        request_id = (
            str(raw_payload.get("request_id", ""))
            if isinstance(raw_payload, dict)
            else ""
        )

        def contract_error_response(
            errors: list[ContractError],
            *,
            status_code: int = 422,
        ) -> JSONResponse:
            return JSONResponse(
                status_code=status_code,
                content={
                    "_meta": build_envelope_v2(
                        "search",
                        "ppt_library.search_response.v2",
                        request_id=request_id,
                    ),
                    "data": {"candidates": [], "trace": None},
                    "_warnings": [],
                    "_errors": [item.to_json() for item in errors],
                },
            )

        if not isinstance(raw_payload, dict):
            return contract_error_response(
                [error(INVALID_INPUT, "Request body must be a JSON object", source_module="api")]
            )

        registry = get_registry()
        validation_errors = registry.validate("search-request.v2", raw_payload)
        if validation_errors:
            return contract_error_response(validation_errors)

        try:
            result = svc.search.search_v2(
                str(raw_payload["query"]),
                top_k=int(raw_payload.get("top_k", 10)),
                profile_name=str(raw_payload.get("search_profile", "default")),
                request_id=request_id,
                run_id=(
                    str(raw_payload["run_id"])
                    if raw_payload.get("run_id") is not None
                    else None
                ),
                explain=bool(raw_payload.get("explain", True)),
                filters=(
                    raw_payload["filters"]
                    if isinstance(raw_payload.get("filters"), dict)
                    else None
                ),
                context=(
                    raw_payload["context"]
                    if isinstance(raw_payload.get("context"), dict)
                    else None
                ),
            )
        except ValueError as exc:
            return contract_error_response(
                [error(INVALID_INPUT, str(exc), source_module="search")]
            )

        response_errors = registry.validate("search-response.v2", result)
        if response_errors:
            return contract_error_response(response_errors, status_code=500)
        return JSONResponse(content=result)

    @app.get("/api/v1/assets")
    async def list_assets(
        limit: int = 50,
        offset: int = 0,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_assets")),
    ) -> JSONResponse:
        return _envelope_response(
            svc.assets.list_assets(limit=limit, offset=offset),
            workspace_id=config.workspace_id,
        )

    @app.get("/api/v1/assets/{asset_id}")
    async def get_asset(
        asset_id: str,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_assets")),
    ) -> JSONResponse:
        result = svc.assets.get_asset(asset_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v1/health/scan")
    async def health_scan(
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("resolve_health")),
    ) -> JSONResponse:
        result = _run_audited_write(
            action="health.scan",
            entity_type="health",
            entity_id=config.workspace_id,
            user=user,
            operation=svc.health.run_scan,
        )
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.get("/api/v1/health/findings")
    async def health_findings(
        severity: str | None = None,
        limit: int = 50,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_health")),
    ) -> JSONResponse:
        return _envelope_response(
            svc.health.get_findings(severity=severity, limit=limit),
            workspace_id=config.workspace_id,
        )

    @app.post("/api/v1/health/findings/{finding_id}/resolve")
    async def resolve_finding(
        finding_id: str,
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("resolve_health")),
    ) -> JSONResponse:
        result = _run_audited_write(
            action="health.resolve",
            entity_type="health_finding",
            entity_id=finding_id,
            user=user,
            operation=lambda: svc.health.resolve_finding(finding_id),
        )
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v1/review/classify")
    async def run_classification(
        limit: int = 100,
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("edit_classifications")),
    ) -> JSONResponse:
        result = _run_audited_write(
            action="review.classify",
            entity_type="classification_batch",
            entity_id=config.workspace_id,
            user=user,
            operation=lambda: svc.review.run_classification(limit=limit),
            details={"limit": limit},
        )
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v1/review/approve/{asset_id}/{field_name}")
    async def approve_classification(
        asset_id: str,
        field_name: str,
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("edit_classifications")),
    ) -> JSONResponse:
        entity_id = f"{asset_id}:{field_name}"
        result = _run_audited_write(
            action="review.approve",
            entity_type="classification",
            entity_id=entity_id,
            user=user,
            operation=lambda: svc.review.approve(asset_id, field_name),
        )
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v1/review/reject/{asset_id}/{field_name}")
    async def reject_classification(
        asset_id: str,
        field_name: str,
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("edit_classifications")),
    ) -> JSONResponse:
        entity_id = f"{asset_id}:{field_name}"
        result = _run_audited_write(
            action="review.reject",
            entity_type="classification",
            entity_id=entity_id,
            user=user,
            operation=lambda: svc.review.reject(asset_id, field_name),
        )
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.get("/api/v1/review/status")
    async def review_status(
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_assets")),
    ) -> JSONResponse:
        return _envelope_response(
            svc.review.get_status(),
            workspace_id=config.workspace_id,
        )

    @app.get("/api/v1/jobs")
    async def list_jobs(
        status: str | None = None,
        limit: int = 50,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_jobs")),
    ) -> JSONResponse:
        return _envelope_response(
            svc.jobs.list_jobs(status=status, limit=limit),
            workspace_id=config.workspace_id,
        )

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(
        job_id: str,
        svc: LibraryService = Depends(_get_service),
        _user: Any = Depends(_require_permission("view_jobs")),
    ) -> JSONResponse:
        result = svc.jobs.get_job(job_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(
        job_id: str,
        svc: LibraryService = Depends(_get_service),
        user: Any = Depends(_require_permission("cancel_jobs")),
    ) -> JSONResponse:
        result = _run_audited_write(
            action="job.cancel",
            entity_type="job",
            entity_id=job_id,
            user=user,
            operation=lambda: svc.jobs.cancel_job(job_id),
        )
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return _envelope_response(result, workspace_id=config.workspace_id)

    @app.get("/api/v1/audit")
    async def list_audit(
        entity_type: str | None = None,
        entity_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
        _user: Any = Depends(_require_permission("view_audit")),
    ) -> JSONResponse:
        from ppt_lib.audit import get_audit_log

        conn = sqlite3.connect(str(db_path))
        try:
            entries = get_audit_log(
                conn,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                limit=limit,
            )
        finally:
            conn.close()
        return _envelope_response(
            ServiceResult(
                success=True,
                message=f"Listed {len(entries)} audit entries",
                data={"entries": [entry.to_json() for entry in entries]},
            ),
            workspace_id=config.workspace_id,
        )

    def _health_event_stream(
        *,
        poll_interval: float,
        max_polls: int,
    ) -> Generator[str, None, None]:
        from ppt_lib.sse import generate_health_stream

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            for event in generate_health_stream(
                conn,
                poll_interval=poll_interval,
                max_polls=max_polls,
            ):
                yield event.format()
        finally:
            conn.close()

    @app.get("/api/v1/events/health")
    async def health_events(
        poll_interval: float = 5.0,
        max_polls: int = 100,
        _user: Any = Depends(_require_permission("view_health")),
    ) -> StreamingResponse:
        return StreamingResponse(
            _health_event_stream(
                poll_interval=max(0.0, poll_interval),
                max_polls=max(1, min(max_polls, 1000)),
            ),
            media_type="text/event-stream",
        )

    def _job_event_stream(
        job_id: str,
        *,
        poll_interval: float,
        max_polls: int,
    ) -> Generator[str, None, None]:
        from ppt_lib.sse import generate_job_events

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            for event in generate_job_events(
                conn,
                job_id,
                poll_interval=poll_interval,
                max_polls=max_polls,
            ):
                yield event.format()
        finally:
            conn.close()

    @app.get("/api/v1/events/jobs/{job_id}")
    async def job_events(
        job_id: str,
        poll_interval: float = 1.0,
        max_polls: int = 1000,
        _user: Any = Depends(_require_permission("view_jobs")),
    ) -> StreamingResponse:
        return StreamingResponse(
            _job_event_stream(
                job_id,
                poll_interval=max(0.0, poll_interval),
                max_polls=max(1, min(max_polls, 10_000)),
            ),
            media_type="text/event-stream",
        )

    return app


def _envelope_response(
    result: ServiceResult,
    *,
    workspace_id: str = "default",
) -> Any:
    """Wrap a service result in the stable v1 API envelope."""
    from datetime import UTC, datetime

    from fastapi.responses import JSONResponse

    envelope = {
        "_meta": {
            "schema_version": "1.0",
            "command": "api",
            "workspace_id": workspace_id,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        **({"data": result.data} if result.data is not None else {}),
        "success": result.success,
        "message": result.message,
        "_errors": result.errors or [],
    }
    return JSONResponse(
        content=envelope,
        status_code=200 if result.success else 400,
    )
