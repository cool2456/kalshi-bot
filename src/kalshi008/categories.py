from __future__ import annotations

from .config import CATEGORIES

KALSHI_TO_PREREG: dict[str, str] = {
    "Climate and Weather": "Weather",
    "Economics": "Economics",
    "Politics": "Politics",
    "Elections": "Politics",
    "Mentions": "Politics",
    "Sports": "Sports",
    "Financials": "Financial",
    "Crypto": "Financial",
    "Entertainment": "Other",
    "Science and Technology": "Other",
    "Companies": "Other",
    "World": "Other",
    "Health": "Other",
    "Commodities": "Other",
    "Social": "Other",
    "Transportation": "Other",
    "Exotics": "Other",
    "Education": "Other",
}

UNMAPPED_CATEGORIES: set[str] = set()


def to_prereg_category(kalshi_category: str | None) -> str:
    if kalshi_category is None:
        UNMAPPED_CATEGORIES.add("<missing>")
        return "Other"
    mapped = KALSHI_TO_PREREG.get(kalshi_category)
    if mapped is None:
        UNMAPPED_CATEGORIES.add(kalshi_category)
        return "Other"
    return mapped


def check_mapping_covers(observed: set[str]) -> list[str]:
    return sorted(c for c in observed if c not in KALSHI_TO_PREREG)


assert set(KALSHI_TO_PREREG.values()) <= set(CATEGORIES)
