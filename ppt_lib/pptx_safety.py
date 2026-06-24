"""PPTX / Renderer safety: protect against malicious or malformed PPTX files.

Implements archive limits, path traversal protection, external relationship
inventory, and embedded object warnings.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Default security limits
MAX_ARCHIVE_ENTRIES = 20_000
MAX_UNCOMPRESSED_MB = 2_048
MAX_SINGLE_ENTRY_MB = 512
MAX_XML_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


@dataclass(frozen=True)
class PptxSafetyReport:
    """Safety assessment of a PPTX file."""

    path: str
    safe: bool
    entry_count: int
    total_uncompressed_bytes: int
    issues: list[dict[str, str]] = field(default_factory=list)
    external_relationships: list[dict[str, str]] = field(default_factory=list)
    embedded_objects: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "safe": self.safe,
            "entry_count": self.entry_count,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "issues": self.issues,
            "external_relationships": self.external_relationships,
            "embedded_objects": self.embedded_objects,
        }


def check_pptx_safety(
    path: Path,
    *,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_uncompressed_mb: int = MAX_UNCOMPRESSED_MB,
    max_single_entry_mb: int = MAX_SINGLE_ENTRY_MB,
) -> PptxSafetyReport:
    """Perform safety checks on a PPTX file.

    Returns a report with issues, external relationships, and embedded objects.
    """
    issues: list[dict[str, str]] = []
    external_rels: list[dict[str, str]] = []
    embedded_objs: list[dict[str, str]] = []

    if not path.is_file():
        return PptxSafetyReport(
            path=str(path),
            safe=False,
            entry_count=0,
            total_uncompressed_bytes=0,
            issues=[{"code": "FILE_NOT_FOUND", "message": f"File not found: {path}"}],
        )

    try:
        with zipfile.ZipFile(path, "r") as zf:
            entries = zf.infolist()
            entry_count = len(entries)

            # Check archive entry count
            if entry_count > max_entries:
                issues.append({
                    "code": "PPTX_ARCHIVE_LIMIT_EXCEEDED",
                    "message": f"Archive has {entry_count} entries (max: {max_entries})",
                })

            # Check total uncompressed size
            total_uncompressed = sum(e.file_size for e in entries)
            max_uncompressed_bytes = max_uncompressed_mb * 1024 * 1024
            if total_uncompressed > max_uncompressed_bytes:
                issues.append({
                    "code": "PPTX_ARCHIVE_LIMIT_EXCEEDED",
                    "message": f"Uncompressed size {total_uncompressed} bytes exceeds {max_uncompressed_mb} MB",
                })

            max_single_bytes = max_single_entry_mb * 1024 * 1024

            for entry in entries:
                # Check individual entry size
                if entry.file_size > max_single_bytes:
                    issues.append({
                        "code": "PPTX_ARCHIVE_LIMIT_EXCEEDED",
                        "message": f"Entry '{entry.filename}' is {entry.file_size} bytes (max: {max_single_bytes})",
                    })

                # Check path traversal
                if _is_path_traversal(entry.filename):
                    issues.append({
                        "code": "PPTX_PATH_TRAVERSAL_DETECTED",
                        "message": f"Entry '{entry.filename}' uses path traversal",
                    })

            # Check relationships for external targets
            for name in zf.namelist():
                if name.endswith(".rels"):
                    try:
                        rels_data = zf.read(name)
                        _scan_relationshiphips(rels_data, external_rels, embedded_objs, source_file=name)
                    except Exception:
                        pass

    except zipfile.BadZipFile:
        issues.append({
            "code": "PPTX_INVALID_ARCHIVE",
            "message": "File is not a valid ZIP archive",
        })
        return PptxSafetyReport(
            path=str(path),
            safe=False,
            entry_count=0,
            total_uncompressed_bytes=0,
            issues=issues,
        )

    safe = len(issues) == 0
    total_uncompressed = sum(e.file_size for e in entries) if "entries" in dir() else 0

    return PptxSafetyReport(
        path=str(path),
        safe=safe,
        entry_count=entry_count if "entry_count" in dir() else 0,
        total_uncompressed_bytes=total_uncompressed,
        issues=issues,
        external_relationships=external_rels,
        embedded_objects=embedded_objs,
    )


def _is_path_traversal(filename: str) -> bool:
    """Check if a filename uses path traversal."""
    if filename.startswith("/") or filename.startswith("\\"):
        return True
    if ".." in filename.split("/"):
        return True
    if ".." in filename.split("\\"):
        return True
    # Check for absolute Windows paths
    if len(filename) >= 2 and filename[1] == ":":
        return True
    return False


_REL_TARGET_PATTERN = re.compile(rb'Target="([^"]+)"')
_REL_TYPE_PATTERN = re.compile(rb'Type="([^"]+)"')


def _scan_relationshiphips(
    rels_xml: bytes,
    external_rels: list[dict[str, str]],
    embedded_objs: list[dict[str, str]],
    *,
    source_file: str = "",
) -> None:
    """Scan a .rels XML file for external targets and embedded objects."""
    # Split into individual Relationship elements
    rel_elements = re.findall(rb'<Relationship[^>]*>', rels_xml)
    for rel in rel_elements:
        target_match = _REL_TARGET_PATTERN.search(rel)
        type_match = _REL_TYPE_PATTERN.search(rel)

        if not target_match:
            continue

        target = target_match.group(1).decode("utf-8", errors="replace")
        rel_type = type_match.group(1).decode("utf-8", errors="replace") if type_match else ""

        # External relationships (http/https targets)
        if target.startswith("http://") or target.startswith("https://"):
            external_rels.append({
                "target": target,
                "type": rel_type,
                "source": source_file,
            })

        # Embedded objects (OLE, ActiveX, packages)
        if any(kw in rel_type.lower() for kw in ["oleobject", "activex", "package"]):
            embedded_objs.append({
                "target": target,
                "type": rel_type,
                "source": source_file,
            })

        # VBA macros
        if "vbaProject" in target or "vba" in rel_type.lower():
            external_rels.append({
                "target": target,
                "type": rel_type,
                "source": source_file,
                "warning": "VBA macro detected",
            })
