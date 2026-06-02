from __future__ import annotations

import zipfile
from pathlib import Path

from ppt_lib.config import load_settings
from ppt_lib.indexer import extract_pptx_text, index_file
from ppt_lib.searcher import SearchOptions, search


def test_chinese_pptx_fixture_text_extraction(tmp_path: Path) -> None:
    deck = tmp_path / "中文方案.pptx"
    _write_pptx(deck, "仓储入库流程")

    text_by_slide = extract_pptx_text(deck)

    assert text_by_slide == {0: "仓储入库流程"}


def test_chinese_pptx_fixture_index_search_round_trip(tmp_path: Path, monkeypatch) -> None:
    deck = tmp_path / "中文方案.pptx"
    _write_pptx(deck, "仓储入库流程")
    settings = load_settings(
        {
            "home_dir": tmp_path / "home",
            "embedding_provider": "fake",
            "vision_provider": "text_extraction",
        },
        config_path=tmp_path / "home" / "config.yml",
    )
    monkeypatch.setattr("ppt_lib.indexer.render_pptx_slides", lambda path, output_dir, max_workers=4: [])

    result = index_file(deck, settings)
    results = search("仓储", SearchOptions(top_k=5, threshold=0.0), settings)

    assert result.status == "indexed"
    assert result.slides_indexed == 1
    assert results[0].text_summary == "仓储入库流程"


def _write_pptx(path: Path, slide_text: str) -> None:
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
