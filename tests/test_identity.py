"""Tests for stable asset identity and fingerprinting (1.5-D)."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from ppt_lib.identity import (
    FINGERPRINT_VERSION,
    compute_content_hash,
    compute_deck_revision_id,
    compute_file_content_hash,
    compute_slide_revision_id,
)
from ppt_lib.identity.fingerprint import _canonicalize_xml
from ppt_lib.identity.registry import (
    IdentityCoverageReport,
    export_identity_registry,
    get_identity_coverage,
    import_identity_registry,
    upsert_identity_mapping,
)

# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_canonicalize_xml_strips_modified_time(self):
        xml = b"<root><dcterms:modified>2026-01-01T00:00:00Z</dcterms:modified><body>text</body></root>"
        result = _canonicalize_xml(xml)
        assert b"dcterms:modified" not in result
        assert b"<body>text</body>" in result

    def test_canonicalize_xml_strips_created_time(self):
        xml = b"<root><dcterms:created>2026-01-01</dcterms:created></root>"
        result = _canonicalize_xml(xml)
        assert b"dcterms:created" not in result

    def test_canonicalize_xml_normalizes_whitespace(self):
        xml = b"<a>  </a>   <b>text</b>"
        result = _canonicalize_xml(xml)
        assert b"</a><b>" in result

    def test_compute_content_hash_deterministic(self):
        data = b"hello world"
        h1 = compute_content_hash(data)
        h2 = compute_content_hash(data)
        assert h1 == h2

    def test_compute_content_hash_different_input(self):
        h1 = compute_content_hash(b"hello")
        h2 = compute_content_hash(b"world")
        assert h1 != h2

    def test_compute_file_content_hash(self, tmp_path: Path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"test content")
        h = compute_file_content_hash(f)
        assert len(h) == 64  # SHA-256 hex

    def test_compute_slide_revision_id_from_pptx(self, tmp_path: Path):
        pptx = _create_minimal_pptx(tmp_path / "test.pptx", slides=2)
        rev1 = compute_slide_revision_id(pptx, 1)
        rev2 = compute_slide_revision_id(pptx, 2)
        assert rev1.startswith("srev_")
        assert rev2.startswith("srev_")
        # Different slides should have different revisions
        assert rev1 != rev2

    def test_slide_revision_id_deterministic(self, tmp_path: Path):
        pptx = _create_minimal_pptx(tmp_path / "test.pptx", slides=1)
        rev1 = compute_slide_revision_id(pptx, 1)
        rev2 = compute_slide_revision_id(pptx, 1)
        assert rev1 == rev2

    def test_deck_revision_id(self, tmp_path: Path):
        pptx = _create_minimal_pptx(tmp_path / "test.pptx", slides=3)
        rev = compute_deck_revision_id(pptx)
        assert rev.startswith("drev_")

    def test_deck_revision_id_deterministic(self, tmp_path: Path):
        pptx = _create_minimal_pptx(tmp_path / "test.pptx", slides=2)
        rev1 = compute_deck_revision_id(pptx)
        rev2 = compute_deck_revision_id(pptx)
        assert rev1 == rev2

    def test_slide_revision_id_handles_missing_file(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.pptx"
        # Should not raise, should return a fallback revision
        rev = compute_slide_revision_id(missing, 1)
        assert rev.startswith("srev_")

    def test_fingerprint_version(self):
        assert FINGERPRINT_VERSION == "slide-fingerprint-v1"


# ---------------------------------------------------------------------------
# Identity registry tests
# ---------------------------------------------------------------------------


class TestIdentityRegistry:
    def _create_db_with_identity_table(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY, presentation_id INTEGER)")
        conn.execute(
            """CREATE TABLE asset_identity_map (
                canonical_asset_id TEXT NOT NULL,
                slide_revision_id TEXT NOT NULL,
                legacy_slide_id INTEGER,
                identity_status TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (canonical_asset_id, slide_revision_id)
            )"""
        )
        return conn

    def test_upsert_and_get_identity(self):
        conn = self._create_db_with_identity_table()
        mapping = upsert_identity_mapping(
            conn,
            canonical_asset_id="asset_001",
            slide_revision_id="srev_abc123",
            legacy_slide_id=42,
            identity_status="resolved",
        )
        assert mapping.canonical_asset_id == "asset_001"
        assert mapping.slide_revision_id == "srev_abc123"
        assert mapping.legacy_slide_id == 42

        # Retrieve
        from ppt_lib.identity.registry import get_identity_by_revision
        found = get_identity_by_revision(conn, "srev_abc123")
        assert found is not None
        assert found.canonical_asset_id == "asset_001"

    def test_upsert_preserves_created_at(self):
        conn = self._create_db_with_identity_table()
        m1 = upsert_identity_mapping(
            conn, "asset_001", "srev_abc", 1, "resolved"
        )
        m2 = upsert_identity_mapping(
            conn, "asset_001", "srev_abc", 1, "needs_review"
        )
        assert m2.created_at == m1.created_at
        assert m2.identity_status == "needs_review"

    def test_get_identity_by_canonical(self):
        conn = self._create_db_with_identity_table()
        upsert_identity_mapping(conn, "asset_001", "srev_v1", 1, "resolved")
        upsert_identity_mapping(conn, "asset_001", "srev_v2", 2, "resolved")

        from ppt_lib.identity.registry import get_identity_by_canonical
        revisions = get_identity_by_canonical(conn, "asset_001")
        assert len(revisions) == 2

    def test_identity_coverage_empty(self):
        conn = self._create_db_with_identity_table()
        report = get_identity_coverage(conn)
        assert report.total_slides == 0
        assert report.resolved == 0
        assert report.unmapped == 0

    def test_identity_coverage_with_data(self):
        conn = self._create_db_with_identity_table()
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (1, 1)")
        conn.execute("INSERT INTO slides (id, presentation_id) VALUES (2, 1)")
        upsert_identity_mapping(conn, "a1", "srev_1", 1, "resolved")

        report = get_identity_coverage(conn)
        assert report.total_slides == 2
        assert report.resolved == 1
        assert report.unmapped == 1

    def test_export_identity_registry(self):
        conn = self._create_db_with_identity_table()
        upsert_identity_mapping(conn, "a1", "srev_1", 1, "resolved")
        upsert_identity_mapping(conn, "a2", "srev_2", 2, "needs_review")

        exported = export_identity_registry(conn)
        assert len(exported) == 2
        assert exported[0]["canonical_asset_id"] == "a1"

    def test_import_identity_registry(self):
        conn = self._create_db_with_identity_table()
        data = [
            {
                "canonical_asset_id": "a1",
                "slide_revision_id": "srev_1",
                "legacy_slide_id": 1,
                "identity_status": "resolved",
                "algorithm_version": "slide-fingerprint-v1",
            },
            {
                "canonical_asset_id": "a2",
                "slide_revision_id": "srev_2",
                "legacy_slide_id": 2,
                "identity_status": "needs_review",
                "algorithm_version": "slide-fingerprint-v1",
            },
        ]
        count = import_identity_registry(conn, data)
        assert count == 2

        # Verify imported
        from ppt_lib.identity.registry import get_identity_by_revision
        found = get_identity_by_revision(conn, "srev_1")
        assert found is not None
        assert found.identity_status == "resolved"

    def test_import_dry_run(self):
        conn = self._create_db_with_identity_table()
        data = [
            {
                "canonical_asset_id": "a1",
                "slide_revision_id": "srev_1",
                "legacy_slide_id": 1,
                "identity_status": "resolved",
            },
        ]
        count = import_identity_registry(conn, data, dry_run=True)
        assert count == 1

        # Should not be in DB
        from ppt_lib.identity.registry import get_identity_by_revision
        found = get_identity_by_revision(conn, "srev_1")
        assert found is None

    def test_coverage_report_to_json(self):
        report = IdentityCoverageReport(
            total_slides=100, resolved=80, needs_review=10,
            legacy_unresolved=5, unmapped=5,
        )
        j = report.to_json()
        assert j["coverage_pct"] == 80.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_pptx(path: Path, slides: int = 1) -> Path:
    """Create a minimal valid PPTX file for testing."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
        for i in range(1, slides + 1):
            zf.writestr(
                f"ppt/slides/slide{i}.xml",
                f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r>"
                f"<a:t>Slide {i} content</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>"
                f"</p:sld>",
            )
            zf.writestr(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',
            )
    return path
