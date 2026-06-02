from __future__ import annotations

import os
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException

SLIDE_PART_PATTERN = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
SLIDE_MASTER_PART_PATTERN = re.compile(r"^ppt/slideMasters/slideMaster[\w.-]*\.xml$")
OFFICE_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
SLIDE_RELATIONSHIP_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
OFFICE_DOCUMENT_RELATIONSHIP_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
PRESENTATION_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
SLIDE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CONTENT_TYPE_DEFAULT_TAG = f"{{{CONTENT_TYPES_NS}}}Default"
CONTENT_TYPE_OVERRIDE_TAG = f"{{{CONTENT_TYPES_NS}}}Override"
URI_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
RISK_TAGS_BY_PART_PREFIX = (
    ("ppt/charts/", "chart"),
    ("ppt/embeddings/", "embedded_object"),
    ("ppt/diagrams/", "smartart_or_diagram"),
    ("ppt/slideLayouts/", "slide_layout"),
    ("ppt/slideMasters/", "slide_master"),
    ("ppt/theme/", "theme"),
)
MAX_OUTPUT_PART_NAME_ATTEMPTS = 10_000
DEFAULT_OUTPUT_SLIDE_CX = 12_192_000
DEFAULT_OUTPUT_SLIDE_CY = 6_858_000
ASPECT_RATIO_TOLERANCE = 0.005

ElementTree.register_namespace("", RELATIONSHIP_NS)
ElementTree.register_namespace("p", PRESENTATION_NS)
ElementTree.register_namespace("a", DRAWING_NS)
ElementTree.register_namespace("r", OFFICE_RELATIONSHIP_NS)


class PptxPackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CopiedSlide:
    source_file: Path
    source_page_number: int
    output_page_number: int
    status: str
    risk_tags: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class PptxPackage:
    path: Path
    _parts: frozenset[str]
    _slide_parts: tuple[str | None, ...]

    @classmethod
    def open(cls, path: Path, *, strict: bool = True) -> PptxPackage:
        package_path = Path(path)
        if not package_path.exists():
            raise PptxPackageError(f"PPTX package does not exist: {package_path}")
        try:
            with zipfile.ZipFile(package_path) as archive:
                parts = frozenset(archive.namelist())
                bad_part = archive.testzip()
        except (OSError, zipfile.BadZipFile) as exc:
            raise PptxPackageError(f"PPTX package is not a readable zip: {package_path}") from exc
        if bad_part is not None:
            raise PptxPackageError(f"PPTX package is not a readable zip: {package_path}; bad part: {bad_part}")

        return cls(
            path=package_path,
            _parts=parts,
            _slide_parts=_index_slide_parts(package_path, parts, strict=strict),
        )

    def slide_part(self, page_number: int) -> str:
        page_index = _page_index(page_number)
        try:
            slide_part = self._slide_parts[page_index]
        except IndexError as exc:
            raise PptxPackageError(f"PPTX package has no slide/page {page_number}: {self.path}") from exc
        if slide_part is None:
            raise PptxPackageError(f"PPTX slide/page {page_number} is not usable from presentation relationships: {self.path}")
        return slide_part

    def slide_relationship_part(self, page_number: int) -> str | None:
        slide_part = self.slide_part(page_number)
        rels_part = _relationship_part_for(slide_part)
        if rels_part not in self._parts:
            return None
        return rels_part

    def read_part(self, part_name: str) -> bytes:
        if part_name not in self._parts:
            raise PptxPackageError(f"PPTX package has no part: {part_name}")
        try:
            with zipfile.ZipFile(self.path) as archive:
                return archive.read(part_name)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise PptxPackageError(f"Cannot read PPTX part: {part_name}") from exc

    def contains_part(self, part_name: str) -> bool:
        return part_name in self._parts

    def list_parts(self) -> tuple[str, ...]:
        return tuple(sorted(self._parts))


@dataclass
class _CopiedSlideDraft:
    source_file: Path
    source_page_number: int
    output_page_number: int
    risk_tags: list[str]
    warnings: list[str]


@dataclass
class _ContentTypeIndex:
    defaults: dict[str, str]
    overrides: dict[str, str]


@dataclass(frozen=True)
class _PartReuseSignature:
    relationships: bytes | None
    content_type: str | None


@dataclass(frozen=True)
class _SlideSize:
    cx: int
    cy: int
    slide_type: str | None = None


