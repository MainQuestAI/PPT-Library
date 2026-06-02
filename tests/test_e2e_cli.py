from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ppt_lib.cli import main


def test_cli_index_search_html_round_trip(tmp_path: Path, capsys, monkeypatch) -> None:
    deck = tmp_path / "warehouse.pptx"
    _write_minimal_pptx(deck, "Warehouse process overview")
    home = tmp_path / "home"
    monkeypatch.setenv("PPT_LIB_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("PPT_LIB_VISION_PROVIDER", "text_extraction")
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])

    index_exit = main(["--home-dir", str(home), "index", str(deck)])
    index_payload = _read_payload(capsys)

    assert index_exit == 0
    assert index_payload["result"]["status"] == "indexed"
    assert index_payload["result"]["slides_indexed"] == 1

    search_exit = main(["--home-dir", str(home), "search", "warehouse", "--threshold", "0.0", "--html"])
    search_payload = _read_payload(capsys)

    assert search_exit == 0
    assert search_payload["_errors"] == []
    assert search_payload["results"][0]["text_summary"] == "Warehouse process overview"
    assert Path(search_payload["html_path"]).exists()


def _write_minimal_pptx(path: Path, slide_text: str) -> None:
    slide_xml = f"""
    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
           xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cSld>
        <p:spTree>
          <p:sp>
            <p:txBody>
              <a:p><a:r><a:t>{slide_text}</a:t></a:r></a:p>
            </p:txBody>
          </p:sp>
        </p:spTree>
      </p:cSld>
    </p:sld>
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("ppt/slides/slide1.xml", slide_xml)


def _read_payload(capsys) -> dict[str, object]:
    return json.loads(capsys.readouterr().out)
