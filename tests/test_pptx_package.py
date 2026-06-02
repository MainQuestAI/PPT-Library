from __future__ import annotations

import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

import ppt_lib.pptx_package as pptx_package_module
from ppt_lib.pptx_package import PptxPackage, PptxPackageError, copy_slides_to_new_pptx


def test_pptx_package_indexes_slide_and_relationships(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx")

    package = PptxPackage.open(pptx)

    assert package.slide_part(1) == "ppt/slides/slide1.xml"
    assert package.slide_relationship_part(1) == "ppt/slides/_rels/slide1.xml.rels"


def test_pptx_package_reads_parts_without_modifying_source(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx")
    before = pptx.read_bytes()

    package = PptxPackage.open(pptx)

    assert package.read_part("ppt/slides/slide1.xml") == b"<p:sld />"
    assert package.contains_part("ppt/slides/slide1.xml") is True
    assert "ppt/slides/slide1.xml" in package.list_parts()
    assert pptx.read_bytes() == before


def test_pptx_package_returns_none_when_slide_relationships_are_missing(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx", include_slide_rels=False)

    package = PptxPackage.open(pptx)

    assert package.slide_relationship_part(1) is None


def test_pptx_package_rejects_missing_or_unreadable_package(tmp_path: Path) -> None:
    with pytest.raises(PptxPackageError, match="does not exist"):
        PptxPackage.open(tmp_path / "missing.pptx")

    invalid = tmp_path / "invalid.pptx"
    invalid.write_bytes(b"not a zip")
    with pytest.raises(PptxPackageError, match="readable zip"):
        PptxPackage.open(invalid)


def test_pptx_package_rejects_invalid_or_missing_slide_page(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx")
    package = PptxPackage.open(pptx)

    with pytest.raises(PptxPackageError, match="positive"):
        package.slide_part(0)
    with pytest.raises(PptxPackageError, match="slide/page"):
        package.slide_part(2)


def test_pptx_package_rejects_missing_part(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx")
    package = PptxPackage.open(pptx)

    with pytest.raises(PptxPackageError, match="ppt/missing.xml"):
        package.read_part("ppt/missing.xml")


def test_pptx_package_uses_presentation_order_when_available(tmp_path: Path) -> None:
    pptx = write_minimal_pptx(tmp_path / "source.pptx", slide_targets=("slides/slide2.xml", "slides/slide1.xml"))

    package = PptxPackage.open(pptx)

    assert package.slide_part(1) == "ppt/slides/slide2.xml"
    assert package.slide_part(2) == "ppt/slides/slide1.xml"


def test_pptx_package_rejects_missing_slide_relationship_without_shifting_pages(tmp_path: Path) -> None:
    pptx = tmp_path / "source.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr("ppt/presentation.xml", _presentation_xml(2))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide2.xml",), first_relationship_id=2))
        archive.writestr("ppt/slides/slide2.xml", b"<p:sld />")

    with pytest.raises(PptxPackageError, match="slide/page 1.*missing relationship"):
        PptxPackage.open(pptx)


def test_pptx_package_rejects_missing_slide_relationship_target_part(tmp_path: Path) -> None:
    pptx = tmp_path / "source.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))

    with pytest.raises(PptxPackageError, match="slide/page 1.*target is missing"):
        PptxPackage.open(pptx)


def test_pptx_package_rejects_non_slide_relationship_for_slide_id(tmp_path: Path) -> None:
    pptx = tmp_path / "source.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            _presentation_rels(
                ("media/image1.png",),
                relationship_type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            ),
        )
        archive.writestr("ppt/media/image1.png", b"image")

    with pytest.raises(PptxPackageError, match="slide/page 1.*not a slide relationship"):
        PptxPackage.open(pptx)


def test_pptx_package_rejects_xml_entities_in_presentation(tmp_path: Path) -> None:
    pptx = tmp_path / "source.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<!DOCTYPE p:presentation [<!ENTITY entity "257">]>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="&entity;" r:id="rId1" /></p:sldIdLst>'
                "</p:presentation>"
            ),
        )
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld />")

    with pytest.raises(PptxPackageError, match="Cannot index PPTX slides"):
        PptxPackage.open(pptx)


