from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import ppt_lib.assemble_ingest as assemble_ingest_module
import ppt_lib.assembler as assembler_module
from ppt_lib.assembler import (
    AssembleFidelityReport,
    AssembleManifestError,
    AssembleReport,
    AssembleSlideReport,
    load_assemble_manifest,
    run_assemble,
)
from ppt_lib.pptx_package import CopiedSlide
from ppt_lib.screenshot import ScreenshotResult


def test_load_assemble_manifest_requires_slides(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema_version":"1.0","slides":[]}', encoding="utf-8")

    with pytest.raises(AssembleManifestError, match="slides"):
        load_assemble_manifest(manifest)


def test_run_assemble_writes_output_and_report(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    manifest = write_manifest(tmp_path, source, page_number=1)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.status in {"passed", "needs_manual_review"}
    assert report.output_path.exists()
    assert report.report_path.exists()
    assert report.slides[0].source_page_number == 1

    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert report_json["status"] == report.status
    assert report_json["output_path"] == str(report.output_path)


def test_run_assemble_records_fidelity_render_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    manifest = write_manifest(tmp_path, source, render_fidelity_baseline=True)
    monkeypatch.setattr("ppt_lib.assembler.render_pptx_slides", lambda *args, **kwargs: [])

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.fidelity.manual_review_required is True
    assert report.fidelity.source_screenshots_dir == str(tmp_path / "assembled" / "screenshots" / "source")
    assert report.fidelity.output_screenshots_dir == str(tmp_path / "assembled" / "screenshots" / "output")
    assert any(warning.startswith("fidelity_render_empty:") for warning in report.fidelity.warnings)


def test_run_assemble_records_fidelity_screenshot_count_gaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    output = tmp_path / "assembled" / "output.pptx"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "run_name": "fidelity-counts",
            "output": {"path": str(output), "overwrite": True},
            "options": {"render_fidelity_baseline": True},
            "slides": [
                {"source_file": str(source), "page_number": 1},
                {"source_file": str(source), "page_number": 2},
            ],
        }),
        encoding="utf-8",
    )

    def fake_copy_slides(slides: list[tuple[Path, int]], output_path: Path) -> list[CopiedSlide]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"pptx")
        return [
            CopiedSlide(slides[0][0], slides[0][1], 1, "copied", [], []),
            CopiedSlide(slides[1][0], slides[1][1], 2, "copied", [], []),
        ]

    def fake_render(pptx_path: Path, output_dir: Path, **kwargs):
        assert kwargs["timeout_seconds"] == assembler_module.FIDELITY_RENDER_TIMEOUT_SECONDS
        return [
            ScreenshotResult(
                slide_index=0,
                png_path=output_dir / "one.png",
                sha256="hash",
                width=100,
                height=100,
                warnings=[],
            )
        ]

    monkeypatch.setattr(assembler_module, "copy_slides_to_new_pptx", fake_copy_slides)
    monkeypatch.setattr(assembler_module, "render_pptx_slides", fake_render)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.fidelity.expected_source_screenshot_count == 2
    assert report.fidelity.actual_source_screenshot_count == 1
    assert report.fidelity.missing_source_screenshot_count == 1
    assert report.fidelity.expected_output_screenshot_count == 2
    assert report.fidelity.actual_output_screenshot_count == 1
    assert report.fidelity.missing_output_screenshot_count == 1
    assert any(warning.startswith("fidelity_render_incomplete:") for warning in report.fidelity.warnings)
    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert report_json["fidelity"]["missing_output_screenshot_count"] == 1


def test_run_assemble_records_fidelity_render_failed_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    manifest = write_manifest(tmp_path, source, render_fidelity_baseline=True)

    def fail_render(*args, **kwargs):
        raise assembler_module.ScreenshotError("renderer unavailable", code="SCREENSHOT_RENDERER_MISSING")

    monkeypatch.setattr("ppt_lib.assembler.render_pptx_slides", fail_render)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.output_path.exists()
    assert report.status == "needs_manual_review"
    assert any(warning.startswith("fidelity_render_failed:") for warning in report.fidelity.warnings)

    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert report_json["status"] == "needs_manual_review"
    assert any(warning.startswith("fidelity_render_failed:") for warning in report_json["fidelity"]["warnings"])


def test_run_assemble_does_not_suppress_unexpected_fidelity_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    manifest = write_manifest(tmp_path, source, render_fidelity_baseline=True)

    def fail_render(*args, **kwargs):
        raise ValueError("programming error")

    monkeypatch.setattr("ppt_lib.assembler.render_pptx_slides", fail_render)

    with pytest.raises(ValueError, match="programming error"):
        run_assemble(load_assemble_manifest(manifest))


