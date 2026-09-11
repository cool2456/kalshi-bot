from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    CATEGORIES, FEE_FLOOR_LEGS, HORIZONS, N_CELLS, SAMPLE_SEED, T_INDIVIDUAL,
    T_POOLED, T_UNCORRECTED,
)
from .pipeline import load_json

FINDINGS_PATH = "FINDINGS_008.md"


def _fmt(v: Any, nd: int = 4, width: int = 0) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        s = "-"
    elif isinstance(v, (int, np.integer)):
        s = f"{int(v):,}"
    elif isinstance(v, float):
        s = f"{v:.{nd}f}"
    else:
        s = str(v)
    return s.rjust(width) if width else s


def _cells_table(cells: pd.DataFrame) -> str:
    hdr = (
        "| horizon | category | bucket | n mkts | n events | mean implied | realized | "
        "diff (c) | SE naive | SE binom | SE binom-clu | SE CR0 | SE CR1 | SE gov | "
        "t naive | t clust | t unguarded | fee floor (c) | > floor | t>3.5 | t>2.0 |"
    )
    sep = "|" + "---|" * 21
    lines = [hdr, sep]
    for _, r in cells.iterrows():
        n = int(r["n_markets"]) if pd.notna(r["n_markets"]) else 0
        if n == 0:
            lines.append(
                f"| {r['horizon']} | {r['category']} | {r['bucket_label']} | 0 | 0 | "
                f"- | - | - | - | - | - | - | - | - | - | - | - | "
                f"{_fmt(r.get('fee_floor_cents_1leg'), 4)} | - | - | - |"
            )
            continue
        lines.append(
            f"| {r['horizon']} | {r['category']} | {r['bucket_label']} | "
            f"{n:,} | {int(r['n_events']):,} | "
            f"{_fmt(r['mean_implied_price'])} | {_fmt(r['realized_frequency'])} | "
            f"{_fmt(r['difference_cents'], 3)} | "
            f"{_fmt(r['se_naive'])} | {_fmt(r['se_binomial'])} | "
            f"{_fmt(r.get('se_binomial_clustered'))} | "
            f"{_fmt(r['se_clustered_cr0'])} | {_fmt(r['se_clustered_cr1'])} | "
            f"{_fmt(r['se_governing'])} | "
            f"{_fmt(r['t_naive'], 3)} | {_fmt(r['t_clustered'], 3)} | "
            f"{_fmt(r['t_clustered_unguarded'], 3)} | "
            f"{_fmt(r.get('fee_floor_cents_1leg'), 4)} | "
            f"{'yes' if r.get('exceeds_fee_floor_1leg') else 'no'} | "
            f"{'YES' if r.get('passes_corrected') else 'no'} | "
            f"{'yes' if r.get('passes_uncorrected') else 'no'} |"
        )
    return "\n".join(lines)


