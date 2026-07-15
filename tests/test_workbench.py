"""Tests for workbench shell (v1.8-C)."""

from __future__ import annotations

from ppt_lib.workbench import get_dashboard_html, get_static_dir


class TestWorkbench:
    def test_dashboard_html(self):
        html = get_dashboard_html()
        assert "<!DOCTYPE html>" in html
        assert "PPT Library" in html
        assert "Workbench" in html
        assert "/api/v1" in html
        assert "/api/v2" in html
        assert "ppt_library.search_request.v2" in html

    def test_dashboard_injects_runtime_security_context(self):
        html = get_dashboard_html(
            csrf_token="csrf-test",
            workspace_id="workspace-test",
            auth_required=True,
        )

        assert 'name="ppt-library-csrf" content="csrf-test"' in html
        assert 'name="ppt-library-workspace" content="workspace-test"' in html
        assert 'name="ppt-library-auth-required" content="true"' in html

    def test_dashboard_has_nav(self):
        html = get_dashboard_html()
        assert "Dashboard" in html
        assert "Search" in html
        assert "Assets" in html
        assert "Health" in html
        assert "Review" in html
        assert "Jobs" in html

    def test_dashboard_has_stats(self):
        html = get_dashboard_html()
        assert "stat-slides" in html
        assert "stat-presentations" in html
        assert "stat-schema" in html

    def test_dashboard_has_css(self):
        html = get_dashboard_html()
        assert "<style>" in html
        assert "--bg" in html

    def test_dashboard_has_js(self):
        html = get_dashboard_html()
        assert "<script>" in html
        assert "loadDashboard" in html
        assert "renderSearch" in html
        assert "renderAssets" in html
        assert "renderHealth" in html
        assert "renderReview" in html
        assert "renderJobs" in html
        assert "X-CSRF-Token" in html
        assert "X-Workspace-ID" in html

    def test_dashboard_has_accessible_status_and_error_regions(self):
        html = get_dashboard_html()

        assert 'id="app-status"' in html
        assert 'role="status"' in html
        assert 'aria-live="polite"' in html
        assert 'id="content"' in html
        assert 'tabindex="-1"' in html

    def test_static_dir(self):
        d = get_static_dir()
        assert d.name == "static"