def test_run_assemble_skips_fidelity_renderer_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    manifest = write_manifest(tmp_path, source, render_fidelity_baseline=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("renderer should not be called")

    monkeypatch.setattr("ppt_lib.assembler.render_pptx_slides", fail_if_called)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.fidelity.manual_review_required is True
    assert report.fidelity.source_screenshots_dir == ""
    assert report.fidelity.output_screenshots_dir == ""


def test_run_assemble_skips_unrenderable_slides_when_complex_policy_is_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    output = tmp_path / "assembled" / "output.pptx"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "run_name": "skip-render-failures",
            "output": {"path": str(output), "overwrite": True},
            "options": {"on_complex_slide": "skip", "render_fidelity_baseline": False},
            "slides": [
                {"source_file": str(source), "page_number": 1},
                {"source_file": str(source), "page_number": 2},
            ],
        }),
        encoding="utf-8",
    )
    copied_inputs: list[tuple[Path, int]] = []

    def fake_preflight(slide):
        if slide.page_number == 2:
            return ["render_preflight_failed: SCREENSHOT_RENDER_FAILED"]
        return []

    def fake_copy_slides(slides: list[tuple[Path, int]], output_path: Path) -> list[CopiedSlide]:
        copied_inputs.extend(slides)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"pptx")
        return [CopiedSlide(slides[0][0], slides[0][1], 1, "copied", [], [])]

    monkeypatch.setattr(assembler_module, "_slide_render_preflight", fake_preflight)
    monkeypatch.setattr(assembler_module, "copy_slides_to_new_pptx", fake_copy_slides)

    report = run_assemble(load_assemble_manifest(manifest))

    assert copied_inputs == [(source, 1)]
    assert report.status == "partial"
    assert report.slide_count == 1
    assert report.skipped_slides[0].source_page_number == 2
    assert report.skipped_slides[0].status == "skipped"
    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert report_json["skipped_slides"][0]["source_page_number"] == 2


def test_run_assemble_keeps_provenance_when_middle_slide_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    output = tmp_path / "assembled" / "output.pptx"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_name": "skip-middle",
                "output": {"path": str(output), "overwrite": True},
                "options": {"on_complex_slide": "skip", "render_fidelity_baseline": False},
                "slides": [
                    {"source_file": str(source), "page_number": 1, "source_slide_id": 101},
                    {"source_file": str(source), "page_number": 2, "source_slide_id": 102},
                    {
                        "source_file": str(source),
                        "page_number": 3,
                        "source_slide_id": 103,
                        "risk_policy": "manual_review_required",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        assembler_module,
        "_slide_render_preflight",
        lambda slide: ["cannot render"] if slide.page_number == 2 else [],
    )

    def fake_copy(slides: list[tuple[Path, int]], output_path: Path) -> list[CopiedSlide]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"pptx")
        return [
            CopiedSlide(path, page, index, "copied", [], [])
            for index, (path, page) in enumerate(slides, start=1)
        ]

    monkeypatch.setattr(assembler_module, "copy_slides_to_new_pptx", fake_copy)

    report = run_assemble(load_assemble_manifest(manifest_path))

    assert [(slide.output_page_number, slide.source_slide_id) for slide in report.slides] == [(1, 101), (2, 103)]
    assert report.slides[1].risk_policy == "manual_review_required"
    assert report.status == "partial"


def test_run_assemble_honors_manual_review_risk_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx")
    manifest_path = write_manifest(tmp_path, source)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["slides"][0]["risk_policy"] = "manual_review_required"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_assemble(load_assemble_manifest(manifest_path))

    assert report.slides[0].risk_policy == "manual_review_required"
    assert report.status == "needs_manual_review"


