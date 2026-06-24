"""Layout and visual fingerprinting for slides (v1.7-B).

Extracts structural and visual fingerprints from PPTX slides:
normalized bounding boxes, media signals, palette, font, and pHash.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BoundingBox:
    """A normalized bounding box (0.0-1.0 coordinate space)."""

    x: float
    y: float
    width: float
    height: float
    shape_type: str  # "text" | "image" | "chart" | "table" | "group" | "other"

    def to_json(self) -> dict[str, object]:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "shape_type": self.shape_type,
        }


@dataclass(frozen=True)
class VisualFingerprint:
    """Complete visual fingerprint for a slide."""

    slide_revision_id: str
    algorithm_version: str
    box_count: int
    boxes: list[BoundingBox]
    has_images: bool
    has_charts: bool
    has_tables: bool
    text_density: float  # text area / total area
    media_hash: str | None
    palette_hash: str | None
    font_signals: list[str]
    phash: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "slide_revision_id": self.slide_revision_id,
            "algorithm_version": self.algorithm_version,
            "box_count": self.box_count,
            "boxes": [b.to_json() for b in self.boxes],
            "has_images": self.has_images,
            "has_charts": self.has_charts,
            "has_tables": self.has_tables,
            "text_density": round(self.text_density, 4),
            "media_hash": self.media_hash,
            "palette_hash": self.palette_hash,
            "font_signals": self.font_signals,
            "phash": self.phash,
        }


FINGERPRINT_VERSION = "visual-fingerprint-v1"

# OOXML namespaces
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# EMU to normalized factor (914400 EMU = 1 inch)
# Defaults are 4:3 standard (10x7.5 inch); actual size read from presentation.xml
_SLIDE_WIDTH_EMU = 914400 * 10  # 10-inch = 9144000 EMU
_SLIDE_HEIGHT_EMU = 6858000  # 7.5-inch = 6858000 EMU

# Regex to extract actual slide dimensions from ppt/presentation.xml
# Format: <p:sldSz cx="12192000" cy="6858000"/>
_SLDSZ_PATTERN = re.compile(
    rb'<p:sldSz\s+[^>]*cx="(\d+)"[^>]*cy="(\d+)"',
    re.IGNORECASE,
)


def _read_slide_dimensions(zf: zipfile.ZipFile) -> tuple[int, int]:
    """Read actual slide dimensions (EMU) from presentation.xml.

    Returns (width_emu, height_emu). Falls back to 10x7.5 inch default
    if the file is missing or unparseable.
    """
    try:
        pres_xml = zf.read("ppt/presentation.xml")
        match = _SLDSZ_PATTERN.search(pres_xml)
        if match:
            return int(match.group(1)), int(match.group(2))
    except (KeyError, OSError, ValueError):
        pass
    return _SLIDE_WIDTH_EMU, _SLIDE_HEIGHT_EMU


def extract_visual_fingerprint(
    pptx_path: Path,
    slide_index: int,
    *,
    slide_revision_id: str = "",
    algorithm_version: str = FINGERPRINT_VERSION,
) -> VisualFingerprint:
    """Extract a visual fingerprint from a specific slide in a PPTX file."""
    boxes: list[BoundingBox] = []
    has_images = False
    has_charts = False
    has_tables = False
    font_signals: list[str] = []
    media_parts: list[bytes] = []

    try:
        with zipfile.ZipFile(pptx_path, "r") as zf:
            slide_name = f"ppt/slides/slide{slide_index}.xml"
            try:
                slide_xml = zf.read(slide_name)
            except KeyError:
                return _empty_fingerprint(slide_revision_id, algorithm_version)

            # Read actual slide dimensions (handles 16:9 widescreen correctly)
            slide_w_emu, slide_h_emu = _read_slide_dimensions(zf)

            # Parse shapes from XML with actual slide dimensions
            boxes, has_images, has_charts, has_tables = _parse_shapes(
                slide_xml, slide_w_emu, slide_h_emu,
            )

            # Extract font signals
            font_signals = _extract_font_signals(slide_xml)

            # Hash media references
            rels_name = f"ppt/slides/_rels/slide{slide_index}.xml.rels"
            try:
                rels_xml = zf.read(rels_name)
                media_parts = _collect_media_data(zf, rels_xml)
            except KeyError:
                pass
    except (zipfile.BadZipFile, OSError):
        return _empty_fingerprint(slide_revision_id, algorithm_version)

    # Compute media hash
    media_hash = None
    if media_parts:
        hasher = hashlib.sha256()
        for part in sorted(media_parts, key=len):
            hasher.update(part)
        media_hash = hasher.hexdigest()[:16]

    # Compute text density
    text_density = _compute_text_density(boxes)

    # Palette and perceptual hash are placeholder (require rendered image)
    palette_hash = None
    phash = None

    return VisualFingerprint(
        slide_revision_id=slide_revision_id,
        algorithm_version=algorithm_version,
        box_count=len(boxes),
        boxes=boxes,
        has_images=has_images,
        has_charts=has_charts,
        has_tables=has_tables,
        text_density=text_density,
        media_hash=media_hash,
        palette_hash=palette_hash,
        font_signals=font_signals,
        phash=phash,
    )


def fingerprint_similarity(
    fp1: VisualFingerprint,
    fp2: VisualFingerprint,
) -> float:
    """Compute structural similarity between two fingerprints.

    Returns 0.0 (completely different) to 1.0 (identical structure).
    """
    score = 0.0
    weights_total = 0.0

    # Box count similarity
    if fp1.box_count > 0 or fp2.box_count > 0:
        max_boxes = max(fp1.box_count, fp2.box_count)
        box_sim = 1.0 - abs(fp1.box_count - fp2.box_count) / max_boxes
        score += box_sim * 0.2
        weights_total += 0.2

    # Media type overlap
    type_matches = sum([
        fp1.has_images == fp2.has_images,
        fp1.has_charts == fp2.has_charts,
        fp1.has_tables == fp2.has_tables,
    ])
    score += (type_matches / 3.0) * 0.3
    weights_total += 0.3

    # Text density similarity
    density_diff = abs(fp1.text_density - fp2.text_density)
    score += (1.0 - density_diff) * 0.2
    weights_total += 0.2

    # Font signal overlap
    if fp1.font_signals or fp2.font_signals:
        set1 = set(fp1.font_signals)
        set2 = set(fp2.font_signals)
        union = set1 | set2
        if union:
            jaccard = len(set1 & set2) / len(union)
            score += jaccard * 0.15
        weights_total += 0.15

    # Media hash match (exact)
    if fp1.media_hash and fp2.media_hash:
        if fp1.media_hash == fp2.media_hash:
            score += 0.15
        weights_total += 0.15

    return score / weights_total if weights_total > 0 else 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_fingerprint(slide_revision_id: str, algorithm_version: str) -> VisualFingerprint:
    return VisualFingerprint(
        slide_revision_id=slide_revision_id,
        algorithm_version=algorithm_version,
        box_count=0,
        boxes=[],
        has_images=False,
        has_charts=False,
        has_tables=False,
        text_density=0.0,
        media_hash=None,
        palette_hash=None,
        font_signals=[],
        phash=None,
    )


def _parse_shapes(
    slide_xml: bytes,
    slide_width_emu: int = _SLIDE_WIDTH_EMU,
    slide_height_emu: int = _SLIDE_HEIGHT_EMU,
) -> tuple[list[BoundingBox], bool, bool, bool]:
    """Parse shape bounding boxes from slide XML.

    Boxes are normalized using the actual slide dimensions (EMU), so 16:9
    widescreen and 4:3 decks produce correct 0.0-1.0 coordinates.
    """
    boxes: list[BoundingBox] = []
    has_images = False
    has_charts = False
    has_tables = False

    # Find sp (shape) elements with bounding boxes
    # Pattern: <p:sp>...<a:off x="..." y="..."/><a:ext cx="..." cy="..."/>...
    sp_pattern = re.compile(
        rb'<p:sp\b[^>]*>(.*?)</p:sp>',
        re.DOTALL,
    )
    off_pattern = re.compile(rb'<a:off\s+x=["\'](\d+)["\']\s+y=["\'](\d+)["\']')
    ext_pattern = re.compile(rb'<a:ext\s+cx=["\'](\d+)["\']\s+cy=["\'](\d+)["\']')

    for sp_match in sp_pattern.finditer(slide_xml):
        sp_body = sp_match.group(1)

        off = off_pattern.search(sp_body)
        ext = ext_pattern.search(sp_body)
        if not off or not ext:
            continue

        x_emu = int(off.group(1))
        y_emu = int(off.group(2))
        cx_emu = int(ext.group(1))
        cy_emu = int(ext.group(2))

        # Normalize to 0.0-1.0 using actual slide dimensions
        x = x_emu / slide_width_emu
        y = y_emu / slide_height_emu
        w = cx_emu / slide_width_emu
        h = cy_emu / slide_height_emu

        # Determine shape type
        shape_type = "other"
        if b"<a:blip" in sp_body or b"image" in sp_body.lower():
            shape_type = "text" if b"<a:t>" in sp_body else "image"
            if shape_type == "image":
                has_images = True
        elif b"<a:graphicFrame" in sp_body or b"chart" in sp_body.lower():
            shape_type = "chart"
            has_charts = True
        elif b"<a:tbl" in sp_body:
            shape_type = "table"
            has_tables = True
        elif b"<a:t>" in sp_body:
            shape_type = "text"

        boxes.append(BoundingBox(x=x, y=y, width=w, height=h, shape_type=shape_type))

    return boxes, has_images, has_charts, has_tables


def _extract_font_signals(slide_xml: bytes) -> list[str]:
    """Extract font family names from slide XML."""
    fonts: set[str] = set()
    # Match typeface="FontName"
    for match in re.finditer(rb'typeface=["\']([^"\']+)["\']', slide_xml):
        font_name = match.group(1).decode("utf-8", errors="replace")
        if font_name and not font_name.startswith("+"):
            fonts.add(font_name)
    return sorted(fonts)


def _collect_media_data(
    zf: zipfile.ZipFile,
    rels_xml: bytes,
) -> list[bytes]:
    """Collect media data referenced by slide relationships."""
    media_parts: list[bytes] = []
    targets = re.findall(rb'Target="([^"]+)"', rels_xml)
    for target in targets:
        target_str = target.decode("utf-8", errors="replace")
        if target_str.startswith("../media/"):
            media_path = "ppt/" + target_str[3:]
            try:
                data = zf.read(media_path)
                media_parts.append(data)
            except KeyError:
                pass
    return media_parts


def _compute_text_density(boxes: list[BoundingBox]) -> float:
    """Compute fraction of slide area covered by text boxes."""
    if not boxes:
        return 0.0
    text_area = sum(
        b.width * b.height for b in boxes if b.shape_type == "text"
    )
    return min(1.0, text_area)
