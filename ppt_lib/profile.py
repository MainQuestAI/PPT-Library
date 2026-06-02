from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

ProfileStatus = Literal["empty", "partial", "complete"]


_INDUSTRY_HINTS: dict[str, list[str]] = {
    "零售": [r"零售", r"商超", r"门店", r"连锁", r"超市"],
    "制造": [r"制造", r"工厂", r"产线", r"工艺"],
    "金融": [r"金融", r"银行", r"保险", r"证券", r"投融资", r"融资", r"信贷"],
    "科技": [r"科技", r"人工智能", r"AI", r"算法", r"大模型", r"软件", r"SaaS"],
    "教育": [r"教育", r"培训", r"课程", r"学习", r"招生"],
    "医疗": [r"医疗", r"医院", r"健康", r"药", r"药企", r"病例"],
}

_DECK_TYPE_HINTS: dict[str, list[str]] = {
    "方案": [r"\b方案\b", r"\b提案\b", r"解决方案", r"proposal", r"solution"],
    "复盘": [r"\b复盘\b", r"复盘会", r"回顾", r"post[- ]?mortem", r"总结"],
    "路线图": [r"路线图", r"roadmap", r"规划", r"里程碑"],
    "周会": [r"\b周会\b", r"\b周报\b", r"weekly", r"周报总结"],
    "汇报": [r"汇报", r"汇报会", r"\b汇报材料\b", r"\breview\b", r"\b述职\b"],
}

_SUMMARY_TEMPLATES: dict[str, str] = {
    "方案": "输出摘要要突出业务目标、落地路径、关键风险与交付动作。",
    "复盘": "输出摘要要保留事实先行、原因分析与可复用改进点。",
    "路线图": "输出摘要要保留阶段划分、里程碑和优先级。",
    "周会": "输出摘要要突出本周变化、待办与对外交付状态。",
    "汇报": "输出摘要要包含结论、证据和建议下一步。",
}

_COMPANY_SUFFIX = ("公司", "有限公司", "科技", "集团", "Corp", "Corporation", "Inc", "LLC", "Ltd", "股份公司", "有限责任公司")
_PRODUCT_HINTS = ["平台", "系统", "服务", "SaaS", "产品", "工具", "平台化", "解决方案", "模型"]
_STOP_TERMS = {"我们", "该", "这个", "这份", "本次", "该项目", "可以", "用于", "以", "并", "进行", "并发"}


@dataclass(frozen=True)
class WorkspaceProfile:
    industry: list[str]
    company_or_brand: list[str]
    products_or_services: list[str]
    deck_types: list[str]
    terminology: list[str]
    summary_guidelines: list[str]
    source_count: int
    status: ProfileStatus


def build_workspace_profile_payload(
    baseline_texts: Mapping[int, str] | Iterable[str],
) -> WorkspaceProfile:
    texts = _normalize_sources(baseline_texts)
    source_count = len(texts)
    merged = " ".join(texts)
    status: ProfileStatus
    if source_count == 0:
        status = "empty"
    elif source_count == 1 and len(merged) < 24:
        status = "partial"
    else:
        status = "complete"

    industry = _extract_matching_labels(merged, _INDUSTRY_HINTS)
    deck_types = _extract_matching_labels(merged, _DECK_TYPE_HINTS)
    company_or_brand = _extract_company_or_brand(texts)
    products_or_services = _extract_products_or_services(merged, texts)
    terminology = _extract_terminology(merged)
    summary_guidelines = _build_summary_guidelines(deck_types)

    return WorkspaceProfile(
        industry=industry,
        company_or_brand=company_or_brand,
        products_or_services=products_or_services,
        deck_types=deck_types,
        terminology=terminology,
        summary_guidelines=summary_guidelines,
        source_count=source_count,
        status=status,
    )


def _normalize_sources(baseline_texts: Mapping[int, str] | Iterable[str]) -> list[str]:
    if isinstance(baseline_texts, dict):
        raw = [str(value) for value in baseline_texts.values()]
    else:
        raw = [str(value) for value in baseline_texts]
    return [line.strip() for line in raw if str(line).strip()]


def _extract_matching_labels(text: str, mapping: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for label, patterns in mapping.items():
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns):
            found.append(label)
    return found

def _extract_company_or_brand(texts: list[str]) -> list[str]:
    candidates: list[str] = []
    pattern = (
        r"[A-Za-z0-9][A-Za-z0-9&.\-]*"
        r"\s*(?:[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})*|有限公司|公司|集团|股份公司|科技|企业)?"
    )
    for line in texts:
        for token in re.findall(pattern, line):
            clean = token.strip().strip("，。；;,. ")
            if not clean:
                continue
            if any(clean.endswith(suffix) for suffix in _COMPANY_SUFFIX):
                candidates.append(_normalize_company(clean))
                continue
            for suffix in _COMPANY_SUFFIX:
                if suffix in clean:
                    if len(clean) <= len(suffix) + 2:
                        continue
                    if clean.count(" ") <= 3:
                        candidates.append(_normalize_company(clean))
                    break
        for match in re.findall(r"[\u4e00-\u9fff]{2,8}(?:公司|集团|科技|有限)", line):
            candidates.append(_normalize_company(match))
    return _dedupe_preserve_order(candidates)


def _extract_products_or_services(text: str, texts: list[str]) -> list[str]:
    candidates: list[str] = []
    tokens = [tok for tok in re.findall(r"[A-Za-z0-9]{2,}[-]?[A-Za-z0-9]*", text)]
    for token in tokens:
        if token.lower() in {w.lower() for w in _STOP_TERMS}:
            continue
        if any(hint.lower() in token.lower() for hint in _PRODUCT_HINTS):
            candidates.append(token)
    for line in texts:
        candidates.extend(
            hint
            for hint in _PRODUCT_HINTS
            if hint in line
        )
    return _dedupe_preserve_order([item for item in candidates if len(item) > 1])


def _extract_terminology(text: str) -> list[str]:
    alpha = re.findall(r"\b[A-Za-z][A-Za-z0-9+.-]{1,}\b", text)
    zh_phrases = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    counter = Counter(token.strip() for token in alpha + zh_phrases)
    terms: list[str] = []
    for token, count in counter.most_common():
        if token in _STOP_TERMS:
            continue
        if len(token) < 2:
            continue
        if token.lower() in {"the", "and", "for", "to", "of", "in", "on", "with"}:
            continue
        if count >= 1:
            terms.append(token)
        if len(terms) >= 12:
            break
    return terms


def _build_summary_guidelines(deck_types: list[str]) -> list[str]:
    defaults = [
        "保持结论先行，用1-2句话先写出本页价值点。",
        "保留关键数字、对象、时间线与风险边界。",
        "避免仅罗列清单，尽量给出可执行建议。",
    ]
    dynamic = [_SUMMARY_TEMPLATES[item] for item in deck_types if item in _SUMMARY_TEMPLATES]
    return _dedupe_preserve_order(dynamic + defaults)


def _normalize_company(name: str) -> str:
    return re.sub(r"\s+", "", name).strip("“”\"'")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        if not value:
            continue
        seen.add(value)
        output.append(value)
    return output
