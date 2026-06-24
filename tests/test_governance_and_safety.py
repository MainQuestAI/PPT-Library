"""Tests for incremental governance (1.5-F) and PPTX safety (1.5-G)."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from ppt_lib.governance import (
    ConsistencyIssue,
    GovernanceChangeSummary,
    compute_incremental_governance,
    get_affected_deck_families,
    get_affected_duplicate_groups,
    get_affected_slide_ids,
    has_manual_override,
    validate_consistency,
)
from ppt_lib.pptx_safety import (
    check_pptx_safety,
)


def _create_governance_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE presentations (id INTEGER PRIMARY KEY, path TEXT, filename TEXT)")
    conn.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY, presentation_id INTEGER)")
    conn.execute("CREATE TABLE duplicate_groups (id INTEGER PRIMARY KEY, canonical_slide_id INTEGER, source TEXT DEFAULT 'auto')")
    conn.execute("CREATE TABLE slide_duplicate_members (duplicate_group_id INTEGER, slide_id INTEGER)")
    conn.execute("CREATE TABLE deck_families (id INTEGER PRIMARY KEY, representative_presentation_id INTEGER, source TEXT DEFAULT 'auto')")
    conn.execute(
        "CREATE TABLE presentation_versions ("
        "presentation_id INTEGER, deck_family_id INTEGER,"
        "version_role TEXT, is_representative INTEGER)"
    )
    return conn


class TestIncrementalGovernance:
    def test_get_affected_slide_ids(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (1, 10)")
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (2, 10)")
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (3, 20)")
        ids = get_affected_slide_ids(conn, 10)
        assert sorted(ids) == [1, 2]

    def test_get_affected_duplicate_groups(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO slide_duplicate_members VALUES (100, 1)")
        conn.execute("INSERT INTO slide_duplicate_members VALUES (100, 2)")
        conn.execute("INSERT INTO slide_duplicate_members VALUES (200, 3)")
        groups = get_affected_duplicate_groups(conn, [1, 3])
        assert sorted(groups) == [100, 200]

    def test_get_affected_duplicate_groups_empty(self):
        conn = _create_governance_db()
        groups = get_affected_duplicate_groups(conn, [])
        assert groups == []

    def test_get_affected_deck_families(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO presentation_versions VALUES (1, 50, 'latest', 1)")
        conn.execute("INSERT INTO presentation_versions VALUES (2, 50, 'older', 0)")
        conn.execute("INSERT INTO presentation_versions VALUES (3, 60, 'latest', 1)")
        families = get_affected_deck_families(conn, [1, 3])
        assert sorted(families) == [50, 60]

    def test_has_manual_override_duplicate(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO duplicate_groups (id, canonical_slide_id, source) VALUES (1, 1, 'manual')")
        assert has_manual_override(conn, "duplicate_group", 1) is True
        assert has_manual_override(conn, "duplicate_group", 999) is False

    def test_has_manual_override_family(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO deck_families (id, representative_presentation_id, source) VALUES (1, 1, 'manual')")
        assert has_manual_override(conn, "deck_family", 1) is True

    def test_compute_dry_run(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (1, 10)")
        conn.execute("INSERT INTO slide_duplicate_members VALUES (100, 1)")
        summary = compute_incremental_governance(conn, [1], dry_run=True)
        assert summary.affected_slides == 1
        assert summary.duplicate_groups_updated == 1

    def test_summary_to_json(self):
        s = GovernanceChangeSummary(
            affected_slides=5,
            duplicate_groups_updated=2,
            duplicate_groups_created=1,
            deck_families_updated=1,
            deck_families_created=0,
            representatives_changed=1,
            manual_overrides_preserved=0,
        )
        j = s.to_json()
        assert j["affected_slides"] == 5


class TestConsistencyValidation:
    def test_no_issues(self):
        conn = _create_governance_db()
        issues = validate_consistency(conn)
        assert len(issues) == 0

    def test_orphan_member(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO slide_duplicate_members VALUES (100, 999)")
        issues = validate_consistency(conn)
        assert any(i.issue_type == "orphan_member" for i in issues)

    def test_orphan_version(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO presentation_versions VALUES (999, 50, 'latest', 1)")
        issues = validate_consistency(conn)
        assert any(i.issue_type == "orphan_version" for i in issues)

    def test_empty_family(self):
        conn = _create_governance_db()
        conn.execute("INSERT INTO deck_families (id, representative_presentation_id) VALUES (50, NULL)")
        issues = validate_consistency(conn)
        assert any(i.issue_type == "empty_family" for i in issues)

    def test_issue_to_json(self):
        issue = ConsistencyIssue("orphan", "slide", 42, "test message")
        j = issue.to_json()
        assert j["issue_type"] == "orphan"
        assert j["entity_id"] == 42


# ---------------------------------------------------------------------------
# PPTX Safety tests (1.5-G)
# ---------------------------------------------------------------------------


class TestPptxSafety:
    def test_safe_pptx(self, tmp_path: Path):
        pptx = tmp_path / "safe.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types></Types>")
            zf.writestr("ppt/presentation.xml", "<presentation/>")
            zf.writestr("ppt/slides/slide1.xml", "<slide/>")
        report = check_pptx_safety(pptx)
        assert report.safe is True
        assert report.entry_count == 3
        assert len(report.issues) == 0

    def test_missing_file(self, tmp_path: Path):
        report = check_pptx_safety(tmp_path / "missing.pptx")
        assert report.safe is False
        assert any(i["code"] == "FILE_NOT_FOUND" for i in report.issues)

    def test_invalid_zip(self, tmp_path: Path):
        bad = tmp_path / "bad.pptx"
        bad.write_bytes(b"not a zip file")
        report = check_pptx_safety(bad)
        assert report.safe is False
        assert any(i["code"] == "PPTX_INVALID_ARCHIVE" for i in report.issues)

    def test_entry_count_limit(self, tmp_path: Path):
        pptx = tmp_path / "big.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            for i in range(50):
                zf.writestr(f"file{i}.txt", f"content {i}")
        report = check_pptx_safety(pptx, max_entries=10)
        assert report.safe is False
        assert any(i["code"] == "PPTX_ARCHIVE_LIMIT_EXCEEDED" for i in report.issues)

    def test_path_traversal(self, tmp_path: Path):
        pptx = tmp_path / "traversal.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("normal.txt", "ok")
            zf.writestr("../../../etc/passwd", "malicious")
        report = check_pptx_safety(pptx)
        assert report.safe is False
        assert any(i["code"] == "PPTX_PATH_TRAVERSAL_DETECTED" for i in report.issues)

    def test_external_relationships(self, tmp_path: Path):
        pptx = tmp_path / "external.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types></Types>")
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<Relationships>'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/external"/>'
                '</Relationships>',
            )
        report = check_pptx_safety(pptx)
        assert len(report.external_relationships) >= 1
        assert any(r["target"] == "https://example.com/external" for r in report.external_relationships)

    def test_report_to_json(self, tmp_path: Path):
        pptx = tmp_path / "safe.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("test.txt", "ok")
        report = check_pptx_safety(pptx)
        j = report.to_json()
        assert j["safe"] is True
        assert "entry_count" in j
