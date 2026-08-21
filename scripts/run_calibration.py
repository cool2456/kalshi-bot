#!/usr/bin/env python3
"""Experiment 008 runner.

    python scripts/run_calibration.py --fees              # step 0: the fee schedule
    python scripts/run_calibration.py --ingest            # steps 1-3: data + snapshots
    python scripts/run_calibration.py --gates             # steps 2-4: run every gate
    python scripts/run_calibration.py --permutation-null  # step 8
    python scripts/run_calibration.py --full              # everything + FINDINGS_008.md

This is a MEASUREMENT. It produces no trading rule and no strategy. PREREG_008 s8
forbids designing one from these results without a new pre-registration.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import numpy as np
import pandas as pd

from kalshi008 import analysis, fees, gates
from kalshi008.api import (
    DiskSpaceExhausted, KalshiAPIUnreachable, KalshiClient, check_reachable, free_disk_gb,
)
from kalshi008.buckets import BUCKET_EDGES, BUCKET_LABELS
from kalshi008.categories import KALSHI_TO_PREREG
from kalshi008.config import (
    BASE_URL, CATEGORIES, FEE_FLOOR_LEGS, HORIZONS, N_CELLS, PERMUTATIONS,
    SAMPLE_SEED, T_INDIVIDUAL, T_POOLED, T_UNCORRECTED,
)
from kalshi008.horizons import audit_close_before_settlement, audit_gate
from kalshi008.ingest import fetch_series, iso, parse_ts, read_jsonl, write_jsonl
from kalshi008.pipeline import (
    build_snapshots, collect_sampled_markets, derived, draw_event_sample,
    draw_event_sample_from_index, load_json, probe_combo_share, run_census, save_json,
)

UTC = dt.timezone.utc


def log(msg: str = "") -> None:
    print(msg, flush=True)


def rule(title: str) -> None:
    log("\n" + "=" * 78)
    log(title)
    log("=" * 78)


# ===========================================================================
# --fees  (BUILD step 0)
# ===========================================================================

def cmd_fees() -> dict:
    rule("STEP 0 — KALSHI FEE SCHEDULE, verified from Kalshi's own documentation")
    log(f"Source     : {fees.SCHEDULE_SOURCE_URL}")
    log(f"Document   : 'Fee Schedule for July 2026  - 7.7.26 Update'")
    log(f"Effective  : {fees.SCHEDULE_EFFECTIVE_DATE}   Retrieved: {fees.SCHEDULE_RETRIEVED_DATE}")
    log(f"Verbatim   : docs/sources/kalshi_fee_schedule_2026-07-07.md")
    log("")
    log("  Trading (taker) fee:  fees = round up(M x 0.07 x C x P x (1-P))     M defaults to 1")
    log("  Maker fee:            fees = round up(M x 0.0175 x C x P x (1-P))   M defaults to 0")
    log("  Settlement fee:       'There is no settlement fee.'")
    log("")
    failures = fees.verify_against_published_table()
    log(f"  Arithmetic check against Kalshi's published 21-row General Trading Fees Table:")
    if failures:
        log(f"    FAILED on {len(failures)} rows:")
        for f in failures[:10]:
            log(f"      {f}")
    else:
        log(f"    PASS — the formula reproduces all "
            f"{len(fees.PUBLISHED_GENERAL_FEE_TABLE)} published rows exactly, "
            f"at both 1 and 100 contracts.")
    log("")
    log("  FEE-EQUIVALENT PRICE ERROR PER BUCKET (cents of price), multiplier M = 1")
    log("  A taker who buys at P and holds to resolution pays 0.07*P*(1-P) dollars and")
    log("  nothing at settlement, so that fee IS the price error it cancels.")
    log("")
    log(f"    {'bucket':<10} {'mid':>6} {'1-leg':>8} {'2-leg':>8} {'lo edge':>9} {'hi edge':>9} {'worst':>8}")
    floors = fees.bucket_fee_floors(BUCKET_EDGES, legs=FEE_FLOOR_LEGS)
    floors2 = fees.bucket_fee_floors(BUCKET_EDGES, legs=2)
    rows = []
    for b, b2 in zip(floors, floors2):
        log(f"    {BUCKET_LABELS[b.bucket_index]:<10} {b.midpoint_cents:>6.1f} "
            f"{b.floor_at_midpoint_cents:>8.4f} {b2.floor_at_midpoint_cents:>8.4f} "
            f"{b.floor_at_low_edge_cents:>9.4f} {b.floor_at_high_edge_cents:>9.4f} "
            f"{b.max_floor_in_bucket_cents:>8.4f}")
        rows.append(dict(
            bucket=b.bucket_index, label=BUCKET_LABELS[b.bucket_index],
            midpoint_cents=b.midpoint_cents,
            floor_1leg_cents=b.floor_at_midpoint_cents,
            floor_2leg_cents=b2.floor_at_midpoint_cents,
            floor_low_edge_cents=b.floor_at_low_edge_cents,
            floor_high_edge_cents=b.floor_at_high_edge_cents,
            worst_in_bucket_cents=b.max_floor_in_bucket_cents,
        ))
    log("")
    log("  Resolving the §6 disagreement between public write-ups:")
    log("    '0% trading fees'          — true only for RESTING orders (maker M defaults to 0),")
    log("                                 and for the 14 series carrying M = 0 on both sides.")
    log("    'a tier capping at 7% of winnings' — a misreading of the 0.07 coefficient. The fee")
    log("                                 peaks at 0.07*0.25 = $0.0175/contract, i.e. 1.75% of")
    log("                                 notional at P = 50c, and is smaller everywhere else.")
    out = dict(
        source_url=fees.SCHEDULE_SOURCE_URL,
        effective_date=fees.SCHEDULE_EFFECTIVE_DATE,
        retrieved_date=fees.SCHEDULE_RETRIEVED_DATE,
        published_table_check_failures=failures,
        taker_formula="fees = round up(M x 0.07 x C x P x (1-P))",
        maker_formula="fees = round up(M x 0.0175 x C x P x (1-P))",
        settlement_fee="There is no settlement fee.",
        bucket_floors=rows,
    )
    save_json("fee_schedule.json", out)
    return out


# ===========================================================================
# --ingest  (BUILD steps 1-3)
# ===========================================================================

def cmd_ingest(args) -> dict:
    rule("STEPS 1-3 — DATA INGESTION, SETTLEMENT JOIN, HORIZON SNAPSHOTS")
    client = KalshiClient(offline=args.offline, min_free_gb=args.min_free_gb)
    try:
        status = check_reachable(client)
    except KalshiAPIUnreachable as e:
        log(f"  Kalshi API UNREACHABLE: {e}")
        log("  Stopping. No scraped aggregator or third-party mirror will be substituted.")
        raise SystemExit(2)
    log(f"  API reachable. exchange_active={status.get('exchange_active')}  base={BASE_URL}")

    cutoff = client.get("/historical/cutoff")
    cutoff_ts = parse_ts(cutoff["market_settled_ts"])
    now_ts = int(time.time())
    log(f"  /historical/cutoff market_settled_ts = {cutoff['market_settled_ts']}")
    log(f"    markets settled BEFORE it -> /historical/markets/{{ticker}}/candlesticks")
    log(f"    markets settled AFTER  it -> /series/{{s}}/markets/{{ticker}}/candlesticks")

    log("\n  fetching /series (one unpaginated request) ...")
    series = fetch_series(client)
    log(f"    {len(series):,} series; "
        f"{len(set(s['kalshi_category'] for s in series.values()))} distinct Kalshi categories")

    log("\n  CENSUS of every non-combo settled market (pass 1/2, nothing written to disk)")
    rep, excl, ev_index = run_census(
        client, series, cutoff_ts, now_ts,
        archive_pages=args.archive_pages, live_pages=args.live_pages, log=log,
    )
    save_json("census_report.json", rep)
    log(f"\n    census: {rep['markets_in_census']:,} markets, "
        f"{rep['markets_with_definitive_outcome']:,} with a definitive YES/NO outcome")
    log(f"    distinct events: {rep['distinct_events']:,}")
    log(f"    realised close_time range: {rep['realised_close_time_range']}")
    log(f"    per category: {rep['count_per_prereg_category_definitive']}")
    log(f"    excluded non-definitive: {rep['excluded_non_definitive_by_result']}")
    log(f"    exclusions by reason: {rep['exclusions_by_reason']}")

    log("\n  MVE COMBO SHARE (bounded probe; the census filter hides these server-side)")
    combo = probe_combo_share(client, log=log)
    save_json("combo_probe.json", combo)
    rep["mve_combo_probe"] = combo
    save_json("census_report.json", rep)

    log("\n  OUTCOME-BLIND EVENT SAMPLE (seed fixed, drawn from the event ticker only)")
    chosen, sinfo = draw_event_sample_from_index(
        ev_index, args.events_per_category, SAMPLE_SEED,
        max_markets_per_category=args.max_markets_per_category)
    save_json("sample_info.json", sinfo)
    log(f"    events available: {sinfo['total_events_in_census']:,}")
    log(f"    events drawn    : {sinfo['events_drawn']:,}  {sinfo['events_drawn_per_category']}")
    log(f"    markets/event in census: {sinfo['markets_per_event_in_census']}")
    log(f"    truncated because: {sinfo['draw_truncated_because']}")
    log("\n  PASS 2/2 — replaying the census from cache to collect the sampled markets")
    sampled = collect_sampled_markets(
        client, series, cutoff_ts, now_ts, chosen,
        archive_pages=args.archive_pages, live_pages=args.live_pages, log=log)
    log(f"    markets in sampled events: {len(sampled):,}")
    free = free_disk_gb(".")
    log(f"    free disk: {free:.2f} GB")

    # The census listing pages are read exactly twice and are then dead weight. On a
    # machine short of disk they would compete with the candlestick responses the
    # analysis actually needs, so drop them before the price fetch starts.
    if free < args.purge_cache_below_gb:
        before = client.cache_size()
        n = client.purge_cached([
            f"{BASE_URL}/historical/markets?%",
            f"{BASE_URL}/markets?status=settled%",
        ])
        log(f"    purged {n:,} cached census pages ({before:,} -> {client.cache_size():,} "
            f"rows); free disk now {free_disk_gb('.'):.2f} GB")

    log("\n  PRICES — one candlestick request per sampled market")
    snaps, reasons, pinfo = build_snapshots(client, sampled, cutoff_ts, log=log)
    log(f"    {pinfo['snapshots_produced']:,} snapshots  {pinfo['snapshots_per_horizon']}")
    log(f"    {client.stats.summary()}")

    write_jsonl(derived("snapshots.jsonl"), [s.to_dict() for s in snaps])
    write_jsonl(derived("sampled_markets.jsonl"), sampled)
    save_json("ingest_info.json", dict(
        cutoff=cutoff, sample=sinfo, prices=pinfo,
        per_horizon_exclusions=dict(reasons),
        request_stats=dict(sent=client.stats.sent, cache_hits=client.stats.cache_hits,
                           http_200=client.stats.http_200, http_404=client.stats.http_404,
                           http_429=client.stats.http_429, retries=client.stats.retries),
        endpoints_used={
            "series": f"{BASE_URL}/series",
            "archive_markets": f"{BASE_URL}/historical/markets?mve_filter=exclude",
            "live_markets": f"{BASE_URL}/markets?status=settled&mve_filter=exclude&min_close_ts&max_close_ts",
            "archive_candles": f"{BASE_URL}/historical/markets/{{ticker}}/candlesticks",
            "live_candles": f"{BASE_URL}/series/{{series}}/markets/{{ticker}}/candlesticks",
            "cutoff": f"{BASE_URL}/historical/cutoff",
        },
    ))
    return dict(census=rep, sample=sinfo, prices=pinfo)


# ===========================================================================
# --gates  (BUILD steps 2, 3, 4)
# ===========================================================================

def _load_for_analysis():
    p_snap, p_mk = derived("snapshots.jsonl"), derived("sampled_markets.jsonl")
    if not (os.path.exists(p_snap) and os.path.exists(p_mk)):
        log("  No ingested data found. Run --ingest first.")
        raise SystemExit(3)
    snaps = list(read_jsonl(p_snap))
    mkts = list(read_jsonl(p_mk))
    return snaps, mkts


def cmd_gates(args) -> dict:
    rule("STEPS 2-4 — GATES (each one is RUN, not asserted)")
    snaps, sampled = _load_for_analysis()
    census = sampled
    analysed_tickers = {s["ticker"] for s in snaps}
    analysed = [m for m in sampled if m["ticker"] in analysed_tickers]

    results = []

    g = gates.gate_definitive_outcomes(analysed, census)
    log(g.render()); results.append(g)

    g = gates.gate_result_matches_settlement_value(sampled)
    log(g.render()); results.append(g)

    if not args.offline:
        client = KalshiClient()
        g = gates.hand_check_settlement_join(client, analysed)
        log(g.render()); results.append(g)
        if g.detail.get("rows"):
            log("\n        hand-checked markets:")
            log(f"        {'category':<11}{'ticker':<34}{'result':<7}{'refetched':<10}{'ok'}")
            for r in g.detail["rows"]:
                log(f"        {r['category']:<11}{r['ticker'][:33]:<34}"
                    f"{str(r['census_result']):<7}{str(r['refetched_result']):<10}"
                    f"{'yes' if r['agrees'] else 'NO'}")
    else:
        log("  [SKIPPED] Step 2 hand-check requires network (--offline set). This gate")
        log("            has NOT been run, so the gate summary below reports NOT RUN.")
        results.append(gates.GateResult(
            name="Step 2 gate: hand-check of the settlement join on a cross-category sample",
            passed=False,
            detail={"status": "NOT RUN -- --offline was set; network required"},
        ))

    # Step 3
    log("")
    from kalshi008.horizons import Snapshot
    snap_objs = [Snapshot(**{k: v for k, v in s.items() if k in Snapshot.__annotations__}) for s in snaps]
    a = audit_gate(snap_objs)
    g3 = gates.GateResult(
        name="Step 3 gate: every price is timestamped STRICTLY before settlement minus H",
        passed=a["passed"], detail=a,
    )
    log(g3.render()); results.append(g3)

    ga = audit_close_before_settlement(sampled)
    g3b = gates.GateResult(
        name="Step 3 support: close_time <= settlement_ts on every market (what makes T=close safe)",
        passed=ga["passed"], detail=ga,
    )
    log(g3b.render()); results.append(g3b)

    # Step 4
    log("")
    ev_index = load_json("events_index.json") or {}
    if not ev_index and not args.offline:
        log("  fetching event metadata for the sampled events (mutually_exclusive flag) ...")
        client = KalshiClient()
        ev_index = {}
        want = sorted({m["event_ticker"] for m in sampled})
        for i, ev in enumerate(want, 1):
            # with_nested_markets costs the same one request and carries the event's
            # FULL market list, which is what makes the Step 4 completeness guard real
            # rather than inert: a partially sampled event would otherwise show 0 YES and
            # be reported as a violation of mutual exclusivity that never happened.
            payload = client.get(f"/events/{ev}?with_nested_markets=true", allow_404=True)
            if payload and payload.get("event"):
                e = payload["event"]
                nested = e.get("markets") or payload.get("markets") or []
                ev_index[ev] = {
                    "mutually_exclusive": bool(e.get("mutually_exclusive")),
                    "collateral_return_type": e.get("collateral_return_type"),
                    "series_ticker": e.get("series_ticker"),
                    "n_markets_expected": len(nested) if nested else None,
                }
            if i % 500 == 0:
                log(f"    events: {i:,}/{len(want):,}")
        save_json("events_index.json", ev_index)
    g4 = gates.gate_mutually_exclusive_events(ev_index, sampled)
    log(g4.render()); results.append(g4)

    dist = gates.markets_per_event_distribution(sampled)
    log("\n  Markets-per-event distribution (BUILD step 4 / PREREG s5):")
    for k, v in dist.items():
        log(f"        {k}: {v}")

    save_json("gates.json", dict(
        results=[dict(name=r.name, passed=r.passed, detail=r.detail) for r in results],
        markets_per_event=dist,
    ))
    all_pass = all(r.passed for r in results)
    log("")
    for r in results:
        log(f"    {'PASS' if r.passed else 'NOT PASSED'}  {r.name}")
    log(f"\n  ALL GATES {'PASSED' if all_pass else 'DID NOT PASS'} "
        f"({sum(1 for r in results if r.passed)}/{len(results)})")
    return dict(passed=all_pass, results=[dict(name=r.name, passed=r.passed) for r in results],
                markets_per_event=dist)


# ===========================================================================
# --permutation-null  (BUILD step 8)
# ===========================================================================

def cmd_permutation(args) -> dict:
    rule("STEP 8 — NULL TESTS (two of them; see DECISIONS_008 decision 14)")
    snaps, _ = _load_for_analysis()
    df = analysis.snapshots_to_frame(snaps)
    if df.empty:
        log("  No snapshots. Run --ingest first.")
        raise SystemExit(3)

    log(f"  {len(df):,} snapshots, {args.permutations} replications of each null.\n")

    log("  NULL 1 — within-category permutation, exactly as BUILD step 8 specifies.")
    log("  Within-group shuffling preserves each category's YES count EXACTLY, so the")
    log("  marginal YES rate is identical in every replication.")
    log("  NOTE: this null shuffles outcomes ACROSS price buckets, which drives every")
    log("  bucket's realized frequency to the category mean. A non-zero count below is")
    log("  forced by that design and is NOT evidence of a pipeline defect.\n")
    res = analysis.permutation_null(df, n=args.permutations)
    log(f"    cells passing corrected   t > {T_INDIVIDUAL}: {res.cells_passing_corrected}")
    log(f"    cells passing uncorrected t > {T_UNCORRECTED}: {res.cells_passing_uncorrected}")
    log(f"    max |t| per replication: {[round(x,2) for x in res.max_abs_t_per_permutation]}")

    log("\n  NULL 2 — Bernoulli(implied price) resample. THIS ONE GOVERNS.")
    log("  Each outcome is redrawn from its own market's implied price, so the market is")
    log("  calibrated at every price BY CONSTRUCTION and the true difference in every")
    log("  cell is zero. Any cell reaching t > 3.5 means the standard errors are too")
    log("  small — which is exactly the failure BUILD step 8 exists to catch.\n")
    ber = analysis.bernoulli_null(df, n=args.permutations)
    log(f"    cells passing corrected   t > {T_INDIVIDUAL}: {ber.cells_passing_corrected}")
    log(f"    cells passing uncorrected t > {T_UNCORRECTED}: {ber.cells_passing_uncorrected}")
    log(f"    max |t| per replication: {[round(x,2) for x in ber.max_abs_t_per_replication]}")
    log(f"    max |diff| cents per replication: "
        f"{[round(x,2) for x in ber.max_abs_diff_cents_per_replication]}")
    log("\n  NULL 3 — Bernoulli resample, COMONOTONIC within each event. ALSO GOVERNS.")
    log("  One uniform draw per event shared by all its markets, so marginals are exactly")
    log("  the implied prices but within-event dependence is maximal. Null 2 draws each")
    log("  market independently and therefore cannot see a clustering failure at all.\n")
    cber = analysis.clustered_bernoulli_null(df, n=args.permutations)
    log(f"    cells passing corrected   t > {T_INDIVIDUAL}: {cber.cells_passing_corrected}")
    log(f"    cells passing uncorrected t > {T_UNCORRECTED}: {cber.cells_passing_uncorrected}")
    log(f"    max |t| per replication: {[round(x,2) for x in cber.max_abs_t_per_replication]}")

    governing_passed = ber.passed and cber.passed
    n_pop = analysis._n_populated(df)
    crit_b = analysis.null_pass_criterion(sum(ber.cells_passing_corrected),
                                          ber.n_replications * n_pop)
    crit_c = analysis.null_pass_criterion(sum(cber.cells_passing_corrected),
                                          cber.n_replications * n_pop)
    log("")
    log(f"  Pass criterion: the exceedance count must be consistent with the nominal rate,")
    log(f"  not exactly zero. With {n_pop} populated cells x {ber.n_replications} replications "
        f"= {crit_b['n_tests']:,} tests,")
    log(f"  a correct pipeline is EXPECTED to throw ~{crit_b['expected_exceedances']:.2f} cells "
        f"above t > {T_INDIVIDUAL};")
    log(f"  the 99th-percentile threshold is {crit_b['threshold_99th_percentile']}.")
    log(f"    null 2 (independent) : observed {crit_b['observed_exceedances']} -> "
        f"{'PASS' if crit_b['passed'] else 'FAIL'}")
    log(f"    null 3 (comonotonic) : observed {crit_c['observed_exceedances']} -> "
        f"{'PASS' if crit_c['passed'] else 'FAIL'}")
    log("")
    if governing_passed:
        log(f"    PASS — both governing nulls are consistent with the nominal false-positive")
        log(f"    rate. The pipeline is not manufacturing significance from its own structure.")
    else:
        log(f"    FAIL — cells passed t > {T_INDIVIDUAL} under a governing null "
            f"(independent={ber.passed}, comonotonic={cber.passed}).")
        log("    The pipeline is manufacturing significance. NO RESULT FROM IT IS USABLE.")

    out = dict(
        within_category_permutation=dict(
            n_permutations=res.n_permutations,
            cells_passing_corrected=res.cells_passing_corrected,
            cells_passing_uncorrected=res.cells_passing_uncorrected,
            max_abs_t=res.max_abs_t_per_permutation,
            passed=res.passed,
            governs=False,
            note="Shuffles outcomes across price buckets; a non-zero count is forced by "
                 "the design, not by a pipeline defect. See DECISIONS_008 decision 14.",
        ),
        bernoulli_null=dict(
            n_replications=ber.n_replications,
            cells_passing_corrected=ber.cells_passing_corrected,
            cells_passing_uncorrected=ber.cells_passing_uncorrected,
            max_abs_t=ber.max_abs_t_per_replication,
            max_abs_diff_cents=ber.max_abs_diff_cents_per_replication,
            passed=ber.passed,
            governs=True,
            note=ber.note,
        ),
        pass_criterion=dict(bernoulli=crit_b, clustered_bernoulli=crit_c),
        clustered_bernoulli_null=dict(
            n_replications=cber.n_replications,
            cells_passing_corrected=cber.cells_passing_corrected,
            cells_passing_uncorrected=cber.cells_passing_uncorrected,
            max_abs_t=cber.max_abs_t_per_replication,
            max_abs_diff_cents=cber.max_abs_diff_cents_per_replication,
            passed=cber.passed,
            governs=True,
            note=cber.note,
        ),
        passed=governing_passed,
    )
    save_json("null_tests.json", out)
    return out


# ===========================================================================
# --full
# ===========================================================================

def cmd_full(args) -> dict:
    fee = cmd_fees()
    if not args.no_ingest:
        cmd_ingest(args)
    gate_res = cmd_gates(args)

    rule("STEPS 5-7 — CALIBRATION TABLES, SIGNIFICANCE, FEE OVERLAY")
    snaps, sampled = _load_for_analysis()
    df = analysis.snapshots_to_frame(snaps)
    cells = analysis.build_cells(df)
    floors = analysis.fee_floor_table(df)
    cells = analysis.apply_fee_overlay(cells, floors, df=df)
    pooled = analysis.pooled_by_horizon(df)
    pooled_b = analysis.pooled_by_horizon_bucket(df)
    recl = analysis.recluster_hits(df, cells)

    populated = cells[cells["n_markets"] > 0]
    n_unc = int(cells["passes_uncorrected"].fillna(False).sum())
    n_cor = int(cells["passes_corrected"].fillna(False).sum())
    log(f"  {N_CELLS} cells; {len(populated)} populated, {N_CELLS - len(populated)} empty")
    log(f"  cells passing UNCORRECTED t > {T_UNCORRECTED}: {n_unc}")
    log(f"  cells passing CORRECTED   t > {T_INDIVIDUAL}: {n_cor}")
    log(f"  cells clearing BOTH t > {T_INDIVIDUAL} and the 1-leg fee floor: "
        f"{int(cells['is_finding_1leg'].fillna(False).sum())}")

    perm = cmd_permutation(args)

    rule("STEP 9 — PRE-COMMITTED CONCLUSION (PREREG s8)")
    concl = analysis.prereg_conclusion(cells, pooled_b, floors, recl)
    if not perm["passed"]:
        concl["verdict"] = "UNUSABLE — the governing (Bernoulli) null failed"
    log(f"  VERDICT: {concl['verdict']}")
    log(f"  effective N (distinct events) per horizon:")
    for _, r in pooled.iterrows():
        log(f"    {r['horizon']:<7} markets={int(r['n_markets']):,}  events={int(r['n_events']):,}  "
            f"diff={r['difference']*100:+.3f}c  t_clustered={r['t_clustered']:+.3f}")

    cells.to_csv(derived("calibration_cells.csv"), index=False)
    pooled.to_csv(derived("pooled_by_horizon.csv"), index=False)
    pooled_b.to_csv(derived("pooled_by_horizon_bucket.csv"), index=False)
    floors.to_csv(derived("fee_floors.csv"), index=False)
    if not recl.empty:
        recl.to_csv(derived("recluster_hits.csv"), index=False)
    save_json("conclusion.json", concl)

    # ---- robustness checks (DECISIONS decisions 6 and 12)
    rule("ROBUSTNESS CHECKS")
    rb = {}
    sub2 = analysis.all_three_horizons_subset(df)
    log(f"  §2 reading (markets qualifying at all three horizons): "
        f"{sub2['ticker'].nunique() if len(sub2) else 0:,} markets, {len(sub2):,} snapshots")
    rb["all_three_horizons"] = (
        analysis.pooled_by_horizon(sub2).to_dict("records") if len(sub2) else []
    )
    subf = analysis.fresh_subset(df)
    log(f"  freshness check (snapshot age <= one horizon-period): {len(subf):,} snapshots "
        f"of {len(df):,}")
    rb["fresh"] = analysis.pooled_by_horizon(subf).to_dict("records") if len(subf) else []

    stale = {}
    one_sided = {}
    for h in HORIZONS:
        sub = df[df["horizon"] == h]
        if not len(sub):
            continue
        v = sub["staleness_s"].to_numpy()
        stale[h] = dict(
            n=int(len(v)), median=int(np.median(v)),
            p90=int(np.percentile(v, 90)), p99=int(np.percentile(v, 99)), max=int(v.max()),
        )
        one_sided[h] = float(sub["one_sided_book"].mean())
    rb["staleness"] = stale
    rb["one_sided_share"] = one_sided
    log(f"  staleness (seconds): { {h: (d['median'], d['p90'], d['max']) for h, d in stale.items()} }")
    log(f"  one-sided book share: { {h: round(v, 3) for h, v in one_sided.items()} }")
    bq = analysis.book_quality_table(df)
    if not bq.empty:
        bq.to_csv(derived("book_quality.csv"), index=False)
        log("\n  BOOK-QUALITY DIAGNOSTIC (§9: treat a large miscalibration as a bug first)")
        log(f"    {'stratum':<34}{'n':>7}{'events':>8}{'implied':>9}{'realized':>10}{'diff(c)':>9}{'t':>8}")
        for _, r in bq.iterrows():
            log(f"    {r['stratum']:<34}{int(r['n_markets']):>7,}{int(r['n_events']):>8,}"
                f"{r['mean_implied_price']:>9.4f}{r['realized_frequency']:>10.4f}"
                f"{r['difference']*100:>+9.3f}{r['t_clustered']:>+8.3f}")
    save_json("robustness.json", rb)

    from kalshi008.report import write_findings
    path = write_findings(
        fee=fee, gates_result=gate_res, cells=cells, pooled=pooled,
        pooled_bucket=pooled_b, floors=floors, recluster=recl, permutation=perm,
        conclusion=concl, df=df, robustness=rb,
        book_quality=bq.to_dict("records") if not bq.empty else None,
    )
    log(f"\n  wrote {path}")
    return concl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fees", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--gates", action="store_true")
    ap.add_argument("--permutation-null", dest="permutation", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--events-per-category", type=int, default=1200,
                    help="events sampled per PREREG category (6 categories)")
    ap.add_argument("--max-markets-per-category", type=int, default=6000,
                    help="market budget per category; events are taken in fixed hash "
                         "order until it is reached")
    ap.add_argument("--permutations", type=int, default=PERMUTATIONS)
    ap.add_argument("--archive-pages", type=int, default=None)
    ap.add_argument("--live-pages", type=int, default=None)
    ap.add_argument("--offline", action="store_true", help="use only the local HTTP cache")
    ap.add_argument("--purge-cache-below-gb", type=float, default=6.0,
                    help="after sampling, drop cached census pages if free disk is below this")
    ap.add_argument("--min-free-gb", type=float, default=3.0,
                    help="abort rather than let the response cache push free disk below this")
    ap.add_argument("--no-ingest", action="store_true", help="with --full, reuse existing data")
    args = ap.parse_args()

    if not any([args.fees, args.ingest, args.gates, args.permutation, args.full]):
        ap.print_help()
        return
    if args.full:
        cmd_full(args); return
    if args.fees:
        cmd_fees()
    if args.ingest:
        cmd_ingest(args)
    if args.gates:
        cmd_gates(args)
    if args.permutation:
        cmd_permutation(args)


if __name__ == "__main__":
    main()
