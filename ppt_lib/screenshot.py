from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class ScreenshotError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScreenshotResult:
    slide_index: int
    png_path: Path
    sha256: str
    width: int
    height: int
    warnings: list[str]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_deduped_png(temp_png: Path, screenshots_dir: Path) -> Path:
    _read_png_size(temp_png)
    sha256 = compute_sha256(temp_png)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    target = screenshots_dir / f"{sha256}.png"
    if not target.exists():
        shutil.copy2(temp_png, target)
    return target


def render_pptx_slides(
    pptx_path: Path,
    output_dir: Path,
    *,
    max_workers: int = 4,
    timeout_seconds: int = 30,
) -> list[ScreenshotResult]:
    soffice = shutil.which("soffice")
    if not soffice:
        raise ScreenshotError("LibreOffice soffice executable was not found.", code="SCREENSHOT_RENDERER_MISSING")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise ScreenshotError("Poppler pdftoppm executable was not found.", code="SCREENSHOT_PDF_RENDERER_MISSING")
    if not pptx_path.exists():
        raise ScreenshotError(f"PPTX file does not exist: {pptx_path}", code="SCREENSHOT_INPUT_NOT_FOUND")

    with tempfile.TemporaryDirectory(prefix="ppt-lib-lo-") as temp_root:
        temp_root_path = Path(temp_root)
        profile_dir = temp_root_path / "profile"
        pdf_dir = temp_root_path / "pdf"
        render_dir = temp_root_path / "png"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        render_dir.mkdir(parents=True, exist_ok=True)
        convert_cmd = [
            soffice,
            "--headless",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf_dir),
            str(pptx_path),
        ]
        completed = _run_render_command(convert_cmd, timeout_seconds=timeout_seconds, timeout_code="SCREENSHOT_RENDER_TIMEOUT")
        if completed.returncode != 0:
            raise _render_failed("LibreOffice PDF conversion failed", completed)

        pdf_path = _single_pdf_output(pdf_dir)
        render_cmd = [
            pdftoppm,
            "-png",
            "-r",
            "144",
            str(pdf_path),
            str(render_dir / "slide"),
        ]
        pdf_completed = _run_render_command(render_cmd, timeout_seconds=timeout_seconds, timeout_code="SCREENSHOT_RENDER_TIMEOUT")
        if pdf_completed.returncode != 0:
            raise _render_failed("PDF screenshot rendering failed", pdf_completed)

        warnings = _warnings(completed) + _warnings(pdf_completed)
        results: list[ScreenshotResult] = []
        for index, png in enumerate(sorted(render_dir.glob("*.png"), key=_png_sort_key)):
            try:
                width, height = _read_png_size(png)
                stored = store_deduped_png(png, output_dir)
            except ScreenshotError:
                continue
            results.append(
                ScreenshotResult(
                    slide_index=index,
                    png_path=stored,
                    sha256=compute_sha256(stored),
                    width=width,
                    height=height,
                    warnings=warnings.copy(),
                )
            )
        return results


def _run_render_command(cmd: list[str], *, timeout_seconds: int, timeout_code: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotError("Screenshot rendering timed out.", code=timeout_code) from exc


def _render_failed(message: str, completed: subprocess.CompletedProcess[str]) -> ScreenshotError:
    detail = completed.stderr.strip() if completed.stderr else f"return code {completed.returncode}"
    return ScreenshotError(f"{message}: {detail}", code="SCREENSHOT_RENDER_FAILED")


def _warnings(completed: subprocess.CompletedProcess[str]) -> list[str]:
    return [completed.stderr.strip()] if completed.stderr and completed.stderr.strip() else []


def _single_pdf_output(pdf_dir: Path) -> Path:
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise ScreenshotError("LibreOffice PDF conversion produced no PDF output.", code="SCREENSHOT_RENDER_FAILED")
    return pdfs[0]


def _png_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"-(\d+)\.png$", path.name)
    if not match:
        return (0, path.name)
    return (int(match.group(1)), path.name)


def _read_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ScreenshotError(f"Invalid PNG output: {path}", code="SCREENSHOT_INVALID_OUTPUT")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise ScreenshotError(f"Invalid PNG dimensions: {path}", code="SCREENSHOT_INVALID_OUTPUT")
    return width, height
