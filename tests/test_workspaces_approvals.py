"""Tests for workspaces (v2.0-B) and approvals (v2.0-D)."""

from __future__ import annotations

import sqlite3

from ppt_lib.approvals import (
    ApprovalStatus,
    ReviewRequest,
    ReviewType,
    approve_request,
    create_review_request,
    get_pending_requests,
    get_request,
    get_review_summary,
    reject_request,
    revoke_request,
)
from ppt_lib.workspaces import (
    Workspace,
    add_member,
    check_workspace_access,
    create_workspace,
    get_members,
    get_workspace,
    list_workspaces,
    remove_member,
)


def _create_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


# --- Workspace tests ---

class TestWorkspace:
    def test_to_json(self):
        ws = Workspace("ws1", "Test", "desc", "2026-01-01", "u1")
        j = ws.to_json()
        assert j["workspace_id"] == "ws1"
        assert j["name"] == "Test"


class TestCreateWorkspace:
    def test_create(self):
        conn = _create_db()
        ws = create_workspace(conn, "My Workspace", owner_user_id="u1")
        assert ws.name == "My Workspace"
        assert ws.workspace_id.startswith("ws_")
        assert ws.owner_user_id == "u1"

    def test_create_adds_owner_as_member(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test", owner_user_id="u1")
        role = check_workspace_access(conn, ws.workspace_id, "u1")
        assert role == "owner"


class TestListWorkspaces:
    def test_list_empty(self):
        conn = _create_db()
        wss = list_workspaces(conn)
        assert len(wss) == 0

    def test_list_multiple(self):
        conn = _create_db()
        create_workspace(conn, "WS1")
        create_workspace(conn, "WS2")
        wss = list_workspaces(conn)
        assert len(wss) == 2


class TestGetWorkspace:
    def test_get_existing(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        found = get_workspace(conn, ws.workspace_id)
        assert found is not None
        assert found.name == "Test"

    def test_get_missing(self):
        conn = _create_db()
        assert get_workspace(conn, "nonexistent") is None


class TestMembership:
    def test_add_member(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        assert add_member(conn, ws.workspace_id, "u2", role="editor") is True

    def test_add_duplicate_member(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        add_member(conn, ws.workspace_id, "u2")
        assert add_member(conn, ws.workspace_id, "u2") is False

    def test_remove_member(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        add_member(conn, ws.workspace_id, "u2")
        assert remove_member(conn, ws.workspace_id, "u2") is True

    def test_remove_nonexistent(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        assert remove_member(conn, ws.workspace_id, "u99") is False

    def test_get_members(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test", owner_user_id="u1")
        add_member(conn, ws.workspace_id, "u2", role="editor")
        members = get_members(conn, ws.workspace_id)
        assert len(members) == 2

    def test_check_access(self):
        conn = _create_db()
        ws = create_workspace(conn, "Test")
        add_member(conn, ws.workspace_id, "u2", role="editor")
        assert check_workspace_access(conn, ws.workspace_id, "u2") == "editor"
        assert check_workspace_access(conn, ws.workspace_id, "u99") is None


# --- Approval tests ---

class TestReviewRequest:
    def test_to_json(self):
        r = ReviewRequest("r1", ReviewType.EXPORT, "a1", "u1",
            ApprovalStatus.PENDING, "need export", "now")
        j = r.to_json()
        assert j["review_type"] == "export"
        assert j["status"] == "pending"


class TestCreateReviewRequest:
    def test_create(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1", reason="test")
        assert req.request_id.startswith("rev_")
        assert req.status == ApprovalStatus.PENDING
        assert req.review_type == ReviewType.EXPORT


class TestApproveReject:
    def test_approve(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        assert approve_request(conn, req.request_id, "admin1", comment="LGTM") is True
        found = get_request(conn, req.request_id)
        assert found.status == ApprovalStatus.APPROVED
        assert found.reviewer_id == "admin1"

    def test_reject(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.DELETE, "a1", "u1")
        assert reject_request(conn, req.request_id, "admin1", comment="No") is True
        found = get_request(conn, req.request_id)
        assert found.status == ApprovalStatus.REJECTED

    def test_approve_nonexistent(self):
        conn = _create_db()
        assert approve_request(conn, "nonexistent", "admin1") is False

    def test_approve_already_approved(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        approve_request(conn, req.request_id, "admin1")
        assert approve_request(conn, req.request_id, "admin2") is False


class TestRevoke:
    def test_revoke_approved(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        approve_request(conn, req.request_id, "admin1")
        assert revoke_request(conn, req.request_id) is True
        found = get_request(conn, req.request_id)
        assert found.status == ApprovalStatus.REVOKED

    def test_revoke_pending(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        assert revoke_request(conn, req.request_id) is False


class TestGetPendingRequests:
    def test_get_pending(self):
        conn = _create_db()
        create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        create_review_request(conn, ReviewType.DELETE, "a2", "u2")
        pending = get_pending_requests(conn)
        assert len(pending) == 2

    def test_filter_by_type(self):
        conn = _create_db()
        create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        create_review_request(conn, ReviewType.DELETE, "a2", "u2")
        pending = get_pending_requests(conn, review_type=ReviewType.EXPORT)
        assert len(pending) == 1

    def test_excludes_approved(self):
        conn = _create_db()
        req = create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        approve_request(conn, req.request_id, "admin1")
        pending = get_pending_requests(conn)
        assert len(pending) == 0


class TestReviewSummary:
    def test_empty(self):
        conn = _create_db()
        summary = get_review_summary(conn)
        assert summary["total"] == 0

    def test_with_requests(self):
        conn = _create_db()
        create_review_request(conn, ReviewType.EXPORT, "a1", "u1")
        req = create_review_request(conn, ReviewType.DELETE, "a2", "u2")
        approve_request(conn, req.request_id, "admin1")
        summary = get_review_summary(conn)
        assert summary["total"] == 2
        assert summary["by_status"]["pending"] == 1
        assert summary["by_status"]["approved"] == 1
