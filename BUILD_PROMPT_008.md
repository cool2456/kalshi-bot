# Claude Code build prompt — experiment 008 (Kalshi calibration)

New repository, `kalshi-research`, with `PREREG_008.md` committed and tagged.
No account required — Kalshi's market data endpoints need no authentication.

---

Build a calibration measurement of Kalshi prediction market prices, specified in
`PREREG_008.md`. Read it first.

**This is a measurement study. It produces no trading rule and no strategy.** If you
find yourself designing one, stop — §8 forbids it without a new pre-registration.

`PREREG_008.md` is the sole source of truth. Do not invent, tune or substitute any
parameter. Stop and ask on genuine ambiguity rather than choosing. In a prior
project that behaviour caught eight specification gaps across six experiments, every
one at a point where a number was decided. Assume this document is underspecified
too.

This is a fresh repository. Set up `.gitignore` for `.env`, caches and data before
any code exists.

## Build order

**Step 0 — fee schedule, first.** §6 requires Kalshi's fee schedule verified from
Kalshi's own published documentation, not secondary sources — public write-ups
disagree, some reporting zero trading fees and others a tier capping at 7% of
winnings. Record the schedule verbatim, its URL, and the retrieval date in
`FINDINGS_008.md`. Compute the fee-equivalent price error per price bucket.

Everything downstream is interpreted against this number. Get it right first.

**Step 1 — data ingestion.** Fetch settled markets and their price histories from
Kalshi's public API. Cache locally. Identify your client honestly in the User-Agent
and rate-limit politely; this is a free public endpoint.

Note that archived markets may live on different endpoints from live ones. Report
which endpoints supplied which data and the realised date range.

**If the API is unreachable, stop and report it. Do not substitute a scraped
aggregator or a third-party mirror.**

**Step 2 — settlement join.** Join each market to its resolution.
*Gate:* assert every market in the analysis set has a definitive YES/NO outcome, and
that voided/cancelled markets are excluded and counted separately. A market whose
resolution is joined incorrectly produces a calibration finding out of nothing —
verify the join on a hand-checked sample of 20 markets across categories.

**Step 3 — horizon snapshots.** Mid price at T−7d, T−24h, T−1h per §3.
*Gate — this is the one most likely to fabricate a result:* assert that every price
used at horizon H is timestamped **strictly before** settlement minus H. A snapshot
taken even slightly late captures information the market had already absorbed and
manufactures apparent miscalibration. Test with a fixture containing a market that
settled early.

Report per-horizon inclusion counts; markets without trades at a horizon are
excluded from that horizon only.

**Step 4 — event clustering.** Map every market to its parent event. Report the
distribution of markets per event, and the count of distinct events.
*Gate:* on an event with N mutually exclusive outcomes, assert exactly one resolves
YES. If that fails, the event grouping is wrong.

**Step 5 — calibration tables.** Fixed 10-cent buckets per §3. For each of the
10 buckets × 6 categories × 3 horizons: mean implied price, realized frequency,
count, distinct events, difference, **naive SE and event-clustered SE**.

Report all 180 cells. Do not summarise to the interesting ones.

**Step 6 — significance.** Bonferroni threshold t > 3.5 for individual cells, t > 2.0
for the 3 pooled tests, per §6. Use clustered standard errors. Report how many cells
would have passed at an uncorrected t > 2.0 — that number is the illustration of why
the correction exists.

**Step 7 — the fee overlay.** Plot measured miscalibration per bucket against the
Step 0 fee-equivalent price error. State plainly which cells, if any, exceed both
the statistical threshold and the fee floor.

**Step 8 — null test.** Permute settlement outcomes within each category, preserving
the marginal YES rate, and re-run the entire pipeline. Expected: no cells pass
t > 3.5. ≥8 permutations. **If cells pass under permutation, the pipeline is
manufacturing significance and no result from it is usable.**

**Step 9 — conclusion** per §8, stated plainly as one of: exploitable
miscalibration exists / market is calibrated / descriptive only. Report the
effective sample size beside every claim.

## Do not

- Do not design, backtest, or suggest a trading strategy.
- Do not filter markets by liquidity, volume or price after seeing outcomes.
- Do not select a headline category or horizon after seeing results.
- Do not report uncorrected t-statistics as findings.
- Do not use naive standard errors for any §8 conclusion.
- Do not report a gate as passed without running it.

## Verify before reporting done

```
pytest -q
python scripts/run_calibration.py --fees
python scripts/run_calibration.py --gates
python scripts/run_calibration.py --permutation-null
python scripts/run_calibration.py --full
```

`FINDINGS_008.md` must contain: the verified fee schedule with source URL and date,
data provenance by endpoint with realised date range, the settlement-join hand-check,
the horizon timestamp assertion result, markets-per-event distribution and distinct
event count, all 180 calibration cells with naive and clustered SEs, the count of
cells passing at uncorrected t > 2.0 versus corrected t > 3.5, the fee overlay, the
permutation null results, the §8 conclusion, and a plain list of anything you built
that you believe does not work as intended.