def test_lineage_uses_report_provenance_after_middle_skip(tmp_path: Path) -> None:
    from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide

    conn = connect(tmp_path / "index.db")
    init_db(conn)
    source_path = tmp_path / "source.pptx"
    source_presentation_id = upsert_presentation(
        conn,
        PresentationRecord(source_path, source_path.name, None, 3, "source", 100, 1.0),
    )
    source_ids = [
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=source_presentation_id,
                slide_index=index,
                title=f"Source {index + 1}",
                text_content="source",
                embedding=None,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
        for index in range(3)
    ]
    output_path = tmp_path / "output.pptx"
    output_presentation_id = upsert_presentation(
        conn,
        PresentationRecord(output_path, output_path.name, None, 2, "output", 100, 1.0),
    )
    output_ids = [
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=output_presentation_id,
                slide_index=index,
                title=f"Output {index + 1}",
                text_content="output",
                embedding=None,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
        for index in range(2)
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_name": "skip-middle-lineage",
                "output": {"path": str(output_path), "overwrite": True},
                "slides": [
                    {"source_file": str(source_path), "page_number": index + 1, "source_slide_id": source_id}
                    for index, source_id in enumerate(source_ids)
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_assemble_manifest(manifest_path)
    report = AssembleReport(
        schema_version="1.0",
        run_id="run-1",
        status="partial",
        output_path=output_path,
        slide_count=2,
        slides=[
            AssembleSlideReport(1, str(source_path), 1, "copied", "low", [], source_ids[0]),
            AssembleSlideReport(2, str(source_path), 3, "copied", "low", [], source_ids[2]),
        ],
        errors=[],
        fidelity=AssembleFidelityReport("", "", True, []),
    )
    run_id = assemble_ingest_module._create_assemble_run(conn, manifest, report, status="partial")

    count, warnings = assemble_ingest_module._insert_lineage(conn, report, output_presentation_id, run_id)

    assert count == 2
    assert warnings == []
    rows = conn.execute(
        "SELECT derived_slide_id, source_slide_id FROM slide_lineage ORDER BY derived_slide_id"
    ).fetchall()
    assert rows == [(output_ids[0], source_ids[0]), (output_ids[1], source_ids[2])]


def test_run_assemble_does_not_overwrite_existing_output_when_disabled(tmp_path: Path) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    output = tmp_path / "assembled" / "output.pptx"
    output.parent.mkdir()
    output.write_bytes(b"existing")
    manifest = write_manifest(tmp_path, source, page_number=1, output=output, overwrite=False)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.status == "failed"
    assert output.read_bytes() == b"existing"
    assert report.report_path.exists()
    assert report.errors


def test_run_assemble_flags_layout_and_theme_risks_for_manual_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_minimal_pptx(tmp_path / "source.pptx", slide_text="hello")
    manifest = write_manifest(tmp_path, source, page_number=1)

    def fake_copy_slides(slides: list[tuple[Path, int]], output_path: Path) -> list[CopiedSlide]:
        output_path.write_bytes(b"pptx")
        return [
            CopiedSlide(
                source_file=slides[0][0],
                source_page_number=slides[0][1],
                output_page_number=1,
                status="copied",
                risk_tags=["slide_layout", "theme"],
                warnings=[],
            )
        ]

    monkeypatch.setattr(assembler_module, "copy_slides_to_new_pptx", fake_copy_slides)

    report = run_assemble(load_assemble_manifest(manifest))

    assert report.slides[0].risk_level == "medium"
    assert report.status == "needs_manual_review"


def test_load_assemble_manifest_rejects_zero_page_number(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    source.write_bytes(b"pptx")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"slides": [{"source_file": str(source), "page_number": 0}]}),
        encoding="utf-8",
    )

    with pytest.raises(AssembleManifestError, match="page_number"):
        load_assemble_manifest(manifest)


def test_load_assemble_manifest_applies_defaults_without_requiring_source_file_exists(tmp_path: Path) -> None:
    source = tmp_path / "missing-source.pptx"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"slides": [{"source_file": str(source), "page_number": 1}]}),
        encoding="utf-8",
    )

    loaded = load_assemble_manifest(manifest)

    assert loaded.schema_version == "1.0"
    assert loaded.run_name == "assemble-run"
    assert loaded.output_path == Path(".gstack/assembled/assemble-run/output.pptx")
    assert loaded.overwrite is False
    assert loaded.render_fidelity_baseline is True
    assert loaded.on_complex_slide == "include_with_warning"
    assert loaded.slides[0].source_file == source
    assert loaded.slides[0].risk_policy == "allow_with_warnings"


