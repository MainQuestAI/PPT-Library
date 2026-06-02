from __future__ import annotations

from pathlib import Path

from ppt_lib.assets import (
    AssetError,
    AssetSignature,
    content_hash,
    is_high_confidence_duplicate,
    is_high_confidence_duplicate_reason,
    normalize_text,
    normalized_text_hash,
    thumbnail_target_path,
)


def test_normalized_text_hash_stable_with_whitespace_and_punctuation() -> None:
    first = normalized_text_hash("  Hello, World!!!   This\nis  test.  ")
    second = normalized_text_hash("hello world this is test")

    assert first == second


def test_normalize_text_keeps_chinese_content() -> None:
    assert normalize_text(" 供应链  体系；   ") == "供应链 体系"


def test_content_hash_stable_for_bytes() -> None:
    payload = b"sample content"

    assert content_hash(payload) == content_hash(payload)


def test_duplicate_candidate_from_screenshot_hash() -> None:
    left = AssetSignature(normalized_text_hash="a", screenshot_hash="snap123")
    right = AssetSignature(normalized_text_hash="b", screenshot_hash="snap123")

    assert is_high_confidence_duplicate(left, right)
    assert is_high_confidence_duplicate_reason(left, right) == "screenshot"


def test_duplicate_candidate_from_normalized_text_hash() -> None:
    left = AssetSignature(normalized_text_hash="texthash", screenshot_hash=None)
    right = AssetSignature(normalized_text_hash="texthash", screenshot_hash="other")

    assert is_high_confidence_duplicate(left, right)
    assert is_high_confidence_duplicate_reason(left, right) == "normalized_text"


def test_no_duplicate_without_high_confidence_keys() -> None:
    left = AssetSignature(normalized_text_hash="a", screenshot_hash=None)
    right = AssetSignature(normalized_text_hash="b", screenshot_hash="different")

    assert not is_high_confidence_duplicate(left, right)
    assert is_high_confidence_duplicate_reason(left, right) == "none"


def test_thumbnail_target_path_layout(tmp_path) -> None:
    target = thumbnail_target_path(tmp_path, screenshot_hash="ab12cd", normalized_text_hash="zz")

    assert target.parent == tmp_path / "ab"
    assert target.name == "ab12cd.png"


def test_thumbnail_target_path_invalid_ext_raises() -> None:
    try:
        thumbnail_target_path(Path("/tmp"), screenshot_hash="ab", normalized_text_hash="cd", extension=".gif")
    except AssetError:
        return
    raise AssertionError("Expected AssetError")
