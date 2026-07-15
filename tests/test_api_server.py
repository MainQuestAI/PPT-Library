"""Tests for local API server (v1.8-B)."""

from __future__ import annotations

import sqlite3
from functools import partial
from importlib import metadata
from pathlib import Path

import pytest

from ppt_lib.api_server import APIConfig, create_api_app
from ppt_lib.asset_schema import upsert_slide_asset
from ppt_lib.db import connect, init_db
from ppt_lib.fts_search import index_from_slides


def _create_test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO presentations
           (id, path, filename, slide_count, indexed_at)
           VALUES (1, '/test.pptx', 'test.pptx', 1, 'now')"""
    )
    conn.execute(
        """INSERT INTO slides
           (id, presentation_id, slide_index, text_content, title, source, metadata_json)
           VALUES (1, 1, 1, 'architecture diagram', 'T1', 'text_extraction', '{}')"""
    )
    index_from_slides(conn)
    conn.commit()
    upsert_slide_asset(conn, "a1")
    conn.close()
    return db_path


class TestAPIConfig:
    def test_default_config(self):
        config = APIConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8899
        assert len(config.secret_key) > 0

    def test_custom_config(self):
        config = APIConfig(
            host="0.0.0.0",
            port=9000,
            debug=True,
            allow_remote=True,
            auth_token="test-token",
            cors_origins=["http://192.168.1.50:9000"],
        )
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.debug is True

    def test_auto_secret(self):
        c1 = APIConfig()
        c2 = APIConfig()
        assert c1.secret_key != c2.secret_key

    def test_remote_bind_requires_explicit_opt_in(self):
        with pytest.raises(ValueError, match="allow_remote"):
            APIConfig(host="0.0.0.0")

    def test_remote_bind_requires_auth_token(self):
        with pytest.raises(ValueError, match="auth token"):
            APIConfig(host="0.0.0.0", allow_remote=True)

    def test_wildcard_remote_bind_requires_explicit_browser_origin(self):
        with pytest.raises(ValueError, match="explicit CORS origin"):
            APIConfig(host="0.0.0.0", allow_remote=True, auth_token="test-token")

    @pytest.mark.parametrize(
        "origin",
        [
            "*",
            "null",
            "ftp://example.com",
            "https://*.example.com",
            "https://user@example.com",
            "https://example.com/path",
        ],
    )
    def test_cors_origin_must_be_an_explicit_http_origin(self, origin: str):
        with pytest.raises(ValueError, match="Invalid Workbench CORS origin"):
            APIConfig(cors_origins=[origin])

    def test_workspace_must_not_be_empty(self):
        with pytest.raises(ValueError, match="workspace_id"):
            APIConfig(workspace_id="   ")

    def test_ipv6_loopback_origin_is_bracketed(self):
        config = APIConfig(host="::1", port=9001)

        assert "http://[::1]:9001" in config.cors_origins


try:
    from fastapi.testclient import TestClient as _FastAPITestClient
    TestClient = partial(
        _FastAPITestClient,
        base_url="http://127.0.0.1:8899",
    )

    def _remote_test_client(app):
        return _FastAPITestClient(
            app,
            base_url="http://192.168.1.50:8899",
        )

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestAPIEndpoints:
    @staticmethod
    def _csrf_headers(config: APIConfig) -> dict[str, str]:
        return {
            "X-CSRF-Token": config.secret_key,
            "Origin": f"http://{config.host}:{config.port}",
            "X-Workspace-ID": config.workspace_id,
        }

    def test_health(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == metadata.version("ppt-library")

    def test_workbench_shell_is_served_with_security_headers(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.get("/")

        assert response.status_code == 200
        assert "PPT Library Workbench" in response.text
        assert f'name="ppt-library-csrf" content="{config.secret_key}"' in response.text
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_status(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_search(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/search?q=architecture")
        assert response.status_code == 200

    def test_search_empty_query(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/search")
        assert response.status_code == 400

    def test_search_v2_returns_valid_contract_without_csrf(self, tmp_path: Path):
        from ppt_lib.contracts.registry import get_registry

        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            "/api/v2/search",
            json={
                "contract": "ppt_library.search_request.v2",
                "request_id": "req-api-v2",
                "query": "architecture",
                "top_k": 5,
                "explain": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["_meta"]["request_id"] == "req-api-v2"
        assert payload["_meta"]["contract"] == "ppt_library.search_response.v2"
        assert payload["data"]["candidates"][0]["provenance"]["legacy_slide_id"] == 1
        assert get_registry().validate("search-response.v2", payload) == []

    def test_search_v2_rejects_invalid_request_contract(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        client = TestClient(create_api_app(APIConfig(db_path=db_path)))

        response = client.post(
            "/api/v2/search",
            json={
                "contract": "ppt_library.search_request.v2",
                "query": "architecture",
                "unexpected": True,
            },
        )

        assert response.status_code == 422
        codes = {item["code"] for item in response.json()["_errors"]}
        assert codes == {"CONTRACT_VALIDATION_FAILED"}

    def test_search_v2_rejects_malformed_body_and_unknown_profile(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        client = TestClient(create_api_app(APIConfig(db_path=db_path)))

        malformed = client.post(
            "/api/v2/search",
            content=b"[",
            headers={"Content-Type": "application/json"},
        )
        unknown_profile = client.post(
            "/api/v2/search",
            json={
                "contract": "ppt_library.search_request.v2",
                "request_id": "req-unknown-profile",
                "query": "architecture",
                "search_profile": "missing",
            },
        )

        assert malformed.status_code == 422
        assert malformed.json()["_errors"][0]["code"] == "INVALID_INPUT"
        assert unknown_profile.status_code == 422
        assert "Unknown search profile" in unknown_profile.json()["_errors"][0]["message"]

    def test_list_assets(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_asset(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets/a1")
        assert response.status_code == 200

    def test_get_asset_not_found(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/assets/nonexistent")
        assert response.status_code == 404

    def test_review_status(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/review/status")
        assert response.status_code == 200

    def test_envelope_format(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        app = create_api_app(config)
        client = TestClient(app)
        response = client.get("/api/v1/status")
        data = response.json()
        assert "_meta" in data
        assert "success" in data
        assert "message" in data
        assert "_errors" in data
        assert data["_meta"]["workspace_id"] == "default"

    def test_write_requires_csrf_token(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post("/api/v1/review/classify?limit=1")

        assert response.status_code == 403
        assert response.json()["detail"] == "CSRF validation failed"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_write_rejects_untrusted_origin(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            "/api/v1/review/classify?limit=1",
            headers={"X-CSRF-Token": config.secret_key, "Origin": "https://evil.example"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Origin is not allowed"

    def test_successful_write_is_audited(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            "/api/v1/review/classify?limit=1",
            headers=self._csrf_headers(config),
        )

        assert response.status_code == 200
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT action, actor, details_json FROM audit_log ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "review.classify"
        assert row[1] == "local"
        assert '"workspace_id": "default"' in row[2]

        conn = sqlite3.connect(str(db_path))
        actions = [
            item[0]
            for item in conn.execute(
                "SELECT action FROM audit_log WHERE entity_type = 'classification_batch' ORDER BY timestamp"
            ).fetchall()
        ]
        conn.close()
        assert actions == ["review.classify.intent", "review.classify"]

    def test_audit_intent_failure_blocks_business_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        operation_called = False

        def run_scan(_service):
            nonlocal operation_called
            operation_called = True
            raise AssertionError("business operation must not run")

        def fail_audit(*args, **kwargs):
            raise sqlite3.OperationalError("audit unavailable")

        monkeypatch.setattr(
            "ppt_lib.services.app_services.HealthService.run_scan",
            run_scan,
        )
        monkeypatch.setattr("ppt_lib.audit.log_action", fail_audit)
        client = _FastAPITestClient(
            create_api_app(config),
            base_url="http://127.0.0.1:8899",
            raise_server_exceptions=False,
        )

        response = client.post(
            "/api/v1/health/scan",
            headers=self._csrf_headers(config),
        )

        assert response.status_code == 500
        assert operation_called is False

    def test_business_exception_records_failed_audit_outcome(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)

        def fail_scan(_service):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(
            "ppt_lib.services.app_services.HealthService.run_scan",
            fail_scan,
        )
        client = _FastAPITestClient(
            create_api_app(config),
            base_url="http://127.0.0.1:8899",
            raise_server_exceptions=False,
        )

        response = client.post(
            "/api/v1/health/scan",
            headers=self._csrf_headers(config),
        )

        assert response.status_code == 500
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT action, details_json FROM audit_log WHERE entity_type = 'health' ORDER BY timestamp"
        ).fetchall()
        conn.close()
        assert [row[0] for row in rows] == ["health.scan.intent", "health.scan.failed"]
        assert '"error_type": "RuntimeError"' in rows[-1][1]
        assert "scan failed" not in rows[-1][1]

    def test_workspace_mismatch_fails_closed(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path, workspace_id="workspace-a")
        client = TestClient(create_api_app(config))

        response = client.get(
            "/api/v1/status",
            headers={"X-Workspace-ID": "workspace-b"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Workspace access denied"

    def test_untrusted_host_is_rejected_before_local_api_access(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = _FastAPITestClient(
            create_api_app(config),
            base_url="http://evil.example",
        )

        api_response = client.get("/api/v1/search?q=architecture")
        shell_response = client.get("/")

        assert api_response.status_code == 400
        assert api_response.json()["detail"] == "Invalid Host header"
        assert shell_response.status_code == 400
        assert api_response.headers["cache-control"] == "no-store"

    def test_remote_api_requires_bearer_token(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(
            host="0.0.0.0",
            db_path=db_path,
            allow_remote=True,
            auth_token="remote-secret",
            cors_origins=["http://192.168.1.50:8899"],
        )
        client = _remote_test_client(create_api_app(config))

        denied = client.get("/api/v1/status")
        allowed = client.get(
            "/api/v1/status",
            headers={"Authorization": "Bearer remote-secret"},
        )

        assert denied.status_code == 401
        assert allowed.status_code == 200

    def test_audit_endpoint_lists_writes(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))
        client.post(
            "/api/v1/review/classify?limit=1",
            headers=self._csrf_headers(config),
        )

        response = client.get("/api/v1/audit")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["entries"][0]["action"] == "review.classify"

    def test_health_sse_stream_terminates_for_test_limit(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.get("/api/v1/events/health?max_polls=1&poll_interval=0")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: health.update" in response.text

    def test_health_scan_and_resolution_are_audited(self, tmp_path: Path):
        from ppt_lib.asset_schema import add_health_finding

        db_path = _create_test_db(tmp_path)
        conn = connect(db_path)
        finding = add_health_finding(
            conn,
            "a1",
            "warning",
            "missing_metadata",
            "Missing review metadata",
        )
        conn.close()
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        scan = client.post("/api/v1/health/scan", headers=self._csrf_headers(config))
        listed = client.get("/api/v1/health/findings?severity=warning")
        resolved = client.post(
            f"/api/v1/health/findings/{finding.finding_id}/resolve",
            headers=self._csrf_headers(config),
        )

        assert scan.status_code == 200
        assert listed.status_code == 200
        assert listed.json()["data"]["findings"][0]["finding_id"] == finding.finding_id
        assert resolved.status_code == 200
        conn = sqlite3.connect(str(db_path))
        state = conn.execute(
            "SELECT state FROM health_findings WHERE finding_id = ?",
            (finding.finding_id,),
        ).fetchone()
        actions = {
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit_log WHERE action IN ('health.scan', 'health.resolve')"
            ).fetchall()
        }
        conn.close()
        assert state == ("resolved",)
        assert actions == {"health.scan", "health.resolve"}

    def test_resolve_unknown_health_finding_returns_404(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            "/api/v1/health/findings/missing/resolve",
            headers=self._csrf_headers(config),
        )

        assert response.status_code == 404
        conn = sqlite3.connect(str(db_path))
        actions = [
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit_log WHERE entity_id = 'missing' ORDER BY timestamp"
            ).fetchall()
        ]
        conn.close()
        assert actions == ["health.resolve.intent", "health.resolve.failed"]

    def test_review_approve_and_reject_are_audited(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO classification_values
               (asset_id, field_name, value, confidence, source, review_state, created_at)
               VALUES ('a1', 'page_archetype', 'diagram', 0.9, 'deterministic', 'pending', 'now')"""
        )
        conn.commit()
        conn.close()
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        approved = client.post(
            "/api/v1/review/approve/a1/page_archetype",
            headers=self._csrf_headers(config),
        )
        rejected = client.post(
            "/api/v1/review/reject/a1/page_archetype",
            headers=self._csrf_headers(config),
        )

        assert approved.status_code == 200
        assert rejected.status_code == 200
        conn = sqlite3.connect(str(db_path))
        state = conn.execute(
            "SELECT review_state FROM classification_values WHERE asset_id = 'a1'"
        ).fetchone()
        actions = {
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'review.%'"
            ).fetchall()
        }
        conn.close()
        assert state == ("rejected",)
        assert {"review.approve", "review.reject"} <= actions

    @pytest.mark.parametrize("operation", ["approve", "reject"])
    def test_review_unknown_classification_returns_404(self, tmp_path: Path, operation: str):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            f"/api/v1/review/{operation}/missing/page_archetype",
            headers=self._csrf_headers(config),
        )

        assert response.status_code == 404

    def test_jobs_list_get_cancel_and_stream(self, tmp_path: Path):
        from ppt_lib.jobs import JobEngine

        db_path = _create_test_db(tmp_path)
        conn = connect(db_path)
        job = JobEngine(conn).create_job("index", "config-hash")
        conn.close()
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        listed = client.get("/api/v1/jobs?status=created")
        fetched = client.get(f"/api/v1/jobs/{job.job_id}")
        stream = client.get(
            f"/api/v1/events/jobs/{job.job_id}?max_polls=1&poll_interval=0"
        )
        cancelled = client.post(
            f"/api/v1/jobs/{job.job_id}/cancel",
            headers=self._csrf_headers(config),
        )

        assert listed.status_code == 200
        assert listed.json()["data"]["jobs"][0]["job_id"] == job.job_id
        assert fetched.status_code == 200
        assert "event: job.progress" in stream.text
        assert cancelled.status_code == 200
        conn = sqlite3.connect(str(db_path))
        cancel_requested = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE job_id = ?",
            (job.job_id,),
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? ORDER BY timestamp DESC LIMIT 1",
            (job.job_id,),
        ).fetchone()
        conn.close()
        assert cancel_requested == (1,)
        assert audit == ("job.cancel",)

    def test_unknown_job_paths_return_404_or_error_event(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        fetched = client.get("/api/v1/jobs/missing")
        cancelled = client.post(
            "/api/v1/jobs/missing/cancel",
            headers=self._csrf_headers(config),
        )
        stream = client.get("/api/v1/events/jobs/missing?max_polls=1&poll_interval=0")

        assert fetched.status_code == 404
        assert cancelled.status_code == 404
        assert "event: error" in stream.text

    def test_remote_workbench_shell_marks_auth_requirement(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(
            host="0.0.0.0",
            db_path=db_path,
            allow_remote=True,
            auth_token="remote-secret",
            cors_origins=["http://192.168.1.50:8899"],
        )
        client = _remote_test_client(create_api_app(config))

        shell = client.get("/")
        wrong_token = client.get(
            "/api/v1/status",
            headers={"Authorization": "Bearer wrong"},
        )

        assert shell.status_code == 200
        assert 'name="ppt-library-auth-required" content="true"' in shell.text
        assert wrong_token.status_code == 401

    def test_remote_write_accepts_explicit_lan_origin(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        origin = "http://192.168.1.50:8899"
        config = APIConfig(
            host="0.0.0.0",
            db_path=db_path,
            allow_remote=True,
            auth_token="remote-secret",
            cors_origins=[origin],
        )
        client = _remote_test_client(create_api_app(config))

        response = client.post(
            "/api/v1/review/classify?limit=1",
            headers={
                "Authorization": "Bearer remote-secret",
                "Origin": origin,
                "X-CSRF-Token": config.secret_key,
            },
        )

        assert response.status_code == 200

    def test_write_accepts_csrf_for_non_browser_client_without_origin(self, tmp_path: Path):
        db_path = _create_test_db(tmp_path)
        config = APIConfig(db_path=db_path)
        client = TestClient(create_api_app(config))

        response = client.post(
            "/api/v1/review/classify?limit=1",
            headers={"X-CSRF-Token": config.secret_key},
        )

        assert response.status_code == 200
