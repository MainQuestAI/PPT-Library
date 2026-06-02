"""Canonical label sets for slide annotation: industries, scenarios, narrative roles."""

from __future__ import annotations

# Narrative role labels (structural role in a presentation narrative)
NARRATIVE_ROLES = [
    "opener",
    "problem",
    "solution",
    "architecture",
    "case",
    "roi",
    "cta",
    "appendix",
]

# Industry labels (common in enterprise sales/martech/consulting)
INDUSTRY_LABELS = [
    "retail",
    "fmcg",
    "beauty",
    "fashion",
    "manufacturing",
    "healthcare",
    "education",
    "finance",
    "real_estate",
    "automotive",
    "technology",
    "media",
    "logistics",
    "energy",
    "government",
    "cross_industry",
]

# Scenario labels (presentation context)
SCENARIO_LABELS = [
    "pitch",
    "proposal",
    "case_study",
    "training",
    "internal_review",
    "product_demo",
    "strategy",
    "methodology",
    "general",
]
