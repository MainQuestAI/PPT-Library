"""Browser-discovered Workbench regressions."""

from ppt_lib.workbench import get_dashboard_html


def test_async_action_buttons_keep_a_stable_element_reference() -> None:
    """Regression: ISSUE-001 — async writes left action buttons disabled.

    Found by /qa on 2026-07-14.
    Report: .gstack/qa-reports/qa-report-localhost-8899-2026-07-14.md
    """
    html = get_dashboard_html()

    assert html.count("const button = event.currentTarget;") == 2
    assert html.count("button.disabled = false;") == 2
    assert "event.currentTarget.disabled = false;" not in html
