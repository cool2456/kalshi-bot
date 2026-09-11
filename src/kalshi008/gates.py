from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .api import KalshiClient
from .config import DEFINITIVE_RESULTS
from .ingest import parse_ts


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: dict = field(default_factory=dict)

    def render(self) -> str:
        head = f"[{'PASS' if self.passed else 'FAIL'}] {self.name}"
        lines = [head]
        for k, v in self.detail.items():
            lines.append(f"        {k}: {v}")
        return "\n".join(lines)


def gate_definitive_outcomes(analysis_markets: Sequence[dict], all_markets: Sequence[dict]) -> GateResult:
    bad = [m["ticker"] for m in analysis_markets if m.get("result") not in DEFINITIVE_RESULTS]
    excluded = collections.Counter(
        str(m.get("result")) for m in all_markets if m.get("result") not in DEFINITIVE_RESULTS
    )
    return GateResult(
        name="Step 2 gate: every analysed market has a definitive YES/NO outcome",
        passed=not bad,
        detail={
            "analysis_markets": len(analysis_markets),
            "non_definitive_in_analysis_set": len(bad),
            "examples": bad[:10],
            "excluded_and_counted_by_result_value": dict(excluded),
            "total_excluded_non_definitive": sum(excluded.values()),
        },
    )


def gate_result_matches_settlement_value(markets: Sequence[dict]) -> GateResult:
    mismatches = []
    checked = 0
    for m in markets:
        sv, nv = m.get("settlement_value_dollars"), m.get("notional_value_dollars")
        if sv is None or nv in (None, "", "0", "0.0000"):
            continue
        try:
            ratio = float(sv) / float(nv)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        checked += 1
        r = m.get("result")
        if r == "yes" and abs(ratio - 1.0) > 1e-6:
            mismatches.append((m["ticker"], r, ratio))
        elif r == "no" and abs(ratio - 0.0) > 1e-6:
            mismatches.append((m["ticker"], r, ratio))
    return GateResult(
        name="Step 2 gate: `result` agrees with settlement_value/notional on every market",
        passed=not mismatches,
        detail={
            "markets_checked": checked,
            "mismatches": len(mismatches),
            "examples": mismatches[:10],
        },
    )


