from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ppt_lib.screenshot import (
    ScreenshotError,
    compute_sha256,
    render_pptx_slides,
    store_deduped_png,
)


def png_bytes(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_compute_sha256_stable(tmp_path: Path) -> None:
    path = tmp_path / "slide.png"
    path.write_bytes(b"same")

    assert compute_sha256(path) == compute_sha256(path)


def test_store_deduped_png_reuses_existing(tmp_path: Path) -> None:
    screenshots_dir = tmp_path / "screens"
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(png_bytes())
    second.write_bytes(png_bytes())

    first_path = store_deduped_png(first, screenshots_dir)
    second_path = store_deduped_png(second, screenshots_dir)

    assert first_path == second_path
    assert len(list(screenshots_dir.glob("*.png"))) == 1


def test_render_invokes_isolated_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen_cmds: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen_cmds.append(cmd)
        if "--convert-to" in cmd:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
        else:
            output_prefix = Path(cmd[-1])
            (output_prefix.parent / f"{output_prefix.name}-1.png").write_bytes(png_bytes(16, 9))
        return subprocess.CompletedProcess(cmd, 0, stderr="warning")

    monkeypatch.setattr("ppt_lib.screenshot.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ppt_lib.screenshot.subprocess.run", fake_run)
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"pptx")

    results = render_pptx_slides(pptx, tmp_path / "screens")

    assert any(arg.startswith("-env:UserInstallation=file://") for arg in seen_cmds[0])
    assert seen_cmds[0][seen_cmds[0].index("--convert-to") + 1] == "pdf"
    assert seen_cmds[1][0] == "/usr/bin/pdftoppm"
    assert results[0].width == 16
    assert results[0].height == 9
    assert "warning" in results[0].warnings


def test_render_returns_all_pdf_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kwargs):
        if "--convert-to" in cmd:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
        else:
            output_prefix = Path(cmd[-1])
            (output_prefix.parent / f"{output_prefix.name}-1.png").write_bytes(png_bytes(16, 9))
            (output_prefix.parent / f"{output_prefix.name}-2.png").write_bytes(png_bytes(17, 10))
            (output_prefix.parent / f"{output_prefix.name}-10.png").write_bytes(png_bytes(18, 11))
        return subprocess.CompletedProcess(cmd, 0, stderr="")

    monkeypatch.setattr("ppt_lib.screenshot.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ppt_lib.screenshot.subprocess.run", fake_run)
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"pptx")

    results = render_pptx_slides(pptx, tmp_path / "screens")

    assert [item.slide_index for item in results] == [0, 1, 2]
    assert [item.width for item in results] == [16, 17, 18]


def test_render_timeout_records_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr("ppt_lib.screenshot.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ppt_lib.screenshot.subprocess.run", fake_run)
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"pptx")

    with pytest.raises(ScreenshotError) as exc:
        render_pptx_slides(pptx, tmp_path / "screens")

    assert exc.value.code == "SCREENSHOT_RENDER_TIMEOUT"


def test_render_nonzero_exit_records_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="conversion failed")

    monkeypatch.setattr("ppt_lib.screenshot.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.screenshot.subprocess.run", fake_run)
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"pptx")

    with pytest.raises(ScreenshotError) as exc:
        render_pptx_slides(pptx, tmp_path / "screens")

    assert exc.value.code == "SCREENSHOT_RENDER_FAILED"
    assert "conversion failed" in str(exc.value)


def test_missing_libreoffice_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.screenshot.shutil.which", lambda name: None)

    with pytest.raises(ScreenshotError) as exc:
        render_pptx_slides(tmp_path / "deck.pptx", tmp_path / "screens")

    assert exc.value.code == "SCREENSHOT_RENDERER_MISSING"


def test_corrupt_png_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not png")

    with pytest.raises(ScreenshotError) as exc:
        store_deduped_png(bad, tmp_path / "screens")

    assert exc.value.code == "SCREENSHOT_INVALID_OUTPUT"