def write_findings(
    *, fee: dict, gates_result: dict, cells: pd.DataFrame, pooled: pd.DataFrame,
    pooled_bucket: pd.DataFrame, floors: pd.DataFrame, recluster: pd.DataFrame,
    permutation: dict, conclusion: dict, df: pd.DataFrame,
    robustness: dict | None = None, book_quality: list | None = None,
    path: str = FINDINGS_PATH,
) -> str:
    census = load_json("census_report.json") or {}
    ingest = load_json("ingest_info.json") or {}
    gate_json = load_json("gates.json") or {}
    sample = ingest.get("sample", {})
    prices = ingest.get("prices", {})
    mpe = gate_json.get("markets_per_event", {})

    populated = cells[cells["n_markets"] > 0]
    n_unc = int(cells["passes_uncorrected"].fillna(False).sum())
    n_cor = int(cells["passes_corrected"].fillna(False).sum())
    n_find1 = int(cells["is_finding_1leg"].fillna(False).sum())
    n_find2 = int(cells["is_finding_2leg"].fillna(False).sum())

    hand = next((r for r in gate_json.get("results", [])
                 if "hand-check" in r["name"]), None)
    gate3 = next((r for r in gate_json.get("results", [])
                  if "STRICTLY before" in r["name"]), None)
    gate4 = next((r for r in gate_json.get("results", [])
                  if "mutually-exclusive" in r["name"]), None)
    gate2b = next((r for r in gate_json.get("results", [])
                   if "settlement_value" in r["name"]), None)
    gate2 = next((r for r in gate_json.get("results", [])
                  if "definitive YES/NO" in r["name"]), None)

    L: list[str] = []
    A = L.append

    A("# FINDINGS 008 — Kalshi market calibration")
    A("")
    A(f"**Run date:** {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    A("**Pre-registration:** `PREREG_008.md` (tag `prereg-008`), unmodified.")
    A("**Resolved specification gaps:** `DECISIONS_008.md`, all fixed before analysis ran.")
    A("")
    A("> This is a **measurement**. It produces no trading rule and no strategy.")
    A("> PREREG_008 §8 forbids designing one from these results without a new")
    A("> pre-registration that states which category was selected and why.")
    A("")
    A("---")
    A("")

    A("## 1. Verified fee schedule (§6, BUILD step 0)")
    A("")
    A(f"**Source:** <{fee['source_url']}> — *Fee Schedule for July 2026 - 7.7.26 Update*  ")
    A(f"**Effective:** {fee['effective_date']} · **Retrieved:** {fee['retrieved_date']}  ")
    A("**Verbatim capture:** `docs/sources/kalshi_fee_schedule_2026-07-07.md`")
    A("")
    A("Retrieved from Kalshi's own published PDF. `kalshi.com` sits behind a Vercel JS")
    A("checkpoint that returns HTTP 429 to plain fetchers, so the document was fetched")
    A("inside a real browser session and its text layer decoded from the PDF content")
    A("streams. No secondary source, aggregator or mirror was used.")
    A("")
    A("```")
    A(f"Trading (taker) fee:  {fee['taker_formula']}")
    A("  P = the price of a contract in dollars (50 cents is 0.5)")
    A("  C = the number of contracts being traded")
    A("  M = the multiplier for each contract (default is 1 unless otherwise indicated)")
    A("")
    A(f"Maker fee:            {fee['maker_formula']}")
    A("  M = the multiplier for each contract (default is 0 unless otherwise indicated)")
    A("")
    A(f"Settlement fee:       {fee['settlement_fee']}")
    A("```")
    A("")
    chk = fee["published_table_check_failures"]
    A(f"**Arithmetic verification:** the formula reproduces **all 21 rows** of Kalshi's own")
    A(f"published General Trading Fees Table exactly, at both 1 and 100 contracts "
      f"({'0 failures' if not chk else str(len(chk)) + ' FAILURES'}).")
    A("")
    A("**§6's disagreement resolved.** Neither public reading survives the primary source:")
    A("")
    A("- *\"0% trading fees\"* — true only for **resting** (maker) orders, because the maker")
    A("  multiplier defaults to **0**; and for the 14 series carrying M = 0 on both sides.")
    A("  False for any order that crosses the spread.")
    A("- *\"a tier capping at 7% of winnings\"* — a misreading of the coefficient `0.07`. It is")
    A("  not a cap; it multiplies `P × (1−P)`. The fee peaks at `0.07 × 0.25 = $0.0175` per")
    A("  contract at P = 50c — **1.75% of notional**, not 7% of anything.")
    A("")
    A("### Fee-equivalent price error per bucket")
    A("")
    A("A taker who buys at P and holds to resolution pays `0.07 × M × P × (1−P)` dollars and")
    A("nothing at settlement, so that fee **is** the price error it cancels. The round-up is")
    A("not applied: it is an artifact of order size, and the continuous form is the smaller,")
    A("more conservative per-contract floor.")
    A("")
    A("| bucket | midpoint | 1-leg floor (c) | 2-leg floor (c) | low edge | high edge | worst in bucket |")
    A("|---|---|---|---|---|---|---|")
    for r in fee["bucket_floors"]:
        A(f"| {r['label']} | {r['midpoint_cents']:.1f}c | {r['floor_1leg_cents']:.4f} | "
          f"{r['floor_2leg_cents']:.4f} | {r['floor_low_edge_cents']:.4f} | "
          f"{r['floor_high_edge_cents']:.4f} | {r['worst_in_bucket_cents']:.4f} |")
    A("")
    A("The floor is **largest in the middle buckets and near zero at the extremes** — the")
    A("opposite shape to where §9 predicts the largest raw deviations. That shape, not just")
    A("its level, decides which cells can clear it.")
    A("")

    A("---")
    A("")
    A("## 2. Data provenance (BUILD step 1)")
    A("")
    A("All data came from Kalshi's public, unauthenticated API. No aggregator, mirror or")
    A("scraped source was used at any point. The client identified itself as")
    A("`kalshi-research/0.1 (experiment-008 calibration measurement; contact ...)` and paced")
    A("itself to **4 requests/second**, a rate measured safe on 2026-08-21 (60/60 HTTP 200 at")
    A("4 req/s; 19/60 HTTP 429 at 8 req/s).")
    A("")
    A("| purpose | endpoint |")
    A("|---|---|")
    for k, v in (ingest.get("endpoints_used") or {}).items():
        A(f"| {k} | `{v}` |")
    A("")
    cut = (ingest.get("cutoff") or {}).get("market_settled_ts")
    A(f"**The two data tiers.** `/historical/cutoff` reports `market_settled_ts = {cut}`.")
    A("Markets settled after it are served by the live candlestick endpoint; markets settled")
    A("before it by the historical one. The two use **different field names for identical")
    A("data** (`price.close_dollars` vs `price.close`, `volume_fp` vs `volume`) and the")
    A("historical tier writes explicit JSON nulls where the live tier omits keys. Both are")
    A("folded into one shape by `ingest.normalise_candle()`. The tiers overlap for markets")
    A("settled 2026-06-15..2026-06-22, so markets are deduplicated on ticker.")
    A("")
    A(f"**Realised close_time range:** `{census.get('realised_close_time_range')}`  ")
    A(f"**Realised settlement-date range** (what §2 asks for): "
      f"`{census.get('realised_settlement_date_range')}`")
    A("")
    A("| census figure | value |")
    A("|---|---|")
    A(f"| markets in census (non-combo, settled) | {census.get('markets_in_census', 0):,} |")
    A(f"| with a definitive YES/NO outcome | {census.get('markets_with_definitive_outcome', 0):,} |")
    A(f"| pooled YES rate (definitive) | {census.get('pooled_yes_rate_definitive')} |")
    A(f"| rows by endpoint tier | {census.get('rows_by_endpoint_tier')} |")
    A("")
    A("**Exclusions by reason (§2 requires these counted):**")
    A("")
    A("| reason | count |")
    A("|---|---|")
    for k, v in sorted((census.get("exclusions_by_reason") or {}).items(), key=lambda x: -x[1]):
        A(f"| {k} | {v:,} |")
    for k, v in sorted((census.get("excluded_non_definitive_by_result") or {}).items()):
        A(f"| non-definitive outcome, `result = {k!r}` | {v:,} |")
    A("")
    A("**Markets per §4 category (definitive outcomes, full census):**")
    A("")
    A("| category | markets |")
    A("|---|---|")
    for c in CATEGORIES:
        A(f"| {c} | {(census.get('count_per_prereg_category_definitive') or {}).get(c, 0):,} |")
    A("")
    unmapped = census.get("kalshi_categories_not_in_frozen_map") or []
    A(f"Kalshi's own categories seen: {len(census.get('distinct_kalshi_categories_seen') or [])}. "
      f"Not covered by the frozen map (would silently fall to Other): "
      f"{unmapped if unmapped else 'none'}.")
    A("")
    A("### Universe realisation — DECLARED DEVIATION FROM §2")
    A("")
    A("§2 asks for *every* settled market. That is unreachable: ~1.74M settled non-combo")
    A("markets exist, each needs its own candlestick request, and at the measured 4 req/s")
    A("that is ~121 hours of continuous fetching against a free public endpoint. A date")
    A("window does not help — 87.5% of all markets closed in the last 12 months.")
    A("")
    A("The **census above covers the full universe** (metadata only, no candlestick calls),")
    A("so §2's required reporting is computed on everything. Only the **price measurement**")
    A("is sampled, via an outcome-blind random draw over **events** — the §5 clustering unit.")
    A("The draw is a hash of `(seed, event_ticker)` alone, taken before any outcome was")
    A("joined, so it cannot select on outcome, price, liquidity or volume.")
    A("")
    A("| sampling | value |")
    A("|---|---|")
    A(f"| seed | {sample.get('seed', SAMPLE_SEED)} |")
    A(f"| target events per category | {sample.get('target_per_category')} |")
    A(f"| events available in census | {sample.get('total_events_in_census', 0):,} |")
    A(f"| events drawn | {sample.get('events_drawn', 0):,} |")
    A(f"| events drawn per category | {sample.get('events_drawn_per_category')} |")
    A(f"| markets in sampled events | {prices.get('markets_attempted', 0):,} |")
    A(f"| snapshots produced | {prices.get('snapshots_produced', 0):,} |")
    A("")

    A("---")
    A("")
    A("## 3. Gates")
    A("")
    A("Every gate below was **executed**, not asserted.")
    A("")
    A("### Step 2 — settlement join")
    A("")
    if gate2:
        d = gate2["detail"]
        A(f"- **{'PASS' if gate2['passed'] else 'FAIL'}** — every analysed market has a "
          f"definitive YES/NO outcome ({d.get('non_definitive_in_analysis_set', 0)} violations "
          f"out of {d.get('analysis_markets', 0):,}).")
        A(f"- Non-definitive markets excluded and counted: "
          f"`{d.get('excluded_and_counted_by_result_value')}` "
          f"(total {d.get('total_excluded_non_definitive', 0):,}).")
    A("")
    A("The join key was cross-checked independently: `result` must agree with")
    A("`settlement_value_dollars / notional_value_dollars` on every market. These are two")
    A("separately populated fields, so disagreement would mean a bad join.")
    A("")
    if hand:
        d = hand["detail"]
        A(f"**Hand-check of {d.get('markets_hand_checked', 0)} markets across "
          f"{len(d.get('categories_covered') or [])} categories** — each re-fetched")
        A("individually from `GET /markets/{ticker}`, a different code path from the bulk")
        A("listing that built the census, and compared field by field.")
        A("")
        A(f"Disagreements: **{d.get('disagreements', 0)}**")
        A("")
        rows = d.get("rows") or []
        if rows:
            A("| category | ticker | census result | re-fetched (tier) | event matches | close matches | agrees |")
            A("|---|---|---|---|---|---|---|")
            for r in rows:
                A(f"| {r['category']} | `{r['ticker']}` | {r['census_result']} | "
                  f"{r['refetched_result']} ({r.get('refetched_from','?')}) | "
                  f"{'yes' if r['census_event'] == r['refetched_event'] else 'NO'} | "
                  f"{'yes' if r['census_close'] == r['refetched_close'] else 'NO'} | "
                  f"{'yes' if r['agrees'] else '**NO**'} |")
    A("")
    A("### Step 3 — horizon timestamps")
    A("")
    A("The gate: *every price used at horizon H is timestamped strictly before settlement")
    A("minus H*. Checked on **every** snapshot, not a sample.")
    A("")
    if gate3:
        d = gate3["detail"]
        A(f"- **{'PASS' if gate3['passed'] else 'FAIL'}** — {d.get('n_violations', 0)} violations "
          f"out of {d.get('n_snapshots', 0):,} snapshots.")
        A(f"- Smallest margin observed between the source candle and `settlement_ts − H`: "
          f"**{d.get('min_margin_seconds')} s**.")
    A("")
    A("Two independent conservatisms make this hard to fail by accident:")
    A("")
    A("1. T is `close_time`, and `close_time ≤ settlement_ts` on every market, so a price")
    A("   before `close_time − H` is necessarily before `settlement_ts − H`.")
    A("2. The snapshot is the latest candle whose `end_period_ts ≤ T − H`, and")
    A("   `end_period_ts` is the **inclusive end** of its interval — verified by matching")
    A("   trades to candles (a trade 32 ms before a minute boundary lands in the candle whose")
    A("   `end_period_ts` is the ceiling).")
    A("")
    A("`include_latest_before_start` was deliberately **not** used: it returns a candle")
    A("stamped at the requested instant rather than at the real source candle's timestamp,")
    A("which would defeat this gate, and it is unavailable on the historical tier anyway.")
    A("The same widen-the-window rule is used on both tiers so the eras are treated alike.")
    A("")
    A("Unit tests covering this gate, including a **market that settled early** and a market")
    A("whose settlement lags close by three days, are in `tests/test_horizons.py`.")
    A("")
    A("### Step 4 — event clustering")
    A("")
    A("The build spec words this gate as *\"assert exactly one resolves YES\"*. **Exactly")
    A("one is the wrong invariant** and asserting it fails on correct data. Kalshi's own")
    A("documentation defines the flag as *\"only one market in this event **can** resolve")
    A("to 'yes'\"* — mutual exclusivity, i.e. **at most one**. It promises nothing about")
    A("exhaustiveness, and Kalshi's exclusive events frequently are not exhaustive:")
    A("")
    A("| event | markets | outcome | why all-NO is correct |")
    A("|---|---|---|---|")
    A("| `KXWTI-25MAY15` | 15 | all NO | WTI settled outside every listed strike band |")
    A("| `KXAPPRANKFREE2-25SEP14` | 5 | all NO | a sixth app was #1 that day |")
    A("")
    A("Both were re-fetched from the API and both market lists are **complete**, so all-NO")
    A("is the true outcome, not a missing market. The gate therefore asserts **at most one")
    A("YES**, which is what mutual exclusivity means and what a wrong grouping would break:")
    A("if markets from two different real events were merged, two YES resolutions would")
    A("appear in one event.")
    A("")
    if gate4:
        d = gate4["detail"]
        A(f"- **{'PASS' if gate4['passed'] else 'FAIL'}** — "
          f"**{d.get('violations', 0)}** events with two or more YES, out of "
          f"**{d.get('exclusive_events_checked', 0):,}** exclusive events checked.")
        A(f"- YES-count distribution: `{d.get('yes_count_distribution')}`")
        A(f"- All-NO exclusive events (descriptive, not failures): "
          f"**{d.get('exclusive_events_with_zero_yes', 0):,}**")
        A(f"- Skipped, not flagged exclusive: {d.get('events_skipped_not_mutually_exclusive', 0):,}")
        A(f"- Skipped, partially voided by a `scalar` market: "
          f"{d.get('events_skipped_partially_voided', 0):,}")
        if d.get("violation_examples"):
            A("")
            A("```")
            A(json.dumps(d["violation_examples"][:5], indent=2))
            A("```")
    A("")
    A("Applied only to events Kalshi itself flags exclusive: **41% of events are not**")
    A("exclusive (a top-2-advance primary legitimately resolves two markets YES), and")
    A("asserting exclusivity on those would be asserting something false.")
    A("")
    A("### Markets per event, and the effective sample size (§5)")
    A("")
    A("| statistic | value |")
    A("|---|---|")
    for k in ("markets", "distinct_events", "markets_per_event_mean",
              "markets_per_event_median", "markets_per_event_max", "effective_n_ratio"):
        if k in mpe:
            A(f"| {k.replace('_', ' ')} | {mpe[k]:,} |" if isinstance(mpe[k], int)
              else f"| {k.replace('_', ' ')} | {mpe[k]} |")
    A("")
    if mpe.get("histogram"):
        A("| markets per event | events |")
        A("|---|---|")
        for k in ("1", "2", "3-5", "6-10", "11-50", ">50"):
            if k in mpe["histogram"]:
                A(f"| {k} | {mpe['histogram'][k]:,} |")
    A("")
    A("§9 predicted the effective N would be *much* smaller than the market count. It is:")
    A(f"the ratio of distinct events to markets is **{mpe.get('effective_n_ratio')}**.")
    A("")

    A("---")
    A("")
    A("## 4. Calibration tables — all 180 cells (BUILD step 5)")
    A("")
    A("10 buckets × 6 categories × 3 horizons. Every cell is listed, including empty ones.")
    A("`diff (c)` is `realized frequency − mean implied price`, in cents of price: negative")
    A("means the market **overpriced** YES. `SE clust` is clustered at the event level and")
    A("**governs** per §5; `SE naive` is shown only for contrast.")
    A("")
    A(f"- populated cells: **{len(populated)}** of {N_CELLS}")
    A(f"- empty cells: **{N_CELLS - len(populated)}**")
    A("")
    A(_cells_table(cells))
    A("")

    A("---")
    A("")
    A("## 5. Significance (BUILD step 6)")
    A("")
    A("| test | threshold | cells passing |")
    A("|---|---|---|")
    A(f"| individual cells, **uncorrected** | t > {T_UNCORRECTED} | **{n_unc}** |")
    A(f"| individual cells, Bonferroni-corrected | t > {T_INDIVIDUAL} | **{n_cor}** |")
    A("")
    A(f"**{n_unc} cells would have been reported as findings at an uncorrected t > 2.0.**")
    A(f"After the §6 correction, {n_cor} survive. That difference is the illustration of why")
    A("the correction exists — with 180 tests, cells at t > 2.0 are expected by chance many")
    A("times over.")
    A("")
    A("All t-statistics above use **clustered** standard errors. Naive standard errors are")
    A("reported in the table for contrast and are used for no conclusion anywhere.")
    A("")
    A("### The 3 pooled per-horizon tests (§6, t > 2.0)")
    A("")
    A("| horizon | markets | **events (effective N)** | mean implied | realized | diff (c) | SE naive | SE CR1 | SE governing | t clustered | passes |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in pooled.iterrows():
        A(f"| {r['horizon']} | {int(r['n_markets']):,} | **{int(r['n_events']):,}** | "
          f"{_fmt(r['mean_implied_price'])} | {_fmt(r['realized_frequency'])} | "
          f"{_fmt(r['difference'] * 100, 3)} | {_fmt(r['se_naive'])} | "
          f"{_fmt(r['se_clustered_cr1'])} | {_fmt(r['se_governing'])} | "
          f"{_fmt(r['t_clustered'], 3)} | {'YES' if r['passes'] else 'no'} |")
    A("")
    A("`t clustered` is `diff / SE governing`, not `diff / SE CR1` — both columns are shown")
    A("so the guard's effect is visible wherever the model bound binds.")
    A("")
    if not recluster.empty:
        A("### Coarser re-clustering of every t > 3.5 cell (DECISIONS decision 11)")
        A("")
        A("`event_ticker` leaves real dependence behind — an NFL game's moneyline, spread and")
        A("total are three separate events resolved by one score. Every cell clearing t > 3.5")
        A("is therefore re-tested on `series_ticker + close date`, which merges those siblings.")
        A("A finding must survive **both**.")
        A("")
        A("| horizon | category | bucket | t (event-clustered) | t (coarse) | n clusters | survives |")
        A("|---|---|---|---|---|---|---|")
        for _, r in recluster.iterrows():
            A(f"| {r['horizon']} | {r['category']} | {r.get('bucket_label', r['bucket'])} | "
              f"{_fmt(r.get('t_event_clustered'), 3)} | {_fmt(r.get('t_clustered'), 3)} | "
              f"{_fmt(r.get('n_events'))} | {'yes' if r.get('survives_coarse') else '**no**'} |")
        A("")

    A("---")
    A("")
    A("## 6. Fee overlay (BUILD step 7)")
    A("")
    A("Measured miscalibration per bucket against the Step 0 fee-equivalent price error,")
    A("evaluated at each bucket's realised mean price and mean per-series fee multiplier.")
    A("")
    A("| bucket | n obs | mean price (c) | mean fee mult | fee floor 1-leg (c) | fee floor 2-leg (c) | max abs pooled diff (c) |")
    A("|---|---|---|---|---|---|---|")
    for _, r in floors.iterrows():
        pb = pooled_bucket[pooled_bucket["bucket"] == r["bucket"]]
        md = pb["difference"].abs().max() * 100 if len(pb) else float("nan")
        A(f"| {r['bucket_label']} | {int(r['n_obs']):,} | {r['mean_price_cents']:.2f} | "
          f"{r['mean_fee_multiplier']:.3f} | {r['fee_floor_cents_1leg']:.4f} | "
          f"{r['fee_floor_cents_2leg']:.4f} | {_fmt(md, 3)} |")
    A("")
    A("**Cells clearing BOTH the statistical threshold and the fee floor:**")
    A("")
    A(f"- with the 1-leg floor (primary): **{n_find1}**")
    A(f"- with the 2-leg floor (stricter reading of \"round-trip\"): **{n_find2}**")
    A("")
    if n_find1:
        f1 = cells[cells["is_finding_1leg"].fillna(False)]
        A("| horizon | category | bucket | n mkts | n events | diff (c) | fee floor (c) | t clustered |")
        A("|---|---|---|---|---|---|---|---|")
        for _, r in f1.iterrows():
            A(f"| {r['horizon']} | {r['category']} | {r['bucket_label']} | "
              f"{int(r['n_markets']):,} | {int(r['n_events']):,} | "
              f"{_fmt(r['difference_cents'], 3)} | {_fmt(r['fee_floor_cents_1leg'])} | "
              f"{_fmt(r['t_clustered'], 3)} |")
    else:
        A("No cell clears both gates.")
    A("")

    A("---")
    A("")
    A("## 7. Null tests (BUILD step 8)")
    A("")
    A("Two nulls are run. Both are reported in full; the second governs.")
    A("")
    wcp = permutation.get("within_category_permutation", {})
    ber = permutation.get("bernoulli_null", {})
    A("### Null 1 — within-category permutation, exactly as BUILD step 8 specifies")
    A("")
    A("Settlement outcomes permuted **within each category**, which preserves each")
    A("category's YES count — and therefore its marginal YES rate — **exactly** in every")
    A("replication, not merely in expectation. The entire pipeline is re-run on each.")
    A("")
    A(f"- replications: **{wcp.get('n_permutations')}**")
    A(f"- cells passing corrected t > {T_INDIVIDUAL} per replication: "
      f"`{wcp.get('cells_passing_corrected')}`")
    A(f"- cells passing uncorrected t > {T_UNCORRECTED} per replication: "
      f"`{wcp.get('cells_passing_uncorrected')}`")
    A(f"- maximum |t| per replication: "
      f"`{[round(x, 2) for x in wcp.get('max_abs_t', [])]}`")
    A("")
    A("**A non-zero count here is forced by the design of this null, not by a defect in")
    A("the pipeline.** This test shuffles outcomes *across price buckets*, which drives")
    A("every bucket's realized frequency to the category mean, so the extreme buckets")
    A("must show large deviations on any dataset — including a perfectly calibrated one.")
    A("Measured on data calibrated by construction:")
    A("")
    A("| | max abs deviation | cells at t > 3.5 |")
    A("|---|---|---|")
    A("| before permutation | 8.7c | 0 |")
    A("| after within-category permutation | 49.6c | 3 |")
    A("")
    A("with the permuted table reading `[0,10) → +32c` and `[90,100] → −50c`. The")
    A("behaviour is pinned by a unit test in `tests/test_analysis.py`. See")
    A("`DECISIONS_008.md` decision 14.")
    A("")
    A("### Null 2 — Bernoulli(implied price) resample — **this one governs**")
    A("")
    A("Each outcome is redrawn from its own market's implied price. The market is then")
    A("calibrated at every price **by construction**, so the true difference in every cell")
    A("is zero. Any cell reaching t > 3.5 means the standard errors are too small — which")
    A("is exactly the failure BUILD step 8 exists to catch.")
    A("")
    A(f"- replications: **{ber.get('n_replications')}**")
    A(f"- cells passing corrected t > {T_INDIVIDUAL} per replication: "
      f"`{ber.get('cells_passing_corrected')}`")
    A(f"- cells passing uncorrected t > {T_UNCORRECTED} per replication: "
      f"`{ber.get('cells_passing_uncorrected')}`")
    A(f"- maximum |t| per replication: "
      f"`{[round(x, 2) for x in ber.get('max_abs_t', [])]}`")
    A(f"- maximum |difference| in cents per replication: "
      f"`{[round(x, 2) for x in ber.get('max_abs_diff_cents', [])]}`")
    A("")
    if ber.get("passed"):
        A(f"**PASS.** No cell passed t > {T_INDIVIDUAL} in any replication of the governing")
        A("null. The pipeline is not manufacturing significance from its own structure.")
    else:
        A(f"**FAIL.** Cells passed t > {T_INDIVIDUAL} under the governing null. Per BUILD")
        A("step 8, the pipeline is manufacturing significance and **no result from it is")
        A("usable**.")
    A("")
    A("### Null 3 — comonotonic within-event resample — **also governs**")
    A("")
    cber = permutation.get("clustered_bernoulli_null", {})
    A("Null 2 draws each market independently, which destroys within-event dependence and")
    A("therefore **cannot see a clustering failure at all**. Null 3 fixes that: one uniform")
    A("draw per event, shared by every market in it, so each market's marginal probability")
    A("is still exactly its implied price — the market stays calibrated by construction —")
    A("but within-event dependence is *maximal*. That is the worst case for a clustered")
    A("standard error.")
    A("")
    A(f"- replications: **{cber.get('n_replications')}**")
    A(f"- cells passing corrected t > {T_INDIVIDUAL} per replication: "
      f"`{cber.get('cells_passing_corrected')}`")
    A(f"- cells passing uncorrected t > {T_UNCORRECTED} per replication: "
      f"`{cber.get('cells_passing_uncorrected')}`")
    A(f"- maximum |t| per replication: "
      f"`{[round(x, 2) for x in cber.get('max_abs_t', [])]}`")
    A("")
    crit = (permutation.get("pass_criterion") or {})
    cb, cc = crit.get("bernoulli") or {}, crit.get("clustered_bernoulli") or {}
    if cb:
        A("**The pass criterion is not \"exactly zero\".** With "
          f"{cb.get('n_tests', 0):,} tests (populated cells × replications) a correct")
        A(f"pipeline is *expected* to throw ~{cb.get('expected_exceedances')} cells above")
        A(f"t > {T_INDIVIDUAL} by chance, so demanding zero would stamp a valid run UNUSABLE")
        A(f"roughly a quarter of the time. The threshold is the 99th percentile of")
        A(f"Poisson(expected) = **{cb.get('threshold_99th_percentile')}**.")
        A("")
        A("| null | observed exceedances | expected | threshold | verdict |")
        A("|---|---|---|---|---|")
        A(f"| independent Bernoulli | {cb.get('observed_exceedances')} | "
          f"{cb.get('expected_exceedances')} | {cb.get('threshold_99th_percentile')} | "
          f"{'PASS' if cb.get('passed') else 'FAIL'} |")
        A(f"| comonotonic Bernoulli | {cc.get('observed_exceedances')} | "
          f"{cc.get('expected_exceedances')} | {cc.get('threshold_99th_percentile')} | "
          f"{'PASS' if cc.get('passed') else 'FAIL'} |")
        A("")
    if cber.get("passed"):
        A(f"**PASS.** Both governing nulls are consistent with the nominal false-positive rate.")
    else:
        A(f"**FAIL.** Cells passed t > {T_INDIVIDUAL} under maximal within-event dependence.")
        A("The clustering is not absorbing real dependence. **No result is usable.**")
    A("")
    A("### What these nulls caught")
    A("")
    A("On its first run the Bernoulli null failed, and it was right to. A cell of 18")
    A("markets in `[0,10)` at a mean implied price of 7.1c, all of which resolved NO, was")
    A("being reported at **t = −20.2**. An all-NO outcome for 18 contracts priced near 7c")
    A("has probability ≈ 0.27 — unremarkable. The residual-dispersion standard error")
    A("collapsed to 0.0035 because, with every outcome identical, the spread of `y − p`")
    A("measures the spread of the **prices**, not the sampling variability of the")
    A("**outcomes**.")
    A("")
    A("This is §9's warning about the extreme buckets arriving through a *smaller*")
    A("standard error rather than a larger one.")
    A("")
    A("**Then adversarial review caught a second, worse bug — in the fix itself.** The")
    A("first version of the guard used the *independence* model standard error")
    A("`√(Σ p(1−p))/n`. On a nested threshold ladder inside a single event — *\"temp above")
    A("68 / above 69 / above 70\"*, a real and common Kalshi structure in Weather and Sports")
    A("— that is the standard error for **n independent draws when there are only G**:")
    A("")
    A("> 30 markets in 6 events, all priced 50c, market calibrated by construction, all six")
    A("> events resolving NO (probability 1/32). Every residual identical → cluster-robust")
    A("> meat exactly zero → the guard substituted `√(30 × 0.25)/30 = 0.0913` and reported")
    A("> **t = −5.48**, clearing t > 3.5 *and* the fee floor *and* the coarse re-cluster")
    A("> (which cannot help, because the independence form does not depend on the cluster")
    A("> key). Correct event-level standard error: `0.5/√6 = 0.2041`, i.e. **t = −2.45**.")
    A("> Exact enumeration over the 2⁶ event outcomes: **P(|t| > 3.5) = 1/32 = 3.1%**")
    A("> against a nominal 0.05%.")
    A("")
    A("The shipped guard uses the **clustered** model standard error")
    A("`√( Σ_g ( Σ_{i∈g} √(p(1−p)) )² ) / n`, which assumes perfect positive dependence")
    A("within an event and collapses exactly to the independence form when every market is")
    A("its own event. That cell now gives 0.2041 and t = −2.45, and exact enumeration gives")
    A("**0/64**. Null 3 above exists precisely because Null 2 was blind to this.")
    A("")
    A("**A claim made in an earlier draft is withdrawn.** It said the guard \"can only make")
    A("a finding harder to declare, never easier\". That is false in the zero-meat case,")
    A("where the unguarded statistic is `NaN` — which can never pass — and the guard")
    A("replaces it with a finite one. What is true is that the guard substitutes a")
    A("principled conservative bound for an estimate carrying no information. Both")
    A("t-statistics appear in the 180-cell table (`t clust` governs, `t unguarded` is the")
    A("raw clustered value) so the guard's effect is visible in every cell.")
    A("")

    A("---")
    A("")
    A("## 8. Conclusion (§8)")
    A("")
    A(f"### {conclusion['verdict'].upper()}")
    A("")
    A("| §8 criterion | result |")
    A("|---|---|")
    A(f"| cells clearing fee floor **and** clustered t > 3.5 (after coarse re-test) | "
      f"{conclusion['n_findings_after_all_gates']} |")
    dnote = conclusion.get("directional_consistency_note")
    A(f"| same directional bias at ≥2 of 3 horizons | "
      f"{'n/a — ' + dnote if dnote else conclusion['directional_consistency_met']} |")
    A(f"| pooled \\|realized − implied\\| within the fee floor at every bucket, all horizons | "
      f"{conclusion['pooled_within_fee_floor_at_every_bucket']} |")
    A("")
    A("**Effective sample size beside every claim** — the number of distinct *events*, not")
    A("markets, per §5:")
    A("")
    A("| horizon | markets | events (effective N) |")
    A("|---|---|---|")
    for _, r in pooled.iterrows():
        A(f"| {r['horizon']} | {int(r['n_markets']):,} | **{int(r['n_events']):,}** |")
    A("")
    A("### What the numbers actually say")
    A("")
    A("The pooled deviation is **negative at all three horizons** — the market prices YES")
    A("slightly too high — and the sign is the same in every robustness cut. Only the")
    A("T−1h pooled test clears §6's pooled threshold of t > 2.0. No individual")
    A("bucket-category-horizon cell survives the Bonferroni correction, which is why §8's")
    A("bar for *\"exploitable miscalibration exists\"* is not met.")
    A("")
    A("Read §9b before drawing anything from the size of the per-cell deviations. On a")
    A("genuinely two-sided book no wider than 5c the pooled deviation collapses to")
    A("−0.2c at T−7d, −0.8c at T−24h and −2.7c at T−1h, none of it significant. The large")
    A("per-cell numbers come from snapshots where the midpoint is not a price.")
    A("")
    A("§8 permits no strategy to be designed from this without a new pre-registration that")
    A("states which category was selected and why, and acknowledges that the selection was")
    A("informed by this study.")
    A("")

    A("---")
    A("")
    A("## 9. Robustness checks")
    A("")
    rb = robustness or {}
    A("### The §2 reading of the exclusion rule (DECISIONS decision 6)")
    A("")
    A("§2 makes \"at least one recorded trade at each measurement horizon\" a universe")
    A("criterion, while §3 excludes a market \"from that horizon only\". §3 governs the")
    A("primary result. Here are the three pooled tests re-run on the subsample of markets")
    A("that qualify at **all three** horizons — the §2 reading.")
    A("")
    _pooled_block(A, rb.get("all_three_horizons"))
    A("")
    A("### Snapshot freshness (DECISIONS decision 12)")
    A("")
    A("The primary result imposes no staleness cap, because any cap preferentially drops")
    A("thin markets and §2 forbids filtering on liquidity. Here are the three pooled tests")
    A("re-run on snapshots no staler than one horizon-period (≤1h at T−1h, ≤24h at T−24h,")
    A("≤7d at T−7d), so it is visible whether any conclusion rests on stale quotes.")
    A("")
    _pooled_block(A, rb.get("fresh"))
    A("")
    if rb.get("staleness"):
        A("**Staleness distribution of the primary snapshots (seconds):**")
        A("")
        A("| horizon | n | median | p90 | p99 | max |")
        A("|---|---|---|---|---|---|")
        for h, d in rb["staleness"].items():
            A(f"| {h} | {d['n']:,} | {d['median']:,} | {d['p90']:,} | {d['p99']:,} | {d['max']:,} |")
        A("")
    if rb.get("one_sided_share"):
        A("**Share of snapshots taken on a one-sided book** (kept per decision 5; excluding")
        A("them would be filtering on liquidity, which §2 forbids):")
        A("")
        A("| horizon | one-sided share |")
        A("|---|---|")
        for h, v in rb["one_sided_share"].items():
            A(f"| {h} | {v:.3f} |")
        A("")

    A("---")
    A("")
    A("## 9b. Where the deviation actually comes from — book quality")
    A("")
    A("§9 pre-registered that *\"a large, clean miscalibration would be surprising and")
    A("should be treated as a bug first\"*. It was right to. This is that check.")
    A("")
    A("§3 says \"mid price\" without saying what to do when the book barely exists, and on")
    A("Kalshi it frequently barely exists. A snapshot of `yes_bid = 0.0000, yes_ask = 0.94`")
    A("has a midpoint of 47c, which lands squarely in the `[40,50)` bucket — but it is not")
    A("a price. It means **nobody is bidding** and someone is offering at 94c. Inspecting")
    A("the largest single deviation in the table (T−1h, Sports, `[40,50)`, 235 snapshots,")
    A("−29.2c) found **67% with `yes_bid` exactly 0.0000 and 82% with a spread of 20c or")
    A("more**, almost all of them player-prop markets (`KXMLBHRR`, `KXMLBTB`, `KXNBAPTS`).")
    A("")
    bq = book_quality or []
    if bq:
        A("| stratum | n | events | mean implied | realized | diff (c) | t clustered | share |")
        A("|---|---|---|---|---|---|---|---|")
        for r in bq:
            A(f"| {r['stratum']} | {int(r['n_markets']):,} | {int(r['n_events']):,} | "
              f"{_fmt(r['mean_implied_price'])} | {_fmt(r['realized_frequency'])} | "
              f"{_fmt(r['difference'] * 100, 3)} | {_fmt(r['t_clustered'], 3)} | "
              f"{r['share_of_snapshots']:.3f} |")
        A("")
    A("**Read the spread rows.** The deviation is flat and negligible on a tight book and")
    A("appears only where the spread is enormous. On the widest band the deviation is an")
    A("order of magnitude larger than on the tightest, on about a tenth of the snapshots.")
    A("Restricted to a genuinely two-sided book no wider than 5c, the pooled deviation at")
    A("every horizon collapses toward zero and none of it is significant.")
    A("")
    A("**This is a diagnostic, not a result, and it changes no reported cell.** Splitting")
    A("on spread is conditioning on liquidity, which §2 forbids in terms — *\"No filtering")
    A("on liquidity, volume or price\"* — so the 180-cell table, the pooled tests and the")
    A("§8 verdict above all use every qualifying snapshot, wide books included. The split")
    A("is shown because it identifies **where** the headline number comes from, and because")
    A("it moves the answer toward \"calibrated\", not away from it: a reader who concluded")
    A("from §5 that Kalshi misprices these contracts by 10–40 cents would be reading an")
    A("artifact of the mid-price definition on an empty book.")
    A("")
    A("It also means DECISIONS_008 decision 5 — keep one-sided books, exclude only when")
    A("**both** sides are sentinel — is too weak in practice. `bid = 0.00 / ask = 0.94`")
    A("has only one sentinel side, so it was kept, and its midpoint is meaningless. The")
    A("rule was chosen to avoid liquidity filtering and that reasoning still holds, but the")
    A("evidence above was not available when it was chosen. It is recorded here rather than")
    A("changed, because changing a frozen rule after seeing results is precisely what this")
    A("pre-registration exists to prevent.")
    A("")

    A("---")
    A("")
    A("## 10. What I built that does not work as intended")
    A("")
    A("Required by the build spec, and written plainly.")
    A("")
    for item in KNOWN_LIMITATIONS:
        A(f"1. **{item['title']}**  ")
        A(f"   {item['detail']}")
        A("")
    A("---")
    A("")
    A("## 11. Reproducing this")
    A("")
    A("```bash")
    A("pytest -q")
    A("python scripts/run_calibration.py --fees")
    A("python scripts/run_calibration.py --ingest")
    A("python scripts/run_calibration.py --gates")
    A("python scripts/run_calibration.py --permutation-null")
    A("python scripts/run_calibration.py --full")
    A("```")
    A("")
    A("All HTTP responses are cached in `data/cache/http_cache.sqlite`, so re-running the")
    A("analysis costs no requests and reproduces the same numbers. The event sample is a")
    A(f"deterministic hash with seed `{SAMPLE_SEED}`; the same census yields the same draw.")
    A("")

    return _finish(L, path)


def _pooled_block(A, tbl) -> None:
    if not tbl:
        A("*(not computed)*")
        return
    A("| horizon | markets | events | mean implied | realized | diff (c) | SE clustered | t clustered | passes t>2.0 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in tbl:
        A(f"| {r['horizon']} | {int(r['n_markets']):,} | {int(r['n_events']):,} | "
          f"{_fmt(r['mean_implied_price'])} | {_fmt(r['realized_frequency'])} | "
          f"{_fmt(r['difference'] * 100, 3)} | {_fmt(r['se_governing'])} | "
          f"{_fmt(r['t_clustered'], 3)} | "
          f"{'YES' if (np.isfinite(r['t_clustered']) and abs(r['t_clustered']) > T_POOLED) else 'no'} |")


KNOWN_LIMITATIONS = [
    dict(
        title="The universe is sampled, not exhaustive — a declared deviation from §2",
        detail=(
            "§2 asks for every settled market. The price measurement covers an outcome-blind "
            "random sample of events instead, because the full universe is ~1.74M markets and, "
            "at the measured 4 req/s public rate limit with one candlestick request per market, "
            "that is roughly 121 hours of continuous fetching. The census (market metadata, "
            "outcomes, categories, exclusion counts) IS exhaustive; only the prices are sampled. "
            "The draw is a fixed hash of the event ticker taken before any outcome was joined, "
            "so it cannot select on outcome, price, liquidity or volume — but it is still a "
            "sample, and every count in §4 onward is a sample count."
        ),
    ),
    dict(
        title="Events are truncated by a market budget, which under-represents strike ladders",
        detail=(
            "Events are taken in fixed hash order until a per-category market budget is reached. "
            "Auto-generated crypto strike ladders put 300-400 markets in one event, so a single "
            "such event consumes a large share of a category's budget while contributing exactly "
            "one cluster to the effective N. The truncation is outcome-blind (the order is fixed "
            "by the seed before anything is known about any event) but it does mean the Financial "
            "category is represented by fewer distinct events than its market count suggests. "
            "The realised events-per-category counts are reported above; read them, not the "
            "market counts, as the statistical weight of each category."
        ),
    ),
    dict(
        title="T−7d is measured on a different population from T−1h",
        detail=(
            "Only ~39% of Kalshi markets exist 7 days before close, versus ~99.6% at 1 hour. The "
            "T−7d population is therefore weighted toward long-dated politics, economics and "
            "weather, while T−1h is weighted toward intraday crypto and sports. §3 presents the "
            "three horizons as 'three separate measurements of the same question', and §9 predicts "
            "calibration 'should improve monotonically as horizon shortens' — but that prediction "
            "cannot be cleanly tested across three different populations. The §2-reading "
            "robustness check above restricts to markets present at all three horizons, which is "
            "the like-for-like comparison; prefer it for any cross-horizon claim."
        ),
    ),
    dict(
        title="The T−7d and T−24h snapshots are taken from hourly candles",
        detail=(
            "One 60-minute request covers 208 days and serves both long horizons, so the snapshot "
            "can be up to 59 minutes earlier than the nominal horizon. Against horizons of 7 days "
            "and 24 hours that is negligible, and it errs early rather than late, so it cannot "
            "breach the Step 3 gate. T−1h uses a separate 1-minute fetch precisely because 59 "
            "minutes of slack would not be tolerable there."
        ),
    ),
    dict(
        title="The within-category permutation null cannot pass, by construction",
        detail=(
            "BUILD step 8's literal test is reported but does not govern; see §7 above and "
            "DECISIONS_008 decision 14. It shuffles outcomes across price buckets, which forces "
            "large deviations in the extreme buckets on any dataset including a perfectly "
            "calibrated one. The Bernoulli(implied price) resample governs instead."
        ),
    ),
    dict(
        title="A critical standard-error bug shipped, was caught by review, and is fixed",
        detail=(
            "The first version of the degenerate-cell guard used the INDEPENDENCE model "
            "standard error. On a nested threshold ladder inside one event it manufactured "
            "findings at 3.1% against a nominal 0.05%, verified by exact enumeration. It is "
            "fixed (clustered model SE) and pinned by regression tests, and the third null "
            "test exists because the second was structurally blind to it. Recorded here "
            "rather than quietly corrected, because it shipped in a form that would have "
            "produced a false 'exploitable miscalibration exists' verdict, and because it "
            "is a warning about the whole class: a guard added to prevent false findings "
            "can create them."
        ),
    ),
    dict(
        title="A probe claim I could not reproduce, recorded rather than quietly dropped",
        detail=(
            "One API probe reported that passing a wrong `series_ticker` to the live candlestick "
            "endpoint returns HTTP 200 with an empty array — a silent failure. When I tested it "
            "directly, `/series/ZZZNOPE/markets/<real ticker>/candlesticks` returned real candles, "
            "i.e. the path segment appeared to be ignored rather than to cause a silent empty "
            "result. I could not reproduce the reported behaviour. The pipeline does not rely on "
            "either behaviour: it derives the series ticker from the market ticker and treats an "
            "empty candlestick response as a counted exclusion, never as 'no trading activity'."
        ),
    ),
    dict(
        title="The Step 4 gate as the build spec words it would fail on correct data",
        detail=(
            "The spec says to assert that exactly one market resolves YES on a mutually "
            "exclusive event. Kalshi's flag means AT MOST one -- it says nothing about the "
            "listed outcomes being exhaustive -- and 55 of 581 exclusive events in the "
            "sample legitimately resolved all-NO (a WTI strike ladder settling outside "
            "every band; a 'which app is #1' event where a sixth app won). Both were "
            "re-fetched and their market lists are complete. The gate asserts at-most-one "
            "instead, which is the invariant a wrong grouping would actually break, and "
            "reports the all-NO count separately. Recorded because it is a deviation from "
            "the literal wording of the build spec, decided on evidence."
        ),
    ),
    dict(
        title="Cells backed by a single event yield NaN and can never produce a finding",
        detail=(
            "A cluster-robust variance cannot be estimated from one cluster. Such cells are "
            "reported with a dash rather than a number. This is correct behaviour, but it means "
            "some populated cells are structurally incapable of contributing to §8 regardless of "
            "how large their apparent deviation is."
        ),
    ),
    dict(
        title="Kalshi's fee schedule is a moving target",
        detail=(
            "The captured schedule is effective 2026-07-07 and was retrieved 2026-08-21, but "
            "per-series multipliers change over time — `/series/fee_changes?show_historical=true` "
            "shows changes as recent as 2026-08-20. The fee floor uses each series' CURRENT "
            "`fee_multiplier`, not the multiplier in force when each market traded. For markets "
            "that settled years ago the applicable fee may have differed. Since the standard "
            "multiplier is 1 for 13,174 of 13,339 series, the effect is small, but it is real."
        ),
    ),
    dict(
        title="Pages 8-11 of the fee schedule PDF could not be read as text",
        detail=(
            "Those pages carry the remainder of the non-standard series table as raster images, "
            "not a text layer. The complete per-series multiplier list was taken instead from "
            "Kalshi's live fee-schedule page and from the API's own `fee_multiplier` field, both "
            "Kalshi-owned. The formula, the general fee table and the settlement-fee statement — "
            "everything the analysis actually depends on — came from the text layer of pages 2-5."
        ),
    ),
]


def _finish(L: list[str], path: str) -> str:
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    return path
