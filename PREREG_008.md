# Pre-registration 008 — Kalshi market calibration

**Committed on:** 2026-08-21

**Repository:** `kalshi-research` (new). Experiments 001–007 live in `trendbot`
and are unaffected by anything here.

**This is a measurement study, not a strategy test.** It measures a property of the
market. It does not backtest a way to trade it, and it produces no trading rule.

**Counters:**
- `measurement_studies = 1`
- `strategy_configs_tried = 0` — no strategy has been tested in this domain.

**The counter that carries forward.** Experiments 001–007 tested equity, ETF and FX
factor anomalies. Those are a different family and their count does not transfer.
But if a Kalshi strategy is ever reported as a success alongside that work — "here
is the one that worked" — the honest multiple-testing family is *everything
attempted across both projects*. Recorded now so it cannot be forgotten later.

Frozen on commit. Changes to §2–6 create experiment 009.

---

## 1. Question

**Are Kalshi contract prices calibrated? That is, do contracts trading at price `p`
resolve YES with frequency `p`?**

This is deliberately not "can I beat the market." A calibration measurement is
prior to any strategy: if prices are well calibrated within fee bounds, no
probability model can profit regardless of quality, and experiment 009 should never
be written. If they are systematically miscalibrated, the shape of the
miscalibration determines what a strategy would have to look like.

**Why this domain is worth measuring at all.** Every prior experiment failed on
insufficient independent breadth — 12 ETFs collapsing to one beta, 41 ETFs at
beta 0.913, 22 currencies at 0.952. Kalshi resolves hundreds of contracts weekly
across weather, economics, politics and sports. Whether it rains in Chicago is
genuinely independent of whether the Fed holds. That is real breadth, and it is the
first dataset in this program that has it.

The data is also the cleanest encountered here: binary resolution, recorded
outcomes, no survivorship, no restatement, no corporate actions, no adjustment
factors. The failure modes that invalidated 003, blocked 004 and complicated 007
do not exist.

Prior: betting and prediction markets have shown **favorite-longshot bias** for
decades — longshots overpriced, favorites underpriced. If it exists here, it should
appear as realized frequency below implied price in the low-price buckets.

## 2. Universe

**Every settled Kalshi market** available through the public API, subject to:

- Resolved with a definitive YES or NO outcome. Voided, cancelled and
  ambiguously-settled markets are **excluded and counted**.
- At least one recorded trade at each measurement horizon in §3.
- Settlement date within the API's available archive. Report the realised range.

No category is excluded. No filtering on liquidity, volume or price. Filtering after
seeing outcomes is the single easiest way to manufacture a calibration finding.

Report total markets, exclusions by reason, and the count per category.

## 3. Measurement

For each market, record the **mid price** at three fixed horizons before settlement:

- **T−7 days**
- **T−24 hours**
- **T−1 hour**

All three are reported. None is the headline; they are three separate measurements
of the same question at different information horizons, and reporting only the most
favourable would be selection.

Markets that did not exist or had no trades at a given horizon are excluded from
*that horizon only*, and the count is reported per horizon.

**Bucketing:** prices sorted into 10 fixed buckets — [0,10), [10,20), … [90,100] —
in cents. Fixed edges, not quantiles, so the buckets are the same across every
category and horizon.

For each bucket: mean implied price, realized YES frequency, count, and the
difference with its standard error.

## 4. Categories — pre-specified, all reported

Markets are grouped by Kalshi's own series categorisation into:

**Weather · Economics · Politics · Sports · Financial (crypto/index levels) · Other**

All six are reported at all three horizons for all ten buckets. **No category may be
selected as the headline after results are seen.** If one shows miscalibration and
five do not, the finding is "one of six categories, uncorrected," and §6's
correction applies.

## 5. Independence and clustering

**Markets within the same event are not independent.** An event with five mutually
exclusive outcomes produces five markets whose resolutions are perfectly dependent —
exactly one resolves YES.

Naive standard errors across all markets would therefore be badly understated. Two
things are required:

1. **Cluster standard errors at the event level.** Report both naive and clustered;
   the clustered figures govern §6.
2. **Report the effective sample size** — number of distinct events, not number of
   markets — alongside every test.

This is the equivalent of the correlation problem that produced beta 0.913 in
experiment 002. It is stated in advance because it is the most likely way a
calibration study overstates its own significance.

## 6. Multiple testing and the fee floor

**10 buckets × 6 categories × 3 horizons = 180 tests.** A finding at t > 2.0 is
expected by chance many times over.

- **Bonferroni-corrected threshold: t > 3.5** for any individual bucket-category
  cell to count as a finding.
- The **aggregate calibration test across all markets** (all categories pooled, per
  horizon) uses t > 2.0, since it is 3 tests, not 180.

**The fee floor.** A miscalibration smaller than round-trip cost is not exploitable
and is not a finding for any purpose beyond description.

Kalshi's fee schedule must be **verified directly from Kalshi's own published
documentation before analysis**, not taken from secondary sources — public write-ups
disagree, with some reporting 0% trading fees and others a tier capping at 7% of
winnings. Record the schedule, its source, and the date retrieved. Compute the
fee-equivalent price error per bucket and plot it against measured miscalibration.

## 7. What is frozen

Universe rule · exclusion criteria · the three horizons · bucket edges · the six
categories · clustering at event level · Bonferroni threshold · the requirement to
report all 180 cells.

## 8. Pre-committed conclusions

**"Exploitable miscalibration exists"** requires:

- At least one bucket-category-horizon cell with |realized − implied| exceeding the
  §6 fee floor, at clustered **t > 3.5**, AND
- The same directional bias visible at **two or more** of the three horizons — a
  miscalibration present only at T−1h is likely a settlement-mechanics artifact, not
  a tradeable inefficiency.

**"Market is calibrated"** if the pooled test shows |realized − implied| within the
fee floor at every bucket, at all three horizons.

**Anything else is "descriptive only"** — patterns worth recording, insufficient to
justify writing experiment 009.

**No strategy may be designed from this study's results without a new
pre-registration that states which category was selected and why, and acknowledges
that the selection was informed by this study.** That acknowledgment is what keeps
the eventual strategy's multiple-testing correction honest.

## 9. Expectations of record

- **Most likely outcome: mild favorite-longshot bias, too small to exploit after
  fees.** That is the standard finding in liquid prediction markets and it would be
  a clean, useful negative.
- Weather and financial contracts should be the best calibrated — objective,
  publicly forecast base rates. Politics and Other should be the worst.
- Calibration should improve monotonically as horizon shortens.
- Extreme buckets ([0,10) and [90,100]) will show the largest deviations and the
  largest standard errors simultaneously; that is where a naive analysis
  manufactures false findings.
- Effective sample size will be **much** smaller than market count. If 10,000
  markets resolve to 1,500 distinct events, the effective N is 1,500.
- **A large, clean miscalibration would be surprising and should be treated as a
  bug first** — most likely a horizon snapshot taken after information the market
  had not yet priced, or settled-outcome data joined incorrectly.

## 10. Signature

Running §3–6 without modifying §2–7.

Signed: **Pranav**   Date: **2026-08-21**