def copy_slides_to_new_pptx(slides: list[tuple[Path, int]], output_path: Path) -> list[CopiedSlide]:
    output_path = Path(output_path)
    resolved_output_path = output_path.resolve()
    slide_copies: list[tuple[PptxPackage, str, str, bytes, _CopiedSlideDraft]] = []
    output_parts: dict[str, bytes] = {}
    output_part_signatures: dict[str, _PartReuseSignature] = {}
    output_relationship_parts: dict[str, bytes] = {}
    copied_part_names: dict[tuple[Path, str], str] = {}
    content_type_indexes: dict[Path, _ContentTypeIndex] = {}
    content_type_defaults: dict[str, str] = {}
    content_type_overrides: dict[str, str] = {}
    reserved_parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }

    # --- Phase 1: collect source slide sizes to determine output canvas ---
    source_sizes: list[_SlideSize | None] = []
    for source_file, _source_page_number in slides:
        source_path = Path(source_file)
        package = PptxPackage.open(source_path, strict=False)
        source_sizes.append(_presentation_slide_size(package))

    output_slide_size = _determine_output_slide_size(source_sizes)

    # --- Phase 2: copy slides with correct canvas ---
    for output_page_number, (source_file, source_page_number) in enumerate(slides, start=1):
        source_path = Path(source_file)
        if resolved_output_path == source_path.resolve():
            raise PptxPackageError(f"Cannot write output PPTX over source PPTX: output={output_path} source={source_path}")
        package = PptxPackage.open(source_path, strict=False)
        if output_path.exists() and os.path.samefile(output_path, source_path):
            raise PptxPackageError(f"Cannot write output PPTX over source PPTX: output={output_path} source={source_path}")
        slide_part = package.slide_part(source_page_number)
        source_slide_size = _presentation_slide_size(package)
        output_slide_part = f"ppt/slides/slide{output_page_number}.xml"
        reserved_parts.add(output_slide_part)
        draft = _CopiedSlideDraft(
            source_file=source_path,
            source_page_number=source_page_number,
            output_page_number=output_page_number,
            risk_tags=[],
            warnings=[],
        )
        # Tag slides that have a different aspect ratio from the output canvas
        if source_slide_size is not None and not _same_aspect_ratio(source_slide_size, output_slide_size):
            draft.risk_tags.append("aspect_ratio_mismatch")
            draft.warnings.append(
                f"Source slide aspect ratio ({source_slide_size.cx}x{source_slide_size.cy}) "
                f"differs from output canvas ({output_slide_size.cx}x{output_slide_size.cy})"
            )
        slide_xml = _normalize_slide_xml_to_output_canvas(package.read_part(slide_part), source_slide_size, output_slide_size)
        slide_copies.append((package, slide_part, output_slide_part, slide_xml, draft))

    for package, source_slide_part, output_slide_part, slide_xml, draft in slide_copies:
        output_parts[output_slide_part] = slide_xml
        source_key = (package.path.resolve(), source_slide_part)
        copied_part_names[source_key] = output_slide_part
        _copy_relationships_for_part(
            package=package,
            source_part=source_slide_part,
            output_part=output_slide_part,
            output_parts=output_parts,
            output_part_signatures=output_part_signatures,
            output_relationship_parts=output_relationship_parts,
            copied_part_names=copied_part_names,
            content_type_indexes=content_type_indexes,
            content_type_defaults=content_type_defaults,
            content_type_overrides=content_type_overrides,
            reserved_parts=reserved_parts,
            risk_tags=draft.risk_tags,
            warnings=draft.warnings,
        )

    copied = [
        CopiedSlide(
            source_file=draft.source_file,
            source_page_number=draft.source_page_number,
            output_page_number=draft.output_page_number,
            status="copied",
            risk_tags=draft.risk_tags,
            warnings=draft.warnings,
        )
        for _, _, _, _, draft in slide_copies
    ]

    try:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types_xml(len(slide_copies), content_type_defaults, content_type_overrides))
            archive.writestr("_rels/.rels", _root_rels_xml())
            slide_master_parts = _output_slide_master_parts(output_parts)
            archive.writestr("ppt/presentation.xml", _presentation_xml(len(slide_copies), slide_master_parts, output_slide_size))
            archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels_xml(len(slide_copies), slide_master_parts))
            for part_name, part_bytes in sorted(output_parts.items()):
                archive.writestr(part_name, part_bytes)
            for part_name, part_bytes in sorted(output_relationship_parts.items()):
                archive.writestr(part_name, part_bytes)
    except OSError as exc:
        raise PptxPackageError(f"Cannot write PPTX package: {output_path}") from exc

    return copied


