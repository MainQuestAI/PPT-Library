"""Tests for visual fingerprinting (v1.7-B)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from ppt_lib.visual_fingerprint import (
    FINGERPRINT_VERSION,
    BoundingBox,
    VisualFingerprint,
    extract_visual_fingerprint,
    fingerprint_similarity,
)


def _make_pptx(path: Path, *, slide_xml: str = "", slides: int = 1) -> Path:
    """Create a minimal PPTX with custom slide XML."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        for i in range(1, slides + 1):
            if slide_xml:
                zf.writestr(f"ppt/slides/slide{i}.xml", slide_xml)
            else:
                zf.writestr(
                    f"ppt/slides/slide{i}.xml",
                    f"<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'>"
                    f"<p:cSld><p:spTree>"
                    f"<p:sp><p:nvSpPr><p:cNvPr id='{i}' name='TextBox'/></p:nvSpPr>"
                    f"<p:spPr>"
                    f"<a:xfrm xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
                    f"<a:off x='914400' y='914400'/>"
                    f"<a:ext cx='4572000' cy='1143000'/>"
                    f"</a:xfrm>"
                    f"</p:spPr>"
                    f"<p:txBody><a:p xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
                    f"<a:r><a:rPr><a:latin typeface='Arial'/></a:rPr>"
                    f"<a:t>Slide {i} text</a:t></a:r></a:p></p:txBody>"
                    f"</p:sp>"
                    f"</p:spTree></p:cSld></p:sld>",
                )
    return path


class TestBoundingBox:
    def test_to_json(self):
        b = BoundingBox(0.1, 0.2, 0.5, 0.3, "text")
        j = b.to_json()
        assert j["x"] == 0.1
        assert j["shape_type"] == "text"


class TestVisualFingerprint:
    def test_to_json(self):
        fp = VisualFingerprint(
            slide_revision_id="srev_1",
            algorithm_version="v1",
            box_count=2,
            boxes=[BoundingBox(0.1, 0.1, 0.5, 0.5, "text")],
            has_images=True,
            has_charts=False,
            has_tables=False,
            text_density=0.25,
            media_hash="abc123",
            palette_hash=None,
            font_signals=["Arial"],
            phash=None,
        )
        j = fp.to_json()
        assert j["slide_revision_id"] == "srev_1"
        assert j["has_images"] is True
        assert j["font_signals"] == ["Arial"]
        assert j["box_count"] == 2


class TestExtractFingerprint:
    def test_extract_from_pptx(self, tmp_path: Path):
        pptx = _make_pptx(tmp_path / "test.pptx")
        fp = extract_visual_fingerprint(pptx, 1, slide_revision_id="srev_1")
        assert fp.slide_revision_id == "srev_1"
        assert fp.algorithm_version == FINGERPRINT_VERSION
        assert fp.box_count >= 1
        assert any(b.shape_type == "text" for b in fp.boxes)

    def test_extract_font_signals(self, tmp_path: Path):
        pptx = _make_pptx(tmp_path / "test.pptx")
        fp = extract_visual_fingerprint(pptx, 1)
        assert "Arial" in fp.font_signals

    def test_missing_file(self, tmp_path: Path):
        fp = extract_visual_fingerprint(tmp_path / "missing.pptx", 1)
        assert fp.box_count == 0
        assert fp.slide_revision_id == ""

    def test_missing_slide(self, tmp_path: Path):
        pptx = _make_pptx(tmp_path / "test.pptx", slides=1)
        fp = extract_visual_fingerprint(pptx, 99)
        assert fp.box_count == 0

    def test_deterministic(self, tmp_path: Path):
        pptx = _make_pptx(tmp_path / "test.pptx")
        fp1 = extract_visual_fingerprint(pptx, 1)
        fp2 = extract_visual_fingerprint(pptx, 1)
        assert fp1.box_count == fp2.box_count
        assert fp1.text_density == fp2.text_density

    def test_text_density(self, tmp_path: Path):
        pptx = _make_pptx(tmp_path / "test.pptx")
        fp = extract_visual_fingerprint(pptx, 1)
        assert 0.0 <= fp.text_density <= 1.0

    def test_empty_slide(self, tmp_path: Path):
        pptx = _make_pptx(
            tmp_path / "empty.pptx",
            slide_xml="<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'><p:cSld><p:spTree></p:spTree></p:cSld></p:sld>",
        )
        fp = extract_visual_fingerprint(pptx, 1)
        assert fp.box_count == 0
        assert fp.text_density == 0.0


class TestFingerprintSimilarity:
    def test_identical(self):
        fp = VisualFingerprint(
            "s1", "v1", 3,
            [BoundingBox(0.1, 0.1, 0.5, 0.5, "text")],
            True, False, False, 0.25, "hash", None, ["Arial"], None,
        )
        assert fingerprint_similarity(fp, fp) == 1.0

    def test_completely_different(self):
        fp1 = VisualFingerprint(
            "s1", "v1", 1,
            [BoundingBox(0, 0, 1, 1, "text")],
            False, False, False, 1.0, None, None, ["Arial"], None,
        )
        fp2 = VisualFingerprint(
            "s2", "v1", 5,
            [BoundingBox(0, 0, 0.2, 0.2, "image")] * 5,
            True, True, True, 0.0, "different", None, ["Times"], None,
        )
        sim = fingerprint_similarity(fp1, fp2)
        assert sim < 0.5

    def test_similar_structure(self):
        fp1 = VisualFingerprint(
            "s1", "v1", 3,
            [BoundingBox(0.1, 0.1, 0.4, 0.4, "text")] * 3,
            True, False, False, 0.3, "hash", None, ["Arial", "Calibri"], None,
        )
        fp2 = VisualFingerprint(
            "s2", "v1", 3,
            [BoundingBox(0.1, 0.1, 0.4, 0.4, "text")] * 3,
            True, False, False, 0.3, "hash", None, ["Arial"], None,
        )
        sim = fingerprint_similarity(fp1, fp2)
        assert sim > 0.7

    def test_empty_fingerprints(self):
        fp1 = VisualFingerprint("s1", "v1", 0, [], False, False, False, 0.0, None, None, [], None)
        fp2 = VisualFingerprint("s2", "v1", 0, [], False, False, False, 0.0, None, None, [], None)
        # Both empty — types match, density matches
        sim = fingerprint_similarity(fp1, fp2)
        assert sim >= 0.0
