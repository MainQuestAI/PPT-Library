from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class AssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetSignature:
    normalized_text_hash: str | None = None
    content_hash: str | None = None
    screenshot_hash: str | None = None


def normalize_text(text: str) -> str:
    raw = str(text or "")
    lowered = raw.lower().strip()
    lowered = re.sub(r"[\r\n\t]+", " ", lowered)
    lowered = re.sub(r"[^\w\u4e00-\u9fff\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " " , lowered)
    return lowered.strip()


def normalized_text_hash(text: str) -> str:
    return _hash_bytes(normalize_text(text).encode("utf-8"))


def content_hash(payload: object) -> str:
    if isinstance(payload, bytes):
        return _hash_bytes(payload)
    if isinstance(payload, bytearray):
        return _hash_bytes(bytes(payload))
    if isinstance(payload, Path):
        return _hash_file(payload)
    return _hash_bytes(str(payload).encode("utf-8"))


def is_high_confidence_duplicate(
    left: AssetSignature,
    right: AssetSignature,
) -> bool:
    if _is_same(left.screenshot_hash, right.screenshot_hash) and left.screenshot_hash is not None:
        return True
    if _is_same(left.normalized_text_hash, right.normalized_text_hash) and left.normalized_text_hash is not None:
        return True
    return False


def is_high_confidence_duplicate_reason(
    left: AssetSignature,
    right: AssetSignature,
) -> Literal["screenshot", "normalized_text", "none"]:
    if _is_same(left.screenshot_hash, right.screenshot_hash) and left.screenshot_hash is not None:
        return "screenshot"
    if _is_same(left.normalized_text_hash, right.normalized_text_hash) and left.normalized_text_hash is not None:
        return "normalized_text"
    return "none"


def thumbnail_target_path(
    root: Path,
    *,
    screenshot_hash: str | None,
    normalized_text_hash: str,
    extension: str = ".png",
) -> Path:
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension.lower() not in ALLOWED_EXTENSIONS:
        raise AssetError(f"Unsupported thumbnail extension: {extension}")
    token = (screenshot_hash or normalized_text_hash).strip().lower()
    if not token:
        raise AssetError("Either screenshot_hash or normalized_text_hash is required.")
    bucket = token[:2] or "00"
    filename = f"{token}{extension}"
    return root / bucket / filename


def _is_same(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left == right


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
