from __future__ import annotations

from pathlib import Path

import pytest

from ppt_lib.config import load_settings
from ppt_lib.vision import (
    CloudVisionProvider,
    LMStudioVisionProvider,
    OllamaVisionProvider,
    TextExtractionVisionProvider,
    VisionProviderError,
    VisionResult,
    build_vision_chain,
    describe_slide_with_fallback,
    parse_vision_payload,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_build_chain_local_first(tmp_path: Path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "vision_api_key": "vision-key"},
        config_path=tmp_path / "config.yml",
    )

    chain = build_vision_chain(settings)

    assert [type(provider) for provider in chain] == [
        OllamaVisionProvider,
        LMStudioVisionProvider,
        CloudVisionProvider,
        TextExtractionVisionProvider,
    ]


def test_describe_slide_uses_first_successful_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingProvider:
        def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
            raise VisionProviderError("down", code="VISION_PROVIDER_DOWN")

    class SuccessfulProvider:
        def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
            return VisionResult(
                source="vision_model",
                title="Architecture",
                text_content="diagram",
                metadata={"chart_types": []},
                confidence=0.9,
                warnings=[],
            )

    monkeypatch.setattr(
        "ppt_lib.vision.build_vision_chain",
        lambda settings: [FailingProvider(), SuccessfulProvider()],
    )
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    result = describe_slide_with_fallback(tmp_path / "slide.png", "fallback", settings)

    assert result.source == "vision_model"
    assert result.title == "Architecture"
    assert "VISION_PROVIDER_DOWN" in result.warnings[0]


def test_text_extraction_last_resort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingProvider:
        def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
            raise VisionProviderError("bad", code="VISION_BAD")

    monkeypatch.setattr("ppt_lib.vision.build_vision_chain", lambda settings: [FailingProvider()])
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    result = describe_slide_with_fallback(tmp_path / "slide.png", "plain text", settings)

    assert result.source == "text_extraction"
    assert result.text_content == "plain text"
    assert result.confidence == 0.2


def test_empty_image_and_empty_text_returns_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ppt_lib.vision.build_vision_chain", lambda settings: [])
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    result = describe_slide_with_fallback(tmp_path / "slide.png", "", settings)

    assert result.source == "text_extraction"
    assert result.text_content == ""
    assert "VISION_EMPTY_CONTENT" in result.warnings


def test_invalid_json_response_records_warning() -> None:
    result = parse_vision_payload("plain non json response", fallback_text="fallback")

    assert result.source == "vision_model"
    assert result.text_content == "plain non json response"
    assert "VISION_INVALID_JSON" in result.warnings


def test_metadata_types_stable() -> None:
    result = parse_vision_payload(
        '{"title":"T","text_content":"Body","metadata":{"chart_types":["flow"]},"confidence":0.7}',
        fallback_text="fallback",
    )

    assert isinstance(result.metadata, dict)
    assert result.metadata["chart_types"] == ["flow"]
    assert result.confidence == 0.7


def test_confidence_range_enforced() -> None:
    result = parse_vision_payload(
        '{"title":"T","text_content":"Body","metadata":{},"confidence":2.5}',
        fallback_text="fallback",
    )

    assert result.confidence == 1.0


def test_ollama_success_returns_vision_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(PNG_1X1)

    def fake_post_json(url, payload, *, timeout_seconds, headers=None):
        assert url == "http://ollama/api/generate"
        assert payload["model"] == "llava-test"
        assert payload["images"]
        return {
            "response": (
                '{"title":"Sales","text_content":"Pipeline chart",'
                '"metadata":{"chart_types":["bar"]},"confidence":0.91}'
            )
        }

    monkeypatch.setattr("ppt_lib.vision._post_json", fake_post_json)
    provider = OllamaVisionProvider(base_url="http://ollama", model="llava-test")

    result = provider.describe_slide(image, "fallback")

    assert result.source == "vision_model"
    assert result.title == "Sales"
    assert result.metadata["chart_types"] == ["bar"]