def test_copy_single_slide_into_new_package(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    assert output.exists()
    assert copied[0].status == "copied"
    assert copied[0].source_file == source
    assert copied[0].source_page_number == 1
    assert copied[0].output_page_number == 1
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        presentation_xml = archive.read("ppt/presentation.xml").decode()
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names
        assert "ppt/presentation.xml" in names
        assert "ppt/_rels/presentation.xml.rels" in names
        assert "ppt/slides/slide1.xml" in names
        assert archive.read("ppt/slides/slide1.xml") == b"<p:sld>hello</p:sld>"
        assert "<p:sldSz " in presentation_xml
        assert "<p:notesSz " in presentation_xml
    output_package = PptxPackage.open(output)
    assert output_package.slide_part(1) == "ppt/slides/slide1.xml"


def test_copy_selected_slide_ignores_unselected_malformed_slide_id(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="257" r:id="rId1" /><p:sldId id="258" /></p:sldIdLst>'
                "</p:presentation>"
            ),
        )
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>selected</p:sld>")
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", b"<Relationships />")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    assert copied[0].status == "copied"
    with zipfile.ZipFile(output) as archive:
        assert b"selected" in archive.read("ppt/slides/slide1.xml")


def test_copy_slide_relationship_parts(tmp_path: Path) -> None:
    source = write_pptx_with_media_and_chart(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        content_types = archive.read("[Content_Types].xml").decode()
        slide_rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert any(name.startswith("ppt/media/") for name in names)
    assert any(name.startswith("ppt/charts/") for name in names)
    assert 'Target="../media/image1.png"' in slide_rels
    assert 'Target="../charts/chart1.xml"' in slide_rels
    assert 'Extension="png"' in content_types
    assert 'PartName="/ppt/charts/chart1.xml"' in content_types
    assert copied[0].risk_tags == ["chart"]


def test_copy_slide_external_relationship_is_preserved_and_tagged(tmp_path: Path) -> None:
    source = write_pptx_with_media(tmp_path / "source.pptx", external_target="https://example.com/image.png")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        slide_rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert not any(name.startswith("ppt/media/") for name in names)
    assert 'TargetMode="External"' in slide_rels
    assert 'Target="https://example.com/image.png"' in slide_rels
    assert copied[0].risk_tags == ["external_relationship"]


def test_copy_slide_absolute_internal_relationship_is_copied_as_relative_target(tmp_path: Path) -> None:
    source = write_pptx_with_media(tmp_path / "source.pptx", internal_target="/ppt/media/image1.png")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        slide_rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
    assert "ppt/media/image1.png" in names
    assert 'Target="../media/image1.png"' in slide_rels
    assert 'Target="/ppt/media/image1.png"' not in slide_rels


def test_copy_slide_relationship_part_collision_renames_target(tmp_path: Path) -> None:
    source_a = write_pptx_with_media(tmp_path / "source-a.pptx", image_bytes=b"first image")
    source_b = write_pptx_with_media(tmp_path / "source-b.pptx", image_bytes=b"second image")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source_a, 1), (source_b, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        first_rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
        second_rels = archive.read("ppt/slides/_rels/slide2.xml.rels").decode()
    assert "ppt/media/image1.png" in names
    assert "ppt/media/image1_2.png" in names
    assert 'Target="../media/image1.png"' in first_rels
    assert 'Target="../media/image1_2.png"' in second_rels


def test_unique_output_part_name_has_collision_limit() -> None:
    source_part = "ppt/media/image1.png"
    output_parts = {source_part: b"existing"}
    output_parts.update({f"ppt/media/image1_{suffix}.png": b"existing" for suffix in range(2, 10002)})

    with pytest.raises(PptxPackageError, match="unique output part name"):
        pptx_package_module._unique_output_part_name(  # noqa: SLF001
            source_part,
            b"new",
            pptx_package_module._PartReuseSignature(None, "image/png"),  # noqa: SLF001
            output_parts,
            {},
            set(),
        )


def test_copy_slide_same_chart_bytes_with_different_relationships_do_not_reuse_chart(tmp_path: Path) -> None:
    source_a = write_pptx_with_chart_workbook(tmp_path / "source-a.pptx", workbook_name="workbook-a.bin")
    source_b = write_pptx_with_chart_workbook(tmp_path / "source-b.pptx", workbook_name="workbook-b.bin")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source_a, 1), (source_b, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        first_slide_rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
        second_slide_rels = archive.read("ppt/slides/_rels/slide2.xml.rels").decode()
        second_chart_rels = archive.read("ppt/charts/_rels/chart1_2.xml.rels").decode()
    assert "ppt/charts/chart1.xml" in names
    assert "ppt/charts/chart1_2.xml" in names
    assert "ppt/embeddings/workbook-a.bin" in names
    assert "ppt/embeddings/workbook-b.bin" in names
    assert 'Target="../charts/chart1.xml"' in first_slide_rels
    assert 'Target="../charts/chart1_2.xml"' in second_slide_rels
    assert 'Target="../embeddings/workbook-b.bin"' in second_chart_rels


def test_copy_slide_layout_master_theme_risk_tags(tmp_path: Path) -> None:
    source = write_pptx_with_layout_master_theme(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "ppt/slideLayouts/slideLayout1.xml" in names
    assert "ppt/slideMasters/slideMaster1.xml" in names
    assert "ppt/theme/theme1.xml" in names
    assert copied[0].risk_tags == ["slide_layout", "slide_master", "theme"]


def test_copy_slide_registers_copied_slide_master_in_presentation(tmp_path: Path) -> None:
    source = write_pptx_with_layout_master_theme(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        presentation_xml = archive.read("ppt/presentation.xml").decode()
        presentation_rels = archive.read("ppt/_rels/presentation.xml.rels").decode()

    assert "<p:sldMasterIdLst>" in presentation_xml
    assert 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"' in presentation_rels
    assert 'Target="slideMasters/slideMaster1.xml"' in presentation_rels


def test_copy_slide_preserves_source_size_when_single_source(tmp_path: Path) -> None:
    """When only one source slide, output canvas matches source — no scaling occurs."""
    source = write_pptx_with_small_wide_slide(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml")
        pres_xml = archive.read("ppt/presentation.xml")
    slide = ElementTree.fromstring(slide_xml)
    shape_transform = slide.find(".//{*}sp/{*}spPr/{*}xfrm")

    # Shape coordinates preserved as-is (no scaling)
    assert shape_transform is not None
    assert shape_transform.find("{*}off").attrib == {"x": "0", "y": "0"}
    assert shape_transform.find("{*}ext").attrib == {"cx": "9144000", "cy": "5143500"}

    # Output presentation uses source slide size
    pres = ElementTree.fromstring(pres_xml)
    sld_sz = pres.find(".//{*}sldSz")
    assert sld_sz is not None
    assert sld_sz.attrib["cx"] == "9144000"
    assert sld_sz.attrib["cy"] == "5143500"


def test_copy_slide_does_not_normalize_different_aspect_slide(tmp_path: Path) -> None:
    source = write_pptx_with_four_by_three_slide(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml")
    slide = ElementTree.fromstring(slide_xml)

    assert slide.find(".//{*}grpSp/{*}grpSpPr/{*}xfrm") is None


def test_copy_mixed_sizes_uses_majority_canvas(tmp_path: Path) -> None:
    """When mixing slide sizes, output canvas is the most common size."""
    wide = write_pptx_with_small_wide_slide(tmp_path / "wide.pptx")
    wide2 = write_pptx_with_small_wide_slide(tmp_path / "wide2.pptx")
    four_three = write_pptx_with_four_by_three_slide(tmp_path / "four_three.pptx")
    output = tmp_path / "output.pptx"

    # 2 wide + 1 four_three → output canvas = wide (9144000x5143500)
    results = copy_slides_to_new_pptx([(wide, 1), (wide2, 1), (four_three, 1)], output)

    with zipfile.ZipFile(output) as archive:
        pres_xml = archive.read("ppt/presentation.xml")
    pres = ElementTree.fromstring(pres_xml)
    sld_sz = pres.find(".//{*}sldSz")
    assert sld_sz is not None
    assert sld_sz.attrib["cx"] == "9144000"
    assert sld_sz.attrib["cy"] == "5143500"

    # The 4:3 slide should be tagged with aspect_ratio_mismatch
    assert "aspect_ratio_mismatch" in results[2].risk_tags
    # The wide slides should NOT be tagged
    assert "aspect_ratio_mismatch" not in results[0].risk_tags
    assert "aspect_ratio_mismatch" not in results[1].risk_tags


def test_copy_four_by_three_preserves_canvas(tmp_path: Path) -> None:
    """Single 4:3 source → output canvas is 4:3, no scaling."""
    source = write_pptx_with_four_by_three_slide(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source, 1)], output)

    with zipfile.ZipFile(output) as archive:
        pres_xml = archive.read("ppt/presentation.xml")
        slide_xml = archive.read("ppt/slides/slide1.xml")

    pres = ElementTree.fromstring(pres_xml)
    sld_sz = pres.find(".//{*}sldSz")
    assert sld_sz is not None
    assert sld_sz.attrib["cx"] == "9144000"
    assert sld_sz.attrib["cy"] == "6858000"

    # Shape not scaled
    slide = ElementTree.fromstring(slide_xml)
    shape_transform = slide.find(".//{*}sp/{*}spPr/{*}xfrm/{*}ext")
    assert shape_transform is not None
    assert shape_transform.attrib == {"cx": "9144000", "cy": "6858000"}


def test_copy_slide_reused_chart_still_tags_each_slide(tmp_path: Path) -> None:
    source = write_two_slide_pptx_with_shared_chart(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1), (source, 2)], output)

    with zipfile.ZipFile(output) as archive:
        names = [name for name in archive.namelist() if name.startswith("ppt/charts/chart")]
    assert names == ["ppt/charts/chart1.xml"]
    assert copied[0].risk_tags == ["chart"]
    assert copied[1].risk_tags == ["chart"]


def test_copy_slide_default_content_type_conflict_writes_override(tmp_path: Path) -> None:
    source_a = write_pptx_with_custom_default_part(
        tmp_path / "source-a.pptx",
        part_name="ppt/custom/item1.foo",
        content_type="application/vnd.example.first",
    )
    source_b = write_pptx_with_custom_default_part(
        tmp_path / "source-b.pptx",
        part_name="ppt/custom/item2.foo",
        content_type="application/vnd.example.second",
    )
    output = tmp_path / "output.pptx"

    copy_slides_to_new_pptx([(source_a, 1), (source_b, 1)], output)

    with zipfile.ZipFile(output) as archive:
        content_types = archive.read("[Content_Types].xml").decode()
    assert 'Default Extension="foo" ContentType="application/vnd.example.first"' in content_types
    assert 'Override PartName="/ppt/custom/item2.foo" ContentType="application/vnd.example.second"' in content_types


def test_copy_slide_missing_relationship_target_is_risk_tagged_and_warned(tmp_path: Path) -> None:
    source = write_pptx_with_missing_relationship_target(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"

    copied = copy_slides_to_new_pptx([(source, 1)], output)

    assert copied[0].risk_tags == ["missing_relationship_target"]
    assert copied[0].warnings == [
        "Relationship target is missing and was left unchanged: ppt/slides/_rels/slide1.xml.rels -> ../media/missing.png"
    ]


def test_copy_single_slide_does_not_modify_source(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    before = source.read_bytes()

    copy_slides_to_new_pptx([(source, 1)], tmp_path / "output.pptx")

    assert source.read_bytes() == before


def test_copy_single_slide_rejects_missing_source_slide(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")

    with pytest.raises(PptxPackageError, match="slide/page 2"):
        copy_slides_to_new_pptx([(source, 2)], tmp_path / "output.pptx")


def test_copy_single_slide_rejects_output_overwriting_source(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    before = source.read_bytes()

    with pytest.raises(PptxPackageError, match="output.*source|source.*output"):
        copy_slides_to_new_pptx([(source, 1)], source)

    assert source.read_bytes() == before


def test_copy_single_slide_rejects_hard_link_output_overwriting_source(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    hardlink_output = tmp_path / "hardlink-output.pptx"
    try:
        os.link(source, hardlink_output)
    except OSError as exc:
        pytest.skip(f"hard links are not supported here: {exc}")
    before = source.read_bytes()

    with pytest.raises(PptxPackageError, match="output.*source|source.*output"):
        copy_slides_to_new_pptx([(source, 1)], hardlink_output)

    assert source.read_bytes() == before


def write_minimal_pptx(
    path: Path,
    *,
    include_slide_rels: bool = True,
    slide_targets: tuple[str, ...] = ("slides/slide1.xml",),
    slide_text: str | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            _presentation_xml(len(slide_targets)),
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            _presentation_rels(slide_targets),
        )
        for target in slide_targets:
            slide_part = f"ppt/{target}"
            slide_xml = b"<p:sld />" if slide_text is None else f"<p:sld>{slide_text}</p:sld>".encode()
            archive.writestr(slide_part, slide_xml)
            if include_slide_rels:
                archive.writestr(_rels_part_for(slide_part), b"<Relationships />")
    return path


def write_pptx_with_media_and_chart(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
                '<Default Extension="xml" ContentType="application/xml" />'
                '<Default Extension="png" ContentType="image/png" />'
                '<Override PartName="/ppt/presentation.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml" />'
                '<Override PartName="/ppt/slides/slide1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml" />'
                '<Override PartName="/ppt/charts/chart1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml" />'
                "</Types>"
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>with dependencies</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/image1.png" />'
                '<Relationship Id="rId2" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
                'Target="../charts/chart1.xml" />'
                "</Relationships>"
            ),
        )
        archive.writestr("ppt/media/image1.png", b"image bytes")
        archive.writestr("ppt/charts/chart1.xml", b"<c:chartSpace />")
    return path


def write_pptx_with_media(
    path: Path,
    *,
    image_bytes: bytes = b"image bytes",
    internal_target: str = "../media/image1.png",
    external_target: str | None = None,
) -> Path:
    relationship_attrs = (
        f'Target="{external_target}" TargetMode="External"'
        if external_target is not None
        else f'Target="{internal_target}"'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
                '<Default Extension="xml" ContentType="application/xml" />'
                '<Default Extension="png" ContentType="image/png" />'
                '<Override PartName="/ppt/presentation.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml" />'
                '<Override PartName="/ppt/slides/slide1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml" />'
                "</Types>"
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>with media</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f"{relationship_attrs} />"
                "</Relationships>"
            ),
        )
        if external_target is None:
            archive.writestr("ppt/media/image1.png", image_bytes)
    return path


def write_pptx_with_chart_workbook(path: Path, *, workbook_name: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        _write_standard_content_types(
            archive,
            extra=(
                '<Override PartName="/ppt/charts/chart1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml" />'
                f'<Override PartName="/ppt/embeddings/{workbook_name}" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />'
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>with chart</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
                'Target="../charts/chart1.xml" />'
                "</Relationships>"
            ),
        )
        archive.writestr("ppt/charts/chart1.xml", b"<c:chartSpace>same chart</c:chartSpace>")
        archive.writestr(
            "ppt/charts/_rels/chart1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" '
                f'Target="../embeddings/{workbook_name}" />'
                "</Relationships>"
            ),
        )
        archive.writestr(f"ppt/embeddings/{workbook_name}", workbook_name.encode())
    return path


def write_pptx_with_layout_master_theme(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        _write_standard_content_types(
            archive,
            extra=(
                '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml" />'
                '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml" />'
                '<Override PartName="/ppt/theme/theme1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.theme+xml" />'
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>with layout</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                'Target="../slideLayouts/slideLayout1.xml" />'
                "</Relationships>"
            ),
        )
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", b"<p:sldLayout />")
        archive.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
                'Target="../slideMasters/slideMaster1.xml" />'
                "</Relationships>"
            ),
        )
        archive.writestr("ppt/slideMasters/slideMaster1.xml", b"<p:sldMaster />")
        archive.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
                'Target="../theme/theme1.xml" />'
                "</Relationships>"
            ),
        )
        archive.writestr("ppt/theme/theme1.xml", b"<a:theme />")
    return path


def write_pptx_with_small_wide_slide(path: Path) -> Path:
    return _write_pptx_with_sized_shape_slide(path, cx=9_144_000, cy=5_143_500, slide_type="screen16x9")


def write_pptx_with_four_by_three_slide(path: Path) -> Path:
    return _write_pptx_with_sized_shape_slide(path, cx=9_144_000, cy=6_858_000, slide_type=None)


def _write_pptx_with_sized_shape_slide(path: Path, *, cx: int, cy: int, slide_type: str | None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        _write_standard_content_types(archive)
        archive.writestr("ppt/presentation.xml", _presentation_xml(1, cx=cx, cy=cy, slide_type=slide_type))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr(
            "ppt/slides/slide1.xml",
            (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                "<p:cSld><p:spTree>"
                "<p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
                "<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
                "<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
                "<p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"Box\"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
                f"<p:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{cx}\" cy=\"{cy}\"/></a:xfrm></p:spPr>"
                "</p:sp>"
                "</p:spTree></p:cSld>"
                "</p:sld>"
            ),
        )
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", b"<Relationships />")
    return path


def write_two_slide_pptx_with_shared_chart(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        _write_standard_content_types(
            archive,
            slide_count=2,
            extra=(
                '<Override PartName="/ppt/charts/chart1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml" />'
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(2))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml", "slides/slide2.xml")))
        for slide_number in (1, 2):
            archive.writestr(f"ppt/slides/slide{slide_number}.xml", f"<p:sld>{slide_number}</p:sld>".encode())
            archive.writestr(
                f"ppt/slides/_rels/slide{slide_number}.xml.rels",
                (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
                    'Target="../charts/chart1.xml" />'
                    "</Relationships>"
                ),
            )
        archive.writestr("ppt/charts/chart1.xml", b"<c:chartSpace>shared chart</c:chartSpace>")
    return path


def write_pptx_with_custom_default_part(path: Path, *, part_name: str, content_type: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
                '<Default Extension="xml" ContentType="application/xml" />'
                f'<Default Extension="foo" ContentType="{content_type}" />'
                '<Override PartName="/ppt/presentation.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml" />'
                '<Override PartName="/ppt/slides/slide1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml" />'
                "</Types>"
            ),
        )
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>custom default</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" '
                f'Target="../{part_name.removeprefix("ppt/")}" />'
                "</Relationships>"
            ),
        )
        archive.writestr(part_name, b"custom default bytes")
    return path


def write_pptx_with_missing_relationship_target(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        _write_standard_content_types(archive)
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        archive.writestr("ppt/slides/slide1.xml", b"<p:sld>missing target</p:sld>")
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/missing.png" />'
                "</Relationships>"
            ),
        )
    return path