def hand_check_settlement_join(
    client: KalshiClient, markets: Sequence[dict], n_per_category: int = 4,
    categories: Sequence[str] = ("Weather", "Economics", "Politics", "Sports", "Financial", "Other"),
) -> GateResult:
    by_cat: dict[str, list[dict]] = collections.defaultdict(list)
    for m in markets:
        by_cat[m["category"]].append(m)

    rows: list[dict] = []
    disagreements: list[dict] = []
    for cat in categories:
        pool = sorted(by_cat.get(cat, []), key=lambda m: m["ticker"])
        if not pool:
            continue
        step = max(1, len(pool) // n_per_category)
        picked = pool[::step][:n_per_category]
        for m in picked:
            fresh = client.get(f"/markets/{m['ticker']}", allow_404=True)
            source = "live"
            if not fresh or "market" not in fresh:
                fresh = client.get(f"/historical/markets/{m['ticker']}", allow_404=True)
                source = "archive"
            if not fresh or "market" not in fresh:
                disagreements.append({"ticker": m["ticker"],
                                      "issue": "not retrievable from either tier"})
                continue
            f = fresh["market"]
            row = {
                "category": cat,
                "ticker": m["ticker"],
                "refetched_from": source,
                "title": (f.get("title") or "")[:70],
                "census_result": m.get("result"),
                "refetched_result": f.get("result"),
                "census_event": m.get("event_ticker"),
                "refetched_event": f.get("event_ticker"),
                "census_close": m.get("close_time"),
                "refetched_close": f.get("close_time"),
                "settlement_value": f.get("settlement_value_dollars"),
                "agrees": (
                    m.get("result") == f.get("result")
                    and m.get("event_ticker") == f.get("event_ticker")
                    and parse_ts(m.get("close_time")) == parse_ts(f.get("close_time"))
                ),
            }
            rows.append(row)
            if not row["agrees"]:
                disagreements.append(row)
    return GateResult(
        name="Step 2 gate: hand-check of the settlement join on a cross-category sample",
        passed=(not disagreements) and len(rows) >= 20,
        detail={
            "markets_hand_checked": len(rows),
            "categories_covered": sorted({r["category"] for r in rows}),
            "disagreements": len(disagreements),
            "disagreement_detail": disagreements[:10],
            "rows": rows,
        },
    )


def gate_mutually_exclusive_events(
    events: dict[str, dict], markets: Sequence[dict], require_complete: bool = True
) -> GateResult:
    by_event: dict[str, list[dict]] = collections.defaultdict(list)
    for m in markets:
        by_event[m["event_ticker"]].append(m)

    checked = 0
    violations: list[dict] = []
    partially_voided = 0
    skipped_incomplete = 0
    skipped_no_metadata = 0
    skipped_not_exclusive = 0
    yes_counts: collections.Counter = collections.Counter()

    for ev_ticker, ms in by_event.items():
        ev = events.get(ev_ticker)
        if not ev:
            skipped_no_metadata += 1
            continue
        if not ev.get("mutually_exclusive"):
            skipped_not_exclusive += 1
            continue
        if any(m.get("result") not in DEFINITIVE_RESULTS for m in ms):
            partially_voided += 1
            continue
        if require_complete and ev.get("n_markets_expected") not in (None, len(ms)):
            skipped_incomplete += 1
            continue
        checked += 1
        n_yes = sum(1 for m in ms if m.get("result") == "yes")
        yes_counts[n_yes] += 1
        if n_yes > 1:
            violations.append({
                "event_ticker": ev_ticker, "n_markets": len(ms), "n_yes": n_yes,
                "tickers": [m["ticker"] for m in ms][:12],
            })
    all_no = [
        ev for ev, ms in by_event.items()
        if events.get(ev, {}).get("mutually_exclusive")
        and all(m.get("result") in DEFINITIVE_RESULTS for m in ms)
        and not any(m.get("result") == "yes" for m in ms)
    ]
    return GateResult(
        name="Step 4 gate: at most one YES on every mutually-exclusive event",
        passed=(not violations) and checked > 0,
        detail={
            "exclusive_events_checked": checked,
            "vacuous_no_events_checked": checked == 0,
            "yes_count_distribution": dict(sorted(yes_counts.items())),
            "violations": len(violations),
            "violation_examples": violations[:10],
            "events_skipped_partially_voided": partially_voided,
            "events_skipped_incomplete_market_list": skipped_incomplete,
            "events_skipped_no_metadata_fetched": skipped_no_metadata,
            "events_skipped_not_mutually_exclusive": skipped_not_exclusive,
            "exclusive_events_with_zero_yes": len(all_no),
            "zero_yes_examples": all_no[:8],
            "note": (
                "Zero-YES exclusive events are NOT violations. Kalshi's flag means at "
                "most one market can resolve YES; it does not promise the listed outcomes "
                "are exhaustive. A strike ladder whose settlement falls outside every band "
                "resolves all-NO legitimately. Two or more YES in one exclusive event "
                "WOULD indicate a wrong grouping, and that count is `violations`."
            ),
        },
    )


def markets_per_event_distribution(markets: Sequence[dict]) -> dict:
    by_event: collections.Counter = collections.Counter(m["event_ticker"] for m in markets)
    sizes = list(by_event.values())
    if not sizes:
        return {"distinct_events": 0, "markets": 0}
    buckets = collections.Counter()
    for s in sizes:
        if s == 1:
            buckets["1"] += 1
        elif s == 2:
            buckets["2"] += 1
        elif s <= 5:
            buckets["3-5"] += 1
        elif s <= 10:
            buckets["6-10"] += 1
        elif s <= 50:
            buckets["11-50"] += 1
        else:
            buckets[">50"] += 1
    srt = sorted(sizes)
    return {
        "markets": len(markets),
        "distinct_events": len(by_event),
        "markets_per_event_mean": round(sum(sizes) / len(sizes), 3),
        "markets_per_event_median": srt[len(srt) // 2],
        "markets_per_event_max": max(sizes),
        "histogram": dict(buckets),
        "effective_n_ratio": round(len(by_event) / len(markets), 4),
    }
