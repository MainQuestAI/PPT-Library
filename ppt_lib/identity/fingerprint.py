"""Content fingerprinting for stable asset identity.

Generates deterministic revision IDs from PPTX content, excluding
volatile OOXML metadata (modified time, zip entry order, etc.).
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

FINGERPRINT_VERSION = "slide-fingerprint-v1"


def compute_slide_revision_id(
    pptx_path: Path,
    slide_index: int,
    *,
    algorithm_version: str = FINGERPRINT_VERSION,
) -> str:
    """Compute a deterministic revision ID for a specific slide.

    The fingerprint is based on canonicalized content, excluding
    volatile OOXML metadata.
    """
    hasher = hashlib.sha256()
    hasher.update(algorithm_version.encode("utf-8"))
    hasher.update(b"\x00")

    try:
        with zipfile.ZipFile(pptx_path, "r") as zf:
            # Canonicalize slide XML
            slide_xml = _read_slide_xml(zf, slide_index)
            if slide_xml:
                canonical = _canonicalize_xml(slide_xml)
                hasher.update(b"xml:")
                hasher.update(canonical)

            # Hash embedded media
            media_hashes = _collect_media_hashes(zf, slide_index)
            for media_hash in sorted(media_hashes):
                hasher.update(b"media:")
                hasher.update(media_hash)

            # Hash slide relationships
            rels_xml = _read_slide_rels(zf, slide_index)
            if rels_xml:
                canonical_rels = _canonicalize_xml(rels_xml)
                hasher.update(b"rels:")
                hasher.update(canonical_rels)
    except (zipfile.BadZipFile, KeyError, OSError):
        # Fallback: hash whatever we can read
        hasher.update(b"fallback:")
        try:
            hasher.update(str(pptx_path.stat().st_size).encode())
        except OSError:
            hasher.update(str(pptx_path).encode())

    digest = hasher.hexdigest()[:32]
    return f"srev_{digest}"


def compute_deck_revision_id(
    pptx_path: Path,
    *,
    algorithm_version: str = FINGERPRINT_VERSION,
) -> str:
    """Compute a deterministic revision ID for an entire deck."""
    hasher = hashlib.sha256()
    hasher.update(algorithm_version.encode("utf-8"))
    hasher.update(b"\x00")

    try:
        with zipfile.ZipFile(pptx_path, "r") as zf:
            # Hash all slide XMLs in sorted order
            slide_names = sorted(
                n for n in zf.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            for name in slide_names:
                xml = zf.read(name)
                canonical = _canonicalize_xml(xml)
                hasher.update(canonical)

            # Hash presentation.xml
            try:
                pres_xml = zf.read("ppt/presentation.xml")
                hasher.update(_canonicalize_xml(pres_xml))
            except KeyError:
                pass
    except (zipfile.BadZipFile, OSError):
        hasher.update(b"fallback:")
        try:
            hasher.update(str(pptx_path.stat().st_size).encode())
        except OSError:
            hasher.update(str(pptx_path).encode())

    digest = hasher.hexdigest()[:32]
    return f"drev_{digest}"


def compute_content_hash(data: bytes) -> str:
    """Compute a simple content hash for source change detection."""
    return hashlib.sha256(data).hexdigest()


def compute_file_content_hash(path: Path) -> str:
    """Compute content hash of a file, reading in chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# OOXML volatile patterns to strip
_VOLATILE_PATTERNS = [
    re.compile(rb'<dcterms:modified>[^<]*</dcterms:modified>'),
    re.compile(rb'<dcterms:created>[^<]*</dcterms:created>'),
    re.compile(rb'<cp:lastModifiedBy>[^<]*</cp:lastModifiedBy>'),
    re.compile(rb'<cp:revision>[^<]*</cp:revision>'),
    re.compile(rb'<mc:AlternateContent[^>]*>.*?</mc:AlternateContent>', re.DOTALL),
]


def _canonicalize_xml(xml: bytes) -> bytes:
    """Remove volatile OOXML metadata and normalize whitespace."""
    result = xml
    for pattern in _VOLATILE_PATTERNS:
        result = pattern.sub(b"", result)
    # Normalize whitespace between tags
    result = re.sub(rb">\s+<", b"><", result)
    return result


def _read_slide_xml(zf: zipfile.ZipFile, slide_index: int) -> bytes | None:
    """Read slide XML by index (1-based)."""
    name = f"ppt/slides/slide{slide_index}.xml"
    try:
        return zf.read(name)
    except KeyError:
        return None


def _read_slide_rels(zf: zipfile.ZipFile, slide_index: int) -> bytes | None:
    """Read slide relationships XML."""
    name = f"ppt/slides/_rels/slide{slide_index}.xml.rels"
    try:
        return zf.read(name)
    except KeyError:
        return None


def _collect_media_hashes(zf: zipfile.ZipFile, slide_index: int) -> list[bytes]:
    """Collect hashes of media files referenced by a slide."""
    hashes: list[bytes] = []
    # Check for slide-specific media
    rels_name = f"ppt/slides/_rels/slide{slide_index}.xml.rels"
    try:
        rels_xml = zf.read(rels_name)
        # Extract Target attributes from relationships
        targets = re.findall(rb'Target="([^"]+)"', rels_xml)
        for target in targets:
            target_str = target.decode("utf-8", errors="replace")
            if target_str.startswith("../media/"):
                media_path = "ppt/" + target_str[3:]  # ../media/ -> ppt/media/
                try:
                    media_data = zf.read(media_path)
                    h = hashlib.sha256(media_data).digest()[:16]
                    hashes.append(h)
                except KeyError:
                    pass
    except KeyError:
        pass
    return hashes
