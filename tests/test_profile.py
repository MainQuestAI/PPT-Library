from __future__ import annotations

from ppt_lib.profile import build_workspace_profile_payload


def test_build_workspace_profile_payload_extracts_expected_fields() -> None:
    baseline = {
        0: "零售行业的 RetailTech科技公司发布供应链和仓储平台解决方案，支持WMS系统。",
        1: "本页是年度路线图，包含实施里程碑和关键KPI。",
    }

    profile = build_workspace_profile_payload(baseline)

    assert profile.source_count == 2
    assert "零售" in profile.industry
    assert "零售行业" in profile.deck_types or "路线图" in profile.deck_types
    assert any(item.startswith("RetailTech") or item.startswith("科技公司") for item in profile.company_or_brand)
    assert "平台" in profile.products_or_services
    assert profile.terminology
    assert profile.summary_guidelines
    assert profile.status == "complete"


def test_build_workspace_profile_payload_empty_source() -> None:
    profile = build_workspace_profile_payload({})

    assert profile.source_count == 0
    assert profile.industry == []
    assert profile.company_or_brand == []
    assert profile.products_or_services == []
    assert profile.status == "empty"
