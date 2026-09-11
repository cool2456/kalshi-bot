from __future__ import annotations

import collections
import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .api import KalshiClient
from .categories import check_mapping_covers, to_prereg_category
from .config import (
    CANDLE_PERIOD_MINUTES, DEFINITIVE_RESULTS, DERIVED_DIR, HORIZONS, SAMPLE_SEED,
)
from .horizons import Snapshot, snapshots_for_market
from .ingest import (
    _slim, census_archive_tier, census_live_tier, event_sample_score, fetch_candles,
    fetch_series, is_combo, iso, parse_ts, read_jsonl, select_events_stratified,
    series_ticker_of, write_jsonl,
)

UTC = dt.timezone.utc
MAX_CANDLE_SPAN_S = 5000 * CANDLE_PERIOD_MINUTES * 60
LIVE_TIER_BACKFILL_S = 45 * 86400
FINE_WINDOW_S = 6 * 3600


class ExclusionCounter(collections.Counter):
    def add(self, reason: str, n: int = 1) -> None:
        self[reason] += n


def _build_row(m: dict, series: dict[str, dict], tier: str, excl: ExclusionCounter):
    st = series.get(m["series_ticker"])
    if st is None:
        excl.add("series_not_in_series_index")
        cat, kcat, fee_mult = "Other", None, 1.0
    else:
        cat, kcat, fee_mult = st["category"], st["kalshi_category"], st.get("fee_multiplier", 1.0)
    open_ts, close_ts = parse_ts(m.get("open_time")), parse_ts(m.get("close_time"))
    settle_ts = parse_ts(m.get("settlement_ts"))
    if close_ts is None:
        excl.add("missing_close_time")
        return None
    if settle_ts is None:
        settle_ts = close_ts
        excl.add("missing_settlement_ts_anchored_to_close")
    if open_ts is None:
        excl.add("missing_open_time")
        return None
    row = dict(m)
    row.update(
        category=cat, kalshi_category=kcat,
        fee_multiplier=(fee_mult if fee_mult is not None else 1.0),
        open_ts=open_ts, close_ts=close_ts, settlement_ts_epoch=settle_ts, tier=tier,
    )
    return row


def _stream_census(client, cutoff_ts, now_ts, archive_pages, live_pages, log, label):
    n = 0
    log(f"  {label}: archive tier (/historical/markets?mve_filter=exclude) ...")
    for m in census_archive_tier(client, max_pages=archive_pages):
        n += 1
        yield m, "archive"
        if n % 250_000 == 0:
            log(f"    archive: {n:,} scanned")
    log(f"    archive done: {n:,} scanned")
    n2 = 0
    live_from = cutoff_ts - LIVE_TIER_BACKFILL_S
    log(f"  {label}: live tier (/markets?status=settled&mve_filter=exclude) "
        f"from {iso(live_from)} (cutoff minus {LIVE_TIER_BACKFILL_S // 86400}d overlap) ...")
    for m in census_live_tier(client, live_from, now_ts, max_pages=live_pages):
        n2 += 1
        yield m, "live"
        if n2 % 250_000 == 0:
            log(f"    live: {n2:,} scanned")
    log(f"    live done: {n2:,} scanned")


def run_census(
    client: KalshiClient,
    series: dict[str, dict],
    cutoff_ts: int,
    now_ts: int,
    archive_pages: int | None = None,
    live_pages: int | None = None,
    log: Callable[[str], None] = print,
) -> tuple[dict, ExclusionCounter, dict]:
    seen: set[str] = set()
    excl = ExclusionCounter()
    t0 = time.time()

    kept = 0
    by_cat: collections.Counter = collections.Counter()
    by_cat_def: collections.Counter = collections.Counter()
    by_result: collections.Counter = collections.Counter()
    by_tier: collections.Counter = collections.Counter()
    ev_cat: dict[str, str] = {}
    ev_size: collections.Counter = collections.Counter()
    kalshi_cats: set[str] = set()
    close_min: int | None = None
    close_max: int | None = None
    settle_min: int | None = None
    settle_max: int | None = None
    n_yes = 0
    n_def = 0

    for m, tier in _stream_census(client, cutoff_ts, now_ts, archive_pages, live_pages,
                                  log, "census pass 1/2"):
        tk = m.get("ticker")
        if not tk or tk in seen:
            excl.add("duplicate_across_tiers")
            continue
        seen.add(tk)
        if is_combo(m):
            excl.add("mve_combo_market")
            continue
        m = _slim(m, series)
        row = _build_row(m, series, tier, excl)
        if row is None:
            continue
        kept += 1
        cat = row["category"]
        by_cat[cat] += 1
        by_result[str(m.get("result"))] += 1
        by_tier[tier] += 1
        if row["kalshi_category"]:
            kalshi_cats.add(row["kalshi_category"])
        ev = m.get("event_ticker") or ""
        ev_cat.setdefault(ev, cat)
        ev_size[ev] += 1
        if m.get("result") in DEFINITIVE_RESULTS:
            n_def += 1
            by_cat_def[cat] += 1
            if m.get("result") == "yes":
                n_yes += 1
        c = row["close_ts"]
        close_min = c if close_min is None or c < close_min else close_min
        close_max = c if close_max is None or c > close_max else close_max
        st_ = row["settlement_ts_epoch"]
        settle_min = st_ if settle_min is None or st_ < settle_min else settle_min
        settle_max = st_ if settle_max is None or st_ > settle_max else settle_max
        if kept % 250_000 == 0:
            log(f"    kept {kept:,}, {len(ev_cat):,} events, {time.time()-t0:.0f}s")

    stats = {
        "markets_in_census": kept,
        "markets_with_definitive_outcome": n_def,
        "count_per_prereg_category": dict(by_cat),
        "count_per_prereg_category_definitive": dict(by_cat_def),
        "result_distribution": dict(by_result),
        "excluded_non_definitive_by_result": {
            k: v for k, v in by_result.items() if k not in DEFINITIVE_RESULTS
        },
        "rows_by_endpoint_tier": dict(by_tier),
        "exclusions_by_reason": dict(excl),
        "realised_close_time_range": [iso(close_min), iso(close_max)] if close_min else None,
        "realised_settlement_date_range": (
            [iso(settle_min), iso(settle_max)] if settle_min else None
        ),
        "distinct_kalshi_categories_seen": sorted(kalshi_cats),
        "kalshi_categories_not_in_frozen_map": check_mapping_covers(kalshi_cats),
        "pooled_yes_rate_definitive": round(n_yes / n_def, 6) if n_def else None,
        "distinct_events": len(ev_cat),
        "seconds": round(time.time() - t0, 1),
    }
    return stats, excl, {"event_category": ev_cat, "event_size": dict(ev_size)}