def test_load_assemble_manifest_accepts_planned_schema(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_name": "first-draft",
                "output": {"path": ".gstack/assembled/first-draft/output.pptx", "overwrite": True},
                "options": {"render_fidelity_baseline": False, "on_complex_slide": "skip"},
                "slides": [
                    {
                        "source_file": "~/library/source-a.pptx",
                        "page_number": 7,
                        "source_slide_id": 123,
                        "reason": "business flow",
                        "risk_policy": "manual_review_required",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_assemble_manifest(manifest)

    assert loaded.run_name == "first-draft"
    assert loaded.output_path == Path(".gstack/assembled/first-draft/output.pptx")
    assert loaded.overwrite is True
    assert loaded.render_fidelity_baseline is False
    assert loaded.on_complex_slide == "skip"
    assert loaded.slides[0].source_file == Path("~/library/source-a.pptx").expanduser()
    assert loaded.slides[0].page_number == 7
    assert loaded.slides[0].source_slide_id == 123
    assert loaded.slides[0].reason == "business flow"
    assert loaded.slides[0].risk_policy == "manual_review_required"


def test_load_assemble_manifest_rejects_unknown_on_complex_slide(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "options": {"on_complex_slide": "archive"},
                "slides": [{"source_file": "source.pptx", "page_number": 1}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssembleManifestError, match="on_complex_slide"):
        load_assemble_manifest(manifest)


def test_load_assemble_manifest_rejects_unknown_risk_policy(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "source_file": "source.pptx",
                        "page_number": 1,
                        "risk_policy": "silent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssembleManifestError, match="risk_policy"):
        load_assemble_manifest(manifest)


def test_load_assemble_manifest_requires_safe_run_name_for_default_output_path(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"run_name": "../draft", "slides": [{"source_file": "source.pptx", "page_number": 1}]}),
        encoding="utf-8",
    )

    with pytest.raises(AssembleManifestError, match="run_name"):
        load_assemble_manifest(manifest)


def test_load_assemble_manifest_allows_unsafe_run_name_with_explicit_output_path(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_name": "../draft",
                "output": {"path": ".gstack/assembled/custom/output.pptx"},
                "slides": [{"source_file": "source.pptx", "page_number": 1}],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_assemble_manifest(manifest)

    assert loaded.run_name == "../draft"
    assert loaded.output_path == Path(".gstack/assembled/custom/output.pptx")


def test_load_assemble_manifest_rejects_null_explicit_output_path(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_name": "../draft",
                "output": {"path": None},
                "slides": [{"source_file": "source.pptx", "page_number": 1}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssembleManifestError, match="output.path"):
        load_assemble_manifest(manifest)


def test_assemble_report_dataclass_contract() -> None:
    report = AssembleReport(
        schema_version="1.0",
        run_id="20260524T120000",
        status="needs_manual_review",
        output_path=Path(".gstack/assembled/first-draft/output.pptx"),
        slide_count=1,
        slides=[
            AssembleSlideReport(
                output_page_number=1,
                source_file="examples/source-a.pptx",
                source_page_number=7,
                status="copied",
                risk_level="medium",
                warnings=["visual review required"],
                source_slide_id=123,
                risk_policy="manual_review_required",
            )
        ],
        errors=[],
        fidelity=AssembleFidelityReport(
            source_screenshots_dir=".gstack/assembled/first-draft/screenshots/source",
            output_screenshots_dir=".gstack/assembled/first-draft/screenshots/output",
            manual_review_required=True,
            warnings=[],
        ),
    )

    assert report.schema_version == "1.0"
    assert report.slides[0].source_page_number == 7
    assert report.slides[0].source_slide_id == 123
    assert report.fidelity.manual_review_required is True


def write_manifest(
    tmp_path: Path,
    source: Path,
    *,
    page_number: int = 1,
    output: Path | None = None,
    overwrite: bool = True,
    render_fidelity_baseline: bool = False,
) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_name": "test-run",
                "output": {
                    "path": str(output or tmp_path / "assembled" / "output.pptx"),
                    "overwrite": overwrite,
                },
                "options": {"render_fidelity_baseline": render_fidelity_baseline},
                "slides": [{"source_file": str(source), "page_number": page_number}],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def write_minimal_pptx(path: Path, *, slide_text: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/presentation.xml", _presentation_xml(1))
        archive.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(("slides/slide1.xml",)))
        slide_xml = b"<p:sld />" if slide_text is None else f"<p:sld>{slide_text}</p:sld>".encode()
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", b"<Relationships />")
    return path


def _presentation_xml(slide_count: int) -> str:
    slide_ids = "".join(f'<p:sldId id="{256 + index}" r:id="rId{index}" />' for index in range(1, slide_count + 1))
    return (
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        "</p:presentation>"
    )


def _presentation_rels(slide_targets: tuple[str, ...]) -> str:
    relationships = "".join(
        '<Relationship xmlns="http://schemas.openxmlformats.org/package/2006/relationships" '
        f'Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="{target}" />'
        for index, target in enumerate(slide_targets, start=1)
    )
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>'