def _copy_relationships_for_part(
    *,
    package: PptxPackage,
    source_part: str,
    output_part: str,
    output_parts: dict[str, bytes],
    output_part_signatures: dict[str, _PartReuseSignature],
    output_relationship_parts: dict[str, bytes],
    copied_part_names: dict[tuple[Path, str], str],
    content_type_indexes: dict[Path, _ContentTypeIndex],
    content_type_defaults: dict[str, str],
    content_type_overrides: dict[str, str],
    reserved_parts: set[str],
    risk_tags: list[str],
    warnings: list[str],
) -> None:
    source_rels_part = _relationship_part_for(source_part)
    if not package.contains_part(source_rels_part):
        return

    try:
        relationships = _parse_xml(package.read_part(source_rels_part))
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise PptxPackageError(f"Cannot parse PPTX relationship part: {source_rels_part}") from exc

    for relationship in list(relationships):
        if _local_name(relationship.tag) != "Relationship":
            continue

        target = relationship.attrib.get("Target")
        if not target:
            continue

        if relationship.attrib.get("TargetMode") == "External":
            _add_unique(risk_tags, "external_relationship")
            continue

        if not _is_internal_relationship_target(target):
            continue

        target_part = _relationship_target_part(source_part, target)
        if not package.contains_part(target_part):
            _add_unique(risk_tags, "missing_relationship_target")
            warnings.append(f"Relationship target is missing and was left unchanged: {source_rels_part} -> {target}")
            continue

        output_target_part = _copy_related_part(
            package=package,
            source_part=target_part,
            output_parts=output_parts,
            output_part_signatures=output_part_signatures,
            output_relationship_parts=output_relationship_parts,
            copied_part_names=copied_part_names,
            content_type_indexes=content_type_indexes,
            content_type_defaults=content_type_defaults,
            content_type_overrides=content_type_overrides,
            reserved_parts=reserved_parts,
            risk_tags=risk_tags,
            warnings=warnings,
        )
        relationship.attrib["Target"] = _relative_target(output_part, output_target_part)

    output_rels_part = _relationship_part_for(output_part)
    output_relationship_parts[output_rels_part] = ElementTree.tostring(relationships, encoding="utf-8", xml_declaration=False)


def _copy_related_part(
    *,
    package: PptxPackage,
    source_part: str,
    output_parts: dict[str, bytes],
    output_part_signatures: dict[str, _PartReuseSignature],
    output_relationship_parts: dict[str, bytes],
    copied_part_names: dict[tuple[Path, str], str],
    content_type_indexes: dict[Path, _ContentTypeIndex],
    content_type_defaults: dict[str, str],
    content_type_overrides: dict[str, str],
    reserved_parts: set[str],
    risk_tags: list[str],
    warnings: list[str],
) -> str:
    source_key = (package.path.resolve(), source_part)
    existing_output_part = copied_part_names.get(source_key)
    if existing_output_part is not None:
        _record_risk_tags_for_part(existing_output_part, risk_tags)
        return existing_output_part

    part_bytes = package.read_part(source_part)
    signature = _part_reuse_signature(package, source_part, content_type_indexes)
    output_part = _unique_output_part_name(source_part, part_bytes, signature, output_parts, output_part_signatures, reserved_parts)
    copied_part_names[source_key] = output_part
    _record_risk_tags_for_part(output_part, risk_tags)
    if output_part not in output_parts:
        output_parts[output_part] = part_bytes
        output_part_signatures[output_part] = signature
        reserved_parts.add(output_part)
        _record_content_type(
            package=package,
            source_part=source_part,
            output_part=output_part,
            content_type_indexes=content_type_indexes,
            content_type_defaults=content_type_defaults,
            content_type_overrides=content_type_overrides,
        )
        _copy_relationships_for_part(
            package=package,
            source_part=source_part,
            output_part=output_part,
            output_parts=output_parts,
            output_part_signatures=output_part_signatures,
            output_relationship_parts=output_relationship_parts,
            copied_part_names=copied_part_names,
            content_type_indexes=content_type_indexes,
            content_type_defaults=content_type_defaults,
            content_type_overrides=content_type_overrides,
            reserved_parts=reserved_parts,
            risk_tags=risk_tags,
            warnings=warnings,
        )
    return output_part


