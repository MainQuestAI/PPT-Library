from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ppt_lib.assemble_spike import AssembleSpikeManifestError, load_assemble_spike_manifest, run_assemble_spike


def test_load_assemble_spike_manifest_requires_samples(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.0", "samples": []}), encoding="utf-8")

    with pytest.raises(AssembleSpikeManifestError, match="samples"):
        load_assemble_spike_manifest(manifest)


def test_load_assemble_spike_manifest_accepts_routes(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fake")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1.0",
                "samples": [{"id": "s1", "path": str(deck), "slides": [1]}],
                "routes": ["image-baseline", "xml-inspection"],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_assemble_spike_manifest(manifest)

    assert loaded.samples[0].id == "s1"
    assert loaded.routes == ["image-baseline", "xml-inspection"]


def test_load_assemble_spike_manifest_rejects_negative_slide_number(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"samples": [{"id": "s1", "path": "/tmp/a.pptx", "slides": [-1]}]}),
        encoding="utf-8",
    )

    with pytest.raises(AssembleSpikeManifestError, match="positive"):
        load_assemble_spike_manifest(manifest)


def test_load_assemble_spike_manifest_rejects_non_numeric_slide_number(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"samples": [{"id": "s1", "path": "/tmp/a.pptx", "slides": ["bad"]}]}),
        encoding="utf-8",
    )

    with pytest.raises(AssembleSpikeManifestError, match="positive"):
        load_assemble_spike_manifest(manifest)


def test_run_assemble_spike_skips_missing_samples(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"samples": [{"id": "s1", "path": str(tmp_path / "missing.pptx"), "slides": [1]}]}),
        encoding="utf-8",
    )
    manifest = load_assemble_spike_manifest(manifest_path)

    report = run_assemble_spike(manifest, tmp_path / "reports")

    assert report.route_results[0].status == "skipped"
    assert Path(report.report_path).exists()


def test_run_assemble_spike_inspects_valid_samples_when_some_are_missing(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    with zipfile.ZipFile(deck, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", "<p:sld />")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "samples": [
                    {"id": "valid", "path": str(deck), "slides": [1]},
                    {"id": "missing", "path": str(tmp_path / "missing.pptx"), "slides": [1]},
                ],
                "routes": ["xml-inspection"],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_assemble_spike_manifest(manifest_path)

    report = run_assemble_spike(manifest, tmp_path / "reports")

    route_result = report.route_results[0]
    assert route_result.status == "needs_manual_review"
    assert route_result.evidence["inspected_sample_count"] == 1
    assert any("Missing sample" in warning for warning in route_result.warnings)
    assert route_result.output_path is not None
    evidence = json.loads(Path(route_result.output_path).read_text(encoding="utf-8"))
    assert [item["id"] for item in evidence] == ["valid"]


def test_run_assemble_spike_writes_xml_evidence_for_valid_pptx(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    with zipfile.ZipFile(deck, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", "<p:sld />")
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", "<p:sldLayout />")
        archive.writestr("ppt/media/image1.png", b"png")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"samples": [{"id": "s1", "path": str(deck), "slides": [1]}], "routes": ["xml-inspection"]}),
        encoding="utf-8",
    )
    manifest = load_assemble_spike_manifest(manifest_path)

    report = run_assemble_spike(manifest, tmp_path / "reports")

    assert report.route_results[0].status == "passed"
    assert report.route_results[0].output_path is not None
    assert Path(report.route_results[0].output_path).exists()
    assert Path(report.route_results[0].output_path).name.startswith("xml-inspection-evidence-")
    assert "xml-inspection" in report.recommendation


def test_run_assemble_spike_does_not_overwrite_previous_xml_evidence(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    with zipfile.ZipFile(deck, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", "<p:sld />")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"samples": [{"id": "s1", "path": str(deck), "slides": [1]}], "routes": ["xml-inspection"]}),
        encoding="utf-8",
    )
    manifest = load_assemble_spike_manifest(manifest_path)

    first = run_assemble_spike(manifest, tmp_path / "reports")
    second = run_assemble_spike(manifest, tmp_path / "reports")

    assert first.route_results[0].output_path != second.route_results[0].output_path
