from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ppt_lib.assets import content_hash, normalized_text_hash
from ppt_lib.db import connect, get_active_workspace_profile, init_db, update_slide_summary_fields
from ppt_lib.settings import Settings


class SummaryClient(Protocol):
    def summarize(self, prompt: str) -> str | dict[str, object] | Any:
        """Return AI generated summary payload."""


@dataclass(frozen=True)
class SlideSummary:
    ai_summary: str
    visual_summary: str
    summary_status: Literal["ok", "fallback", "warning"]
    warnings: list[str]


@dataclass(frozen=True)
class EnrichmentRunResult:
    processed: int
    remaining: int
    warnings: list[str]


def generate_slide_summary(
    raw_text: str,
    vision_metadata: dict[str, object] | None,
    workspace_profile: dict[str, object] | None,
    *,
    client: SummaryClient | None = None,
    fallback_length: int = 180,
) -> SlideSummary:
    text = str(raw_text).strip()
    metadata = vision_metadata or {}
    profile_hint = _format_profile_hint(workspace_profile)
    visual_summary = _extract_visual_summary(metadata)

    if not client:
        return _fallback_summary(
            text=text,
            visual_summary=visual_summary,
            warnings=["SUMMARY_FALLBACK_TEXT_MODE"],
            status="fallback",
            fallback_length=fallback_length,
        )

    try:
        payload = client.summarize(_build_prompt(text, metadata, profile_hint))
        parsed = _parse_client_payload(payload)
        raw_ai_summary = parsed.get("ai_summary")
        raw_visual_summary = parsed.get("visual_summary")
        ai_summary = raw_ai_summary.strip() if isinstance(raw_ai_summary, str) else ""
        parsed_visual = raw_visual_summary.strip() if isinstance(raw_visual_summary, str) else ""
        raw_summary_status = parsed.get("summary_status", "ok")
        summary_status: Literal["ok", "fallback", "warning"] = "warning"
        if raw_summary_status == "ok":
            summary_status = "ok"
        elif raw_summary_status == "fallback":
            summary_status = "fallback"

        raw_warnings = parsed.get("warnings", [])
        warnings = [item for item in raw_warnings if isinstance(item, str)] if isinstance(raw_warnings, list) else []
        if not ai_summary:
            return _fallback_summary(
                text=text,
                visual_summary=parsed_visual or visual_summary,
                warnings=warnings + ["SUMMARY_EMPTY_RESPONSE_FALLBACK"],
                status="fallback",
                fallback_length=fallback_length,
            )

        return SlideSummary(
            ai_summary=ai_summary,
            visual_summary=parsed_visual or visual_summary or "无可用视觉摘要",
            summary_status=summary_status,
            warnings=warnings,
        )
    except Exception as exc:
        return _fallback_summary(
            text=text,
            visual_summary=visual_summary,
            warnings=[f"SUMMARY_LM_UNAVAILABLE:{type(exc).__name__}:{exc}", *_format_warning_profile(profile_hint)],
            status="fallback",
            fallback_length=fallback_length,
        )


def enrich_pending_slides(
    settings: Settings,
    *,
    limit: int | None = None,
    client: SummaryClient | None = None,
) -> EnrichmentRunResult:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    active_profile = get_active_workspace_profile(conn)
    profile_payload: dict[str, object] | None = None
    profile_id: int | None = None
    if active_profile is not None:
        profile_id = active_profile.id
        row = conn.execute(
            "SELECT metadata_json FROM workspace_profiles WHERE id = ?",
            (active_profile.id,),
        ).fetchone()
        profile_payload = _parse_profile_json(row[0] if row else None)

    query = """
        SELECT id, text_content, metadata_json
        FROM slides
        WHERE summary_status IS NULL OR summary_status IN ('pending', 'failed')
        ORDER BY id
    """
    params: list[object] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    warnings: list[str] = []
    for row in rows:
        slide_id = int(row[0])
        raw_text = str(row[1] or "")
        metadata = _parse_profile_json(row[2])
        summary = generate_slide_summary(
            raw_text,
            metadata,
            profile_payload,
            client=client,
        )
        warnings.extend(summary.warnings)
        update_slide_summary_fields(
            conn,
            slide_id,
            raw_text=raw_text,
            ai_summary=summary.ai_summary,
            visual_summary=summary.visual_summary,
            summary_status=summary.summary_status,
            profile_id=profile_id,
            text_hash=normalized_text_hash(raw_text),
            content_hash=content_hash(raw_text),
            commit=False,
        )
    conn.commit()
    remaining = int(
        conn.execute(
            "SELECT COUNT(*) FROM slides WHERE summary_status IS NULL OR summary_status IN ('pending', 'failed')"
        ).fetchone()[0]
    )
    return EnrichmentRunResult(processed=len(rows), remaining=remaining, warnings=_dedupe(warnings))


def profile_payload_from_row(raw: str | None) -> dict[str, object]:
    return _parse_profile_json(raw)


def _build_prompt(raw_text: str, vision_metadata: dict[str, object], profile_hint: str) -> str:
    profile_section = profile_hint or "未提供工作区画像信息。"
    metadata_section = _format_metadata(vision_metadata) or "无可用视觉元信息。"
    text_section = raw_text.strip() or "无可用正文文本，仅凭视觉信息生成摘要。"
    return (
        "请基于以下信息输出 JSON，仅返回 JSON 字段：\n"
        "{\n"
        '  "ai_summary": "一句到三句内的文字摘要",\n'
        '  "visual_summary": "一句话视觉信息摘要",\n'
        '  "summary_status": "ok/ warning"\n'
        "}\n"
        f"Workspace Profile: {profile_section}\n"
        f"Vision Metadata: {metadata_section}\n"
        f"Raw Text: {text_section}"
    )


def _parse_client_payload(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"ai_summary": text}
    return {}


def _parse_profile_json(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _fallback_summary(
    *,
    text: str,
    visual_summary: str,
    warnings: list[str],
    status: str,
    fallback_length: int,
) -> SlideSummary:
    excerpt = _extractive_fallback(text, fallback_length)
    return SlideSummary(
        ai_summary=excerpt,
        visual_summary=visual_summary or "无可用视觉摘要",
        summary_status="fallback" if status else "warning",
        warnings=warnings,
    )


def _extractive_fallback(text: str, length: int) -> str:
    if not text.strip():
        return "该页缺少可直接归纳的正文文本，当前摘要采用降级模式。"
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= length:
        return f"文本摘要：{normalized}"
    return f"文本摘要：{normalized[: max(1, length)].rstrip()}..."

def _extract_visual_summary(metadata: dict[str, object]) -> str:
    parts: list[str] = []
    for key in ("layout_type", "chart_types", "visual_elements", "key_entities", "use_cases", "business_domain"):
        value = metadata.get(key)
        if value:
            parts.append(f"{key}:{_format_metadata_value(value)}")
    return "; ".join(parts)


def _format_metadata_value(value: object) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if item is not None)
    return str(value)


def _format_metadata(metadata: dict[str, object]) -> str:
    if not metadata:
        return ""
    return "; ".join(f"{k}:{_format_metadata_value(v)}" for k, v in sorted(metadata.items()) if v is not None)


def _format_profile_hint(profile: dict[str, object] | None) -> str:
    if not profile:
        return ""
    items = [f"{k}:{v}" for k, v in sorted(profile.items()) if v not in (None, "", [], {}, ())]
    return "; ".join(items)


def _format_warning_profile(profile_hint: str) -> list[str]:
    return ["SUMMARY_PROFILE_NOTE: profile_hint_present"] if profile_hint else []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