def probe_combo_share(
    client: KalshiClient, pages_per_tier: int = 15, log: Callable[[str], None] = print
) -> dict:
    out = {}
    for tier, path in (("archive", "/historical/markets"),
                       ("live", "/markets?status=settled")):
        total = combos = 0
        pages = 0
        for page in client.paginate(path, "markets", limit=1000, max_pages=pages_per_tier):
            pages += 1
            for m in page:
                total += 1
                if is_combo(m):
                    combos += 1
        out[tier] = {
            "pages_sampled": pages,
            "markets_sampled": total,
            "mve_combo_markets": combos,
            "non_combo_markets": total - combos,
            "combo_share": round(combos / total, 6) if total else None,
        }
        log(f"    combo probe [{tier}]: {combos:,}/{total:,} markets are MVE combos "
            f"({100 * combos / total:.2f}%)" if total else f"    combo probe [{tier}]: none")
    return out


def collect_sampled_markets(
    client: KalshiClient,
    series: dict[str, dict],
    cutoff_ts: int,
    now_ts: int,
    chosen_events: set[str],
    archive_pages: int | None = None,
    live_pages: int | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    excl = ExclusionCounter()
    seen: set[str] = set()
    out: list[dict] = []
    for m, tier in _stream_census(client, cutoff_ts, now_ts, archive_pages, live_pages,
                                  log, "census pass 2/2"):
        tk = m.get("ticker")
        if not tk or tk in seen or is_combo(m):
            continue
        seen.add(tk)
        if (m.get("event_ticker") or "") not in chosen_events:
            continue
        row = _build_row(_slim(m, series), series, tier, excl)
        if row is not None:
            out.append(row)
    return out


def census_report(markets: Sequence[dict], excl: ExclusionCounter) -> dict:
    by_cat = collections.Counter(m["category"] for m in markets)
    by_result = collections.Counter(str(m.get("result")) for m in markets)
    definitive = [m for m in markets if m.get("result") in DEFINITIVE_RESULTS]
    non_def = collections.Counter(
        str(m.get("result")) for m in markets if m.get("result") not in DEFINITIVE_RESULTS
    )
    closes = [m["close_ts"] for m in markets if m.get("close_ts")]
    tiers = collections.Counter(m["tier"] for m in markets)
    kalshi_cats = {m.get("kalshi_category") for m in markets if m.get("kalshi_category")}
    return {
        "markets_in_census": len(markets),
        "markets_with_definitive_outcome": len(definitive),
        "excluded_non_definitive_by_result": dict(non_def),
        "exclusions_by_reason": dict(excl),
        "count_per_prereg_category": dict(by_cat),
        "count_per_prereg_category_definitive": dict(
            collections.Counter(m["category"] for m in definitive)
        ),
        "result_distribution": dict(by_result),
        "rows_by_endpoint_tier": dict(tiers),
        "realised_close_time_range": [iso(min(closes)), iso(max(closes))] if closes else None,
        "distinct_kalshi_categories_seen": sorted(kalshi_cats),
        "kalshi_categories_not_in_frozen_map": check_mapping_covers(kalshi_cats),
        "pooled_yes_rate_definitive": (
            round(sum(1 for m in definitive if m["result"] == "yes") / len(definitive), 6)
            if definitive else None
        ),
    }


def draw_event_sample_from_index(
    event_index: dict,
    per_category: int,
    seed: int = SAMPLE_SEED,
    max_markets_per_category: int | None = None,
) -> tuple[set[str], dict]:
    ev_cat = event_index["event_category"]
    ev_size = collections.Counter(event_index["event_size"])
    return _draw(ev_cat, ev_size, per_category, seed, max_markets_per_category)


def draw_event_sample(
    markets: Sequence[dict],
    per_category: int,
    seed: int = SAMPLE_SEED,
    max_markets_per_category: int | None = None,
) -> tuple[set[str], dict]:
    ev_cat: dict[str, str] = {}
    ev_size: collections.Counter = collections.Counter()
    for m in markets:
        ev_cat.setdefault(m["event_ticker"], m["category"])
        ev_size[m["event_ticker"]] += 1
    return _draw(ev_cat, ev_size, per_category, seed, max_markets_per_category)


def _draw(ev_cat, ev_size, per_category, seed, max_markets_per_category):
    by_cat: dict[str, list[str]] = collections.defaultdict(list)
    for ev, cat in ev_cat.items():
        by_cat[cat].append(ev)

    chosen: set[str] = set()
    truncated: dict[str, str] = {}
    drawn_markets: dict[str, int] = {}
    for cat, evs in by_cat.items():
        ordered = sorted(evs, key=lambda e: (event_sample_score(e, seed), e))
        taken, mk = [], 0
        for ev in ordered:
            if len(taken) >= per_category:
                truncated[cat] = "event count reached"
                break
            if max_markets_per_category is not None and mk + ev_size[ev] > max_markets_per_category:
                if taken:
                    truncated[cat] = "market budget reached"
                    break
            taken.append(ev)
            mk += ev_size[ev]
        chosen |= set(taken)
        drawn_markets[cat] = mk

    return chosen, {
        "seed": seed,
        "target_per_category": per_category,
        "max_markets_per_category": max_markets_per_category,
        "events_available_per_category": {k: len(v) for k, v in sorted(by_cat.items())},
        "events_drawn": len(chosen),
        "events_drawn_per_category": dict(collections.Counter(ev_cat[e] for e in chosen)),
        "markets_drawn_per_category": drawn_markets,
        "draw_truncated_because": truncated,
        "total_events_in_census": len(ev_cat),
        "markets_per_event_in_census": {
            "mean": round(sum(ev_size.values()) / len(ev_size), 3) if ev_size else 0,
            "max": max(ev_size.values()) if ev_size else 0,
        },
    }


def build_snapshots(
    client: KalshiClient,
    markets: Sequence[dict],
    cutoff_ts: int,
    log: Callable[[str], None] = print,
    log_every: int = 2000,
) -> tuple[list[Snapshot], ExclusionCounter, dict]:
    reasons = ExclusionCounter()
    snaps: list[Snapshot] = []
    no_candles = 0
    truncated_window = 0
    fine_misses = 0
    t0 = time.time()

    for i, m in enumerate(markets, 1):
        if m.get("result") not in DEFINITIVE_RESULTS:
            reasons.add("market:non_definitive_outcome")
            continue
        close_ts, open_ts = m["close_ts"], m["open_ts"]
        start = max(open_ts, close_ts - MAX_CANDLE_SPAN_S)
        if start > open_ts:
            truncated_window += 1
        if close_ts <= start:
            reasons.add("market:degenerate_time_window")
            continue
        candles = fetch_candles(client, m, start, close_ts, CANDLE_PERIOD_MINUTES, cutoff_ts)
        if not candles:
            no_candles += 1
            reasons.add("market:no_candlesticks_returned")
            continue

        fine: list = []
        t1h = close_ts - HORIZONS["T-1h"]
        if t1h > open_ts:
            fine_start = max(open_ts, t1h - FINE_WINDOW_S)
            if t1h > fine_start:
                fine = fetch_candles(client, m, fine_start, t1h, 1, cutoff_ts)
                if not fine:
                    fine_misses += 1

        s, _ = snapshots_for_market(
            m, candles, m["category"], float(m.get("fee_multiplier") or 1.0), reasons,
            fine_candles=fine,
        )
        snaps.extend(s)
        if log_every and i % log_every == 0:
            rate = i / max(time.time() - t0, 1e-9)
            log(f"    prices: {i:,}/{len(markets):,} markets, {len(snaps):,} snapshots, "
                f"{rate:.1f} mkt/s, {time.time()-t0:.0f}s elapsed")
    return snaps, reasons, {
        "markets_attempted": len(markets),
        "markets_with_no_candlesticks": no_candles,
        "markets_with_truncated_candle_window": truncated_window,
        "markets_with_no_fine_grained_candles_for_T-1h": fine_misses,
        "snapshots_produced": len(snaps),
        "snapshots_per_horizon": dict(collections.Counter(s.horizon for s in snaps)),
        "seconds": round(time.time() - t0, 1),
    }


def derived(name: str) -> str:
    os.makedirs(DERIVED_DIR, exist_ok=True)
    return os.path.join(DERIVED_DIR, name)


def save_json(name: str, obj: Any) -> str:
    p = derived(name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    return p


def load_json(name: str) -> Any:
    p = derived(name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)