def test_lmstudio_fallback_after_ollama_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(PNG_1X1)
    calls: list[str] = []

    def fake_post_json(url, payload, *, timeout_seconds, headers=None):
        calls.append(url)
        if "11434" in url:
            raise VisionProviderError("down", code="VISION_PROVIDER_UNAVAILABLE")
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["name"] == "slide_description"
        assert payload["response_format"]["json_schema"]["strict"] is True
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"title":"Ops","text_content":"Operational flow",'
                            '"metadata":{"layout_type":"process"},"confidence":0.8}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("ppt_lib.vision._post_json", fake_post_json)
    settings = load_settings(
        {"home_dir": tmp_path, "lmstudio_vision_model": "qwen/qwen3.6-27b"},
        config_path=tmp_path / "config.yml",
    )

    result = describe_slide_with_fallback(image, "fallback", settings)

    assert len(calls) == 2
    assert result.title == "Ops"
    assert result.warnings[0].startswith("VISION_PROVIDER_UNAVAILABLE")


def test_lmstudio_retries_text_after_json_schema_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(PNG_1X1)
    formats: list[str] = []

    def fake_post_json(url, payload, *, timeout_seconds, headers=None):
        formats.append(str(payload["response_format"]["type"]))
        if payload["response_format"]["type"] == "json_schema":
            raise VisionProviderError("schema unsupported", code="VISION_HTTP_ERROR")
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"title":"Fallback","text_content":"JSON object worked",'
                            '"metadata":{},"confidence":0.7}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("ppt_lib.vision._post_json", fake_post_json)
    provider = LMStudioVisionProvider(base_url="http://lmstudio", model="local")

    result = provider.describe_slide(image, "fallback")

    assert formats == ["json_schema", "text"]
    assert result.title == "Fallback"
    assert result.warnings[0].startswith("VISION_FORMAT_FALLBACK")


def test_os_error_provider_continues_to_text_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingProvider:
        def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
            raise FileNotFoundError("missing screenshot")

    monkeypatch.setattr("ppt_lib.vision.build_vision_chain", lambda settings: [FailingProvider()])
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    result = describe_slide_with_fallback(tmp_path / "missing.png", "plain text", settings)

    assert result.source == "text_extraction"
    assert result.text_content == "plain text"
    assert result.warnings[0].startswith("VISION_PROVIDER_OS_ERROR")


def test_cloud_fallback_used_when_local_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(PNG_1X1)
    seen_headers: dict[str, str] = {}

    def fake_post_json(url, payload, *, timeout_seconds, headers=None):
        seen_headers.update(headers or {})
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"title":"Cloud","text_content":"Cloud summary",'
                            '"metadata":{"language":"en"},"confidence":0.7}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("ppt_lib.vision._post_json", fake_post_json)
    provider = CloudVisionProvider("secret", base_url="https://vision.example/v1", model="vision-test")

    result = provider.describe_slide(image, "fallback")

    assert seen_headers["Authorization"] == "Bearer secret"
    assert result.title == "Cloud"


def test_image_too_large_records_provider_error(tmp_path: Path) -> None:
    image = tmp_path / "slide.png"
    image.write_bytes(PNG_1X1)
    provider = OllamaVisionProvider(max_image_bytes=1)

    with pytest.raises(VisionProviderError) as exc_info:
        provider.describe_slide(image, "fallback")

    assert exc_info.value.code == "VISION_IMAGE_TOO_LARGE"


def test_non_image_file_rejected_before_provider_call(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"not an image")
    provider = OllamaVisionProvider()

    with pytest.raises(VisionProviderError) as exc_info:
        provider.describe_slide(pptx, "fallback")

    assert exc_info.value.code == "VISION_IMAGE_UNSUPPORTED"


def test_invalid_confidence_type_is_coerced() -> None:
    result = parse_vision_payload(
        '{"title":"T","text_content":"Body","metadata":{},"confidence":"high"}',
        fallback_text="fallback",
    )

    assert result.confidence == 0.5
    assert "VISION_CONFIDENCE_TYPE_COERCED" in result.warnings