def _write_standard_content_types(archive: zipfile.ZipFile, *, slide_count: int = 1, extra: str = "") -> None:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml" />'
        for index in range(1, slide_count + 1)
    )
    archive.writestr(
        "[Content_Types].xml",
        (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
            '<Default Extension="xml" ContentType="application/xml" />'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml" />'
            f"{slide_overrides}"
            f"{extra}"
            "</Types>"
        ),
    )


def _presentation_xml(slide_count: int, *, cx: int | None = None, cy: int | None = None, slide_type: str | None = None) -> str:
    slide_ids = "".join(f'<p:sldId id="{256 + index}" r:id="rId{index}" />' for index in range(1, slide_count + 1))
    slide_size = ""
    if cx is not None and cy is not None:
        slide_type_attr = f' type="{slide_type}"' if slide_type else ""
        slide_size = f'<p:sldSz cx="{cx}" cy="{cy}"{slide_type_attr}/>'
    return (
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        f"{slide_size}"
        "</p:presentation>"
    )


def _presentation_rels(
    slide_targets: tuple[str, ...],
    *,
    first_relationship_id: int = 1,
    relationship_type: str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
) -> str:
    relationships = "".join(
        '<Relationship xmlns="http://schemas.openxmlformats.org/package/2006/relationships" '
        f'Id="rId{index}" '
        f'Type="{relationship_type}" '
        f'Target="{target}" />'
        for index, target in enumerate(slide_targets, start=first_relationship_id)
    )
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>'


def _rels_part_for(part_name: str) -> str:
    directory, name = part_name.rsplit("/", 1)
    return f"{directory}/_rels/{name}.rels"
