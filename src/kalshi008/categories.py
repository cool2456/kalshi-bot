"""Kalshi's own 18 series categories mapped onto PREREG_008 s4's six.

s4 requires grouping by "Kalshi's own series categorisation" into six categories, but
does not state the mapping; Kalshi publishes 18 distinct strings. The mapping below was
fixed in DECISIONS_008.md (decision 3) before any analysis ran.

Elections and Mentions join Politics: both are political-outcome markets and s4 names no
separate bucket. Crypto joins Financial on s4's own parenthetical, "Financial
(crypto/index levels)". Commodities and Companies stay in Other, because that
parenthetical names only crypto and index levels.
"""

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
"""Any Kalshi category string not in the table above. Mapped to Other and REPORTED --
if Kalshi adds a category after this was frozen, it must be visible, not silent."""


def to_prereg_category(kalshi_category: str | None) -> str:
    """Map one Kalshi series category onto the six frozen by s4."""
    if kalshi_category is None:
        UNMAPPED_CATEGORIES.add("<missing>")
        return "Other"
    mapped = KALSHI_TO_PREREG.get(kalshi_category)
    if mapped is None:
        UNMAPPED_CATEGORIES.add(kalshi_category)
        return "Other"
    return mapped


def check_mapping_covers(observed: set[str]) -> list[str]:
    """Return Kalshi categories seen in the data that the frozen table does not name."""
    return sorted(c for c in observed if c not in KALSHI_TO_PREREG)


assert set(KALSHI_TO_PREREG.values()) <= set(CATEGORIES)
