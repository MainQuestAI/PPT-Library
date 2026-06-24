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

    def test_static_dir(self):
        d = get_static_dir()
        assert d.name == "static"