def _index_slide_parts(path: Path, parts: frozenset[str], *, strict: bool) -> tuple[str | None, ...]:
    if "ppt/presentation.xml" in parts and "ppt/_rels/presentation.xml.rels" in parts:
        return _index_slide_parts_from_presentation(path, parts, strict=strict)
    return tuple(sorted((part for part in parts if SLIDE_PART_PATTERN.fullmatch(part)), key=_slide_number))


def _index_slide_parts_from_presentation(path: Path, parts: frozenset[str], *, strict: bool) -> tuple[str | None, ...]:
    try:
        with zipfile.ZipFile(path) as archive:
            presentation = _parse_xml(archive.read("ppt/presentation.xml"))
            rels = _parse_xml(archive.read("ppt/_rels/presentation.xml.rels"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError, DefusedXmlException) as exc:
        raise PptxPackageError(f"Cannot index PPTX slides from presentation relationships: {path}") from exc

    relationships_by_id = {
        relationship.attrib.get("Id"): relationship.attrib
        for relationship in rels.findall(f"{{{RELATIONSHIP_NS}}}Relationship")
        if relationship.attrib.get("Id")
    }
    slide_parts: list[str | None] = []
    for page_number, slide_id in enumerate(presentation.findall(".//{*}sldId"), start=1):
        relationship_id = slide_id.attrib.get(f"{{{OFFICE_RELATIONSHIP_NS}}}id")
        if not relationship_id:
            if strict:
                raise PptxPackageError(f"PPTX slide/page {page_number} is missing presentation relationship id: {path}")
            slide_parts.append(None)
            continue

        relationship = relationships_by_id.get(relationship_id)
        if relationship is None:
            if strict:
                raise PptxPackageError(f"PPTX slide/page {page_number} references missing relationship: {relationship_id}")
            slide_parts.append(None)
            continue

        relationship_type = relationship.get("Type")
        if relationship_type != SLIDE_RELATIONSHIP_TYPE:
            if strict:
                raise PptxPackageError(
                    f"PPTX slide/page {page_number} relationship {relationship_id} is not a slide relationship: {relationship_type}"
                )
            slide_parts.append(None)
            continue

        target = relationship.get("Target")
        if not target:
            if strict:
                raise PptxPackageError(f"PPTX slide/page {page_number} relationship {relationship_id} is missing target.")
            slide_parts.append(None)
            continue

        slide_part = _normalize_part("ppt", target)
        if not SLIDE_PART_PATTERN.fullmatch(slide_part):
            if strict:
                raise PptxPackageError(
                    f"PPTX slide/page {page_number} relationship {relationship_id} points to non-slide part: {slide_part}"
                )
            slide_parts.append(None)
            continue
        if slide_part not in parts:
            if strict:
                raise PptxPackageError(f"PPTX slide/page {page_number} relationship {relationship_id} target is missing: {slide_part}")
            slide_parts.append(None)
            continue
        slide_parts.append(slide_part)
    return tuple(slide_parts)


def _normalize_part(base_dir: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def _slide_number(part_name: str) -> int:
    match = SLIDE_PART_PATTERN.fullmatch(part_name)
    if match is None:
        raise PptxPackageError(f"Invalid slide part name: {part_name}")
    return int(match.group(1))


def _relationship_part_for(part_name: str) -> str:
    directory, name = part_name.rsplit("/", 1)
    return f"{directory}/_rels/{name}.rels"


def _unique_output_part_name(
    source_part: str,
    part_bytes: bytes,
    signature: _PartReuseSignature,
    output_parts: dict[str, bytes],
    output_part_signatures: dict[str, _PartReuseSignature],
    reserved_parts: set[str],
) -> str:
    existing_bytes = output_parts.get(source_part)
    if existing_bytes == part_bytes and output_part_signatures.get(source_part) == signature:
        return source_part
    if source_part not in reserved_parts and source_part not in output_parts:
        return source_part

    stem, extension = posixpath.splitext(source_part)
    suffix = 2
    for _ in range(MAX_OUTPUT_PART_NAME_ATTEMPTS):
        candidate = f"{stem}_{suffix}{extension}"
        existing_candidate_bytes = output_parts.get(candidate)
        if existing_candidate_bytes == part_bytes and output_part_signatures.get(candidate) == signature:
            return candidate
        if candidate not in reserved_parts and candidate not in output_parts:
            return candidate
        suffix += 1
    raise PptxPackageError(f"Cannot find unique output part name for: {source_part}")


def _part_reuse_signature(
    package: PptxPackage,
    source_part: str,
    content_type_indexes: dict[Path, _ContentTypeIndex],
) -> _PartReuseSignature:
    rels_part = _relationship_part_for(source_part)
    relationships = package.read_part(rels_part) if package.contains_part(rels_part) else None
    return _PartReuseSignature(
        relationships=relationships,
        content_type=_part_content_type(package, source_part, content_type_indexes),
    )


def _record_risk_tags_for_part(part_name: str, risk_tags: list[str]) -> None:
    for prefix, risk_tag in RISK_TAGS_BY_PART_PREFIX:
        if part_name.startswith(prefix):
            _add_unique(risk_tags, risk_tag)


def _is_internal_relationship_target(target: str) -> bool:
    return URI_SCHEME_PATTERN.match(target) is None


def _relationship_target_part(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target).lstrip("/")
    return _normalize_part(posixpath.dirname(source_part), target)


def _relative_target(from_part: str, to_part: str) -> str:
    return posixpath.relpath(to_part, posixpath.dirname(from_part))


def _add_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _record_content_type(
    *,
    package: PptxPackage,
    source_part: str,
    output_part: str,
    content_type_indexes: dict[Path, _ContentTypeIndex],
    content_type_defaults: dict[str, str],
    content_type_overrides: dict[str, str],
) -> None:
    index = _content_type_index(package, content_type_indexes)
    source_override = index.overrides.get(source_part)
    if source_override is not None:
        content_type_overrides[output_part] = source_override
        return

    extension = _part_extension(source_part)
    content_type = index.defaults.get(extension)
    if content_type is None:
        return
    if not extension:
        content_type_overrides[output_part] = content_type
        return

    existing_default = content_type_defaults.get(extension)
    if existing_default is None:
        content_type_defaults[extension] = content_type
    elif existing_default != content_type:
        content_type_overrides[output_part] = content_type


def _part_content_type(
    package: PptxPackage,
    source_part: str,
    content_type_indexes: dict[Path, _ContentTypeIndex],
) -> str | None:
    index = _content_type_index(package, content_type_indexes)
    source_override = index.overrides.get(source_part)
    if source_override is not None:
        return source_override
    return index.defaults.get(_part_extension(source_part))


def _content_type_index(package: PptxPackage, content_type_indexes: dict[Path, _ContentTypeIndex]) -> _ContentTypeIndex:
    package_key = package.path.resolve()
    existing_index = content_type_indexes.get(package_key)
    if existing_index is not None:
        return existing_index

    if not package.contains_part("[Content_Types].xml"):
        index = _ContentTypeIndex(defaults={}, overrides={})
        content_type_indexes[package_key] = index
        return index

    try:
        content_types = _parse_xml(package.read_part("[Content_Types].xml"))
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise PptxPackageError(f"Cannot parse PPTX content types: {package.path}") from exc

    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for child in list(content_types):
        if child.tag == CONTENT_TYPE_DEFAULT_TAG:
            extension = child.attrib.get("Extension")
            content_type = child.attrib.get("ContentType")
            if extension and content_type:
                defaults[extension] = content_type
        elif child.tag == CONTENT_TYPE_OVERRIDE_TAG:
            part_name = child.attrib.get("PartName")
            content_type = child.attrib.get("ContentType")
            if part_name and content_type:
                overrides[part_name.lstrip("/")] = content_type

    index = _ContentTypeIndex(defaults=defaults, overrides=overrides)
    content_type_indexes[package_key] = index
    return index


def _part_extension(part_name: str) -> str:
    return posixpath.splitext(part_name)[1].lstrip(".")


def _presentation_slide_size(package: PptxPackage) -> _SlideSize | None:
    if not package.contains_part("ppt/presentation.xml"):
        return None
    try:
        presentation = _parse_xml(package.read_part("ppt/presentation.xml"))
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise PptxPackageError(f"Cannot parse PPTX presentation size: {package.path}") from exc
    slide_size = presentation.find(f"{{{PRESENTATION_NS}}}sldSz")
    if slide_size is None:
        return None
    try:
        cx = int(slide_size.attrib["cx"])
        cy = int(slide_size.attrib["cy"])
    except (KeyError, ValueError) as exc:
        raise PptxPackageError(f"Cannot parse PPTX slide size: {package.path}") from exc
    if cx <= 0 or cy <= 0:
        raise PptxPackageError(f"Invalid PPTX slide size: {package.path}")
    return _SlideSize(cx=cx, cy=cy, slide_type=slide_size.attrib.get("type"))


def _determine_output_slide_size(source_sizes: list[_SlideSize | None]) -> _SlideSize:
    """Determine the output canvas size from source slide sizes.

    Strategy: use the most common source size. If all sources are None or the list is empty,
    fall back to the default 16:9 widescreen size.
    """
    from collections import Counter

    valid_sizes = [(s.cx, s.cy, s.slide_type) for s in source_sizes if s is not None]
    if not valid_sizes:
        return _SlideSize(DEFAULT_OUTPUT_SLIDE_CX, DEFAULT_OUTPUT_SLIDE_CY, "wide")
    (cx, cy, slide_type), _count = Counter(valid_sizes).most_common(1)[0]
    return _SlideSize(cx=cx, cy=cy, slide_type=slide_type)


def _normalize_slide_xml_to_output_canvas(slide_xml: bytes, source_slide_size: _SlideSize | None, output_slide_size: _SlideSize) -> bytes:
    if not _should_normalize_slide_size(source_slide_size, output_slide_size):
        return slide_xml
    assert source_slide_size is not None

    try:
        slide = _parse_xml(slide_xml)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise PptxPackageError("Cannot parse PPTX slide XML for size normalization.") from exc

    x_scale = output_slide_size.cx / source_slide_size.cx
    y_scale = output_slide_size.cy / source_slide_size.cy

    if _same_aspect_ratio(source_slide_size, output_slide_size):
        # Same aspect ratio: scale both axes independently (stretch to fill)
        _scale_slide_coordinates(slide, x_scale=x_scale, y_scale=y_scale)
    else:
        # Different aspect ratio: uniform scale (fit, preserving source ratio)
        # This centers the content and avoids distortion
        uniform_scale = min(x_scale, y_scale)
        x_offset = int((output_slide_size.cx - source_slide_size.cx * uniform_scale) / 2)
        y_offset = int((output_slide_size.cy - source_slide_size.cy * uniform_scale) / 2)
        _scale_slide_coordinates(slide, x_scale=uniform_scale, y_scale=uniform_scale)
        if x_offset != 0 or y_offset != 0:
            _offset_slide_coordinates(slide, x_offset=x_offset, y_offset=y_offset)

    return ElementTree.tostring(slide, encoding="utf-8", xml_declaration=False)


def _offset_slide_coordinates(slide: ElementTree.Element, *, x_offset: int, y_offset: int) -> None:
    """Shift all position coordinates by the given offsets to center content."""
    for element in slide.iter():
        tag = _local_name(element.tag)
        if tag in {"off", "chOff"}:
            raw_x = element.attrib.get("x")
            raw_y = element.attrib.get("y")
            if raw_x is not None:
                try:
                    element.attrib["x"] = str(int(raw_x) + x_offset)
                except (ValueError, OverflowError):
                    pass
            if raw_y is not None:
                try:
                    element.attrib["y"] = str(int(raw_y) + y_offset)
                except (ValueError, OverflowError):
                    pass


def _should_normalize_slide_size(source_slide_size: _SlideSize | None, output_slide_size: _SlideSize) -> bool:
    if source_slide_size is None:
        return False
    if source_slide_size.cx == output_slide_size.cx and source_slide_size.cy == output_slide_size.cy:
        return False
    # Normalize whenever source differs from output — both same-ratio and cross-ratio
    return True


def _same_aspect_ratio(first: _SlideSize, second: _SlideSize) -> bool:
    delta = abs(first.cx * second.cy - second.cx * first.cy)
    scale = max(first.cx * second.cy, second.cx * first.cy)
    return delta / scale <= ASPECT_RATIO_TOLERANCE


def _scale_slide_coordinates(slide: ElementTree.Element, *, x_scale: float, y_scale: float) -> None:
    for element in slide.iter():
        for attribute in ("x", "cx"):
            _scale_integer_attribute(element, attribute, x_scale)
        for attribute in ("y", "cy"):
            _scale_integer_attribute(element, attribute, y_scale)
        _scale_text_size(element, (x_scale + y_scale) / 2)


def _scale_text_size(element: ElementTree.Element, scale: float) -> None:
    if _local_name(element.tag) not in {"rPr", "defRPr", "endParaRPr"}:
        return
    _scale_integer_attribute(element, "sz", scale)


def _scale_integer_attribute(element: ElementTree.Element, attribute: str, scale: float) -> None:
    raw_value = element.attrib.get(attribute)
    if raw_value is None:
        return
    try:
        value = int(raw_value)
    except ValueError:
        return
    element.attrib[attribute] = str(round(value * scale))


def _parse_xml(content: bytes) -> ElementTree.Element:
    return DefusedElementTree.fromstring(content)


def _page_index(page_number: int) -> int:
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number <= 0:
        raise PptxPackageError("slide/page number must be a positive 1-based integer.")
    return page_number - 1


def _content_types_xml(
    slide_count: int,
    extra_defaults: dict[str, str] | None = None,
    extra_overrides: dict[str, str] | None = None,
) -> str:
    defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
    }
    if extra_defaults:
        defaults.update(extra_defaults)
    overrides = {"ppt/presentation.xml": PRESENTATION_CONTENT_TYPE}
    for index in range(1, slide_count + 1):
        overrides[f"ppt/slides/slide{index}.xml"] = SLIDE_CONTENT_TYPE
    if extra_overrides:
        overrides.update(extra_overrides)

    default_entries = "".join(
        f'<Default Extension="{extension}" ContentType="{content_type}" />'
        for extension, content_type in sorted(defaults.items())
    )
    slide_overrides = "".join(
        f'<Override PartName="/{part_name}" ContentType="{content_type}" />'
        for part_name, content_type in sorted(overrides.items())
    )
    return (
        f'<Types xmlns="{CONTENT_TYPES_NS}">'
        f"{default_entries}"
        f"{slide_overrides}"
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        f'<Relationships xmlns="{RELATIONSHIP_NS}">'
        f'<Relationship Id="rId1" Type="{OFFICE_DOCUMENT_RELATIONSHIP_TYPE}" Target="ppt/presentation.xml" />'
        "</Relationships>"
    )


def _output_slide_master_parts(output_parts: dict[str, bytes]) -> tuple[str, ...]:
    return tuple(sorted(part for part in output_parts if SLIDE_MASTER_PART_PATTERN.fullmatch(part)))


def _presentation_xml(slide_count: int, slide_master_parts: tuple[str, ...] = (), output_slide_size: _SlideSize | None = None) -> str:
    if output_slide_size is None:
        output_slide_size = _SlideSize(DEFAULT_OUTPUT_SLIDE_CX, DEFAULT_OUTPUT_SLIDE_CY, "wide")
    sld_type = output_slide_size.slide_type or "custom"
    master_ids = "".join(
        f'<p:sldMasterId id="{2147483648 + index}" r:id="rId{slide_count + index}" />'
        for index, _ in enumerate(slide_master_parts, start=1)
    )
    slide_ids = "".join(f'<p:sldId id="{256 + index}" r:id="rId{index}" />' for index in range(1, slide_count + 1))
    return (
        f'<p:presentation xmlns:p="{PRESENTATION_NS}" xmlns:r="{OFFICE_RELATIONSHIP_NS}">'
        f"{f'<p:sldMasterIdLst>{master_ids}</p:sldMasterIdLst>' if master_ids else ''}"
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        f'<p:sldSz cx="{output_slide_size.cx}" cy="{output_slide_size.cy}" type="{sld_type}" />'
        '<p:notesSz cx="6858000" cy="9144000" />'
        "</p:presentation>"
    )


def _presentation_rels_xml(slide_count: int, slide_master_parts: tuple[str, ...] = ()) -> str:
    slide_relationships = "".join(
        f'<Relationship Id="rId{index}" Type="{SLIDE_RELATIONSHIP_TYPE}" Target="slides/slide{index}.xml" />'
        for index in range(1, slide_count + 1)
    )
    master_relationships = "".join(
        f'<Relationship Id="rId{slide_count + index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        f'Target="{_relative_target("ppt/presentation.xml", master_part)}" />'
        for index, master_part in enumerate(slide_master_parts, start=1)
    )
    return f'<Relationships xmlns="{RELATIONSHIP_NS}">{slide_relationships}{master_relationships}</Relationships>'


__all__ = ["CopiedSlide", "PptxPackage", "PptxPackageError", "copy_slides_to_new_pptx"]
