# FINDINGS 008 — Kalshi market calibration

**Run date:** 2026-08-21 20:08 UTC
**Pre-registration:** `PREREG_008.md` (tag `prereg-008`), unmodified.
**Resolved specification gaps:** `DECISIONS_008.md`, all fixed before analysis ran.

> This is a **measurement**. It produces no trading rule and no strategy.
> PREREG_008 §8 forbids designing one from these results without a new
> pre-registration that states which category was selected and why.

---

## 1. Verified fee schedule (§6, BUILD step 0)

**Source:** <https://kalshi.com/docs/kalshi-fee-schedule.pdf> — *Fee Schedule for July 2026 - 7.7.26 Update*  
**Effective:** 2026-07-07 · **Retrieved:** 2026-08-21  
**Verbatim capture:** `docs/sources/kalshi_fee_schedule_2026-07-07.md`

Retrieved from Kalshi's own published PDF. `kalshi.com` sits behind a Vercel JS
checkpoint that returns HTTP 429 to plain fetchers, so the document was fetched
inside a real browser session and its text layer decoded from the PDF content
streams. No secondary source, aggregator or mirror was used.

```
Trading (taker) fee:  fees = round up(M x 0.07 x C x P x (1-P))
  P = the price of a contract in dollars (50 cents is 0.5)
  C = the number of contracts being traded
  M = the multiplier for each contract (default is 1 unless otherwise indicated)

Maker fee:            fees = round up(M x 0.0175 x C x P x (1-P))
  M = the multiplier for each contract (default is 0 unless otherwise indicated)

Settlement fee:       There is no settlement fee.
```

**Arithmetic verification:** the formula reproduces **all 21 rows** of Kalshi's own
published General Trading Fees Table exactly, at both 1 and 100 contracts (0 failures).

**§6's disagreement resolved.** Neither public reading survives the primary source:

- *"0% trading fees"* — true only for **resting** (maker) orders, because the maker
  multiplier defaults to **0**; and for the 14 series carrying M = 0 on both sides.
  False for any order that crosses the spread.
- *"a tier capping at 7% of winnings"* — a misreading of the coefficient `0.07`. It is
  not a cap; it multiplies `P × (1−P)`. The fee peaks at `0.07 × 0.25 = $0.0175` per
  contract at P = 50c — **1.75% of notional**, not 7% of anything.

### Fee-equivalent price error per bucket

A taker who buys at P and holds to resolution pays `0.07 × M × P × (1−P)` dollars and
nothing at settlement, so that fee **is** the price error it cancels. The round-up is
not applied: it is an artifact of order size, and the continuous form is the smaller,
more conservative per-contract floor.

| bucket | midpoint | 1-leg floor (c) | 2-leg floor (c) | low edge | high edge | worst in bucket |
|---|---|---|---|---|---|---|
| [0,10) | 5.0c | 0.3325 | 0.6650 | 0.0000 | 0.6300 | 0.6300 |
| [10,20) | 15.0c | 0.8925 | 1.7850 | 0.6300 | 1.1200 | 1.1200 |
| [20,30) | 25.0c | 1.3125 | 2.6250 | 1.1200 | 1.4700 | 1.4700 |
| [30,40) | 35.0c | 1.5925 | 3.1850 | 1.4700 | 1.6800 | 1.6800 |
| [40,50) | 45.0c | 1.7325 | 3.4650 | 1.6800 | 1.7500 | 1.7500 |
| [50,60) | 55.0c | 1.7325 | 3.4650 | 1.7500 | 1.6800 | 1.7500 |
| [60,70) | 65.0c | 1.5925 | 3.1850 | 1.6800 | 1.4700 | 1.6800 |
| [70,80) | 75.0c | 1.3125 | 2.6250 | 1.4700 | 1.1200 | 1.4700 |
| [80,90) | 85.0c | 0.8925 | 1.7850 | 1.1200 | 0.6300 | 1.1200 |
| [90,100] | 95.0c | 0.3325 | 0.6650 | 0.6300 | 0.0000 | 0.6300 |

The floor is **largest in the middle buckets and near zero at the extremes** — the
opposite shape to where §9 predicts the largest raw deviations. That shape, not just
its level, decides which cells can clear it.

---

## 2. Data provenance (BUILD step 1)

All data came from Kalshi's public, unauthenticated API. No aggregator, mirror or
scraped source was used at any point. The client identified itself as
`kalshi-research/0.1 (experiment-008 calibration measurement; contact ...)` and paced
itself to **4 requests/second**, a rate measured safe on 2026-08-21 (60/60 HTTP 200 at
4 req/s; 19/60 HTTP 429 at 8 req/s).

| purpose | endpoint |
|---|---|
| series | `https://api.elections.kalshi.com/trade-api/v2/series` |
| archive_markets | `https://api.elections.kalshi.com/trade-api/v2/historical/markets?mve_filter=exclude` |
| live_markets | `https://api.elections.kalshi.com/trade-api/v2/markets?status=settled&mve_filter=exclude&min_close_ts&max_close_ts` |
| archive_candles | `https://api.elections.kalshi.com/trade-api/v2/historical/markets/{ticker}/candlesticks` |
| live_candles | `https://api.elections.kalshi.com/trade-api/v2/series/{series}/markets/{ticker}/candlesticks` |
| cutoff | `https://api.elections.kalshi.com/trade-api/v2/historical/cutoff` |

**The two data tiers.** `/historical/cutoff` reports `market_settled_ts = 2026-06-22T00:00:00Z`.
Markets settled after it are served by the live candlestick endpoint; markets settled
before it by the historical one. The two use **different field names for identical
data** (`price.close_dollars` vs `price.close`, `volume_fp` vs `volume`) and the
historical tier writes explicit JSON nulls where the live tier omits keys. Both are
folded into one shape by `ingest.normalise_candle()`. The tiers overlap for markets
settled 2026-06-15..2026-06-22, so markets are deduplicated on ticker.

**Realised close_time range:** `['2021-07-01T23:00:00Z', '2026-11-03T15:00:00Z']`  
**Realised settlement-date range** (what §2 asks for): `['2021-07-03T15:39:00Z', '2026-08-21T17:20:47Z']`

| census figure | value |
|---|---|
| markets in census (non-combo, settled) | 13,614,599 |
| with a definitive YES/NO outcome | 13,584,898 |
| pooled YES rate (definitive) | 0.320405 |
| rows by endpoint tier | {'archive': 10224262, 'live': 3390337} |

**Exclusions by reason (§2 requires these counted):**

| reason | count |
|---|---|
| duplicate_across_tiers | 410,372 |
| series_not_in_series_index | 10,293 |
| non-definitive outcome, `result = 'scalar'` | 29,701 |

**Markets per §4 category (definitive outcomes, full census):**

| category | markets |
|---|---|
| Weather | 202,419 |
| Economics | 24,491 |
| Politics | 83,429 |
| Sports | 1,771,134 |
| Financial | 11,234,391 |
| Other | 269,034 |

Kalshi's own categories seen: 17. Not covered by the frozen map (would silently fall to Other): none.

### Universe realisation — DECLARED DEVIATION FROM §2

§2 asks for *every* settled market. That is unreachable: ~1.74M settled non-combo
markets exist, each needs its own candlestick request, and at the measured 4 req/s
that is ~121 hours of continuous fetching against a free public endpoint. A date
window does not help — 87.5% of all markets closed in the last 12 months.

The **census above covers the full universe** (metadata only, no candlestick calls),
so §2's required reporting is computed on everything. Only the **price measurement**
is sampled, via an outcome-blind random draw over **events** — the §5 clustering unit.
The draw is a hash of `(seed, event_ticker)` alone, taken before any outcome was
joined, so it cannot select on outcome, price, liquidity or volume.

| sampling | value |
|---|---|
| seed | 20260821 |
| target events per category | 1200 |
| events available in census | 578,361 |
| events drawn | 1,391 |
| events drawn per category | {'Financial': 58, 'Politics': 211, 'Weather': 353, 'Other': 183, 'Economics': 253, 'Sports': 333} |
| markets in sampled events | 14,911 |
| snapshots produced | 14,854 |

---

## 3. Gates

Every gate below was **executed**, not asserted.

### Step 2 — settlement join

- **PASS** — every analysed market has a definitive YES/NO outcome (0 violations out of 8,227).
- Non-definitive markets excluded and counted: `{'scalar': 49}` (total 49).

The join key was cross-checked independently: `result` must agree with
`settlement_value_dollars / notional_value_dollars` on every market. These are two
separately populated fields, so disagreement would mean a bad join.

**Hand-check of 24 markets across 6 categories** — each re-fetched
individually from `GET /markets/{ticker}`, a different code path from the bulk
listing that built the census, and compared field by field.

Disagreements: **0**

| category | ticker | census result | re-fetched (tier) | event matches | close matches | agrees |
|---|---|---|---|---|---|---|
| Weather | `CO2-22APR-C390` | no | no (archive) | yes | yes | yes |
| Weather | `KXHIGHCHI-25AUG22-B81.5` | yes | yes (archive) | yes | yes | yes |
| Weather | `KXHIGHPHIL-24DEC06-B34.5` | no | no (archive) | yes | yes | yes |
| Weather | `KXLOWTCHI-26JAN20-B0.5` | no | no (archive) | yes | yes | yes |
| Economics | `AAAGASD-23OCT06-US-3.768` | no | no (archive) | yes | yes | yes |
| Economics | `KXAAAGASD-26JUL13-3.870` | yes | yes (live) | yes | yes | yes |
| Economics | `KXCHGDPYOY-26JUL15-T3.6` | yes | yes (live) | yes | yes | yes |
| Economics | `KXPAYROLLS-26JUL-T70000` | no | no (live) | yes | yes | yes |
| Politics | `538APPROVE-22NOV02-B40.9` | no | no (archive) | yes | yes | yes |
| Politics | `KXHEARINGMENTION-26APR20-BIDE` | yes | yes (archive) | yes | yes | yes |
| Politics | `KXNBAMENTION-26MAR31NYKHOU-OVER` | yes | yes (archive) | yes | yes | yes |
| Politics | `KXTRUMPMENTION-25AUG08-ENERG` | yes | yes (archive) | yes | yes | yes |
| Sports | `KXAFCCLGAME-26APR20VIKAAS-AAS` | yes | yes (archive) | yes | yes | yes |
| Sports | `KXMLBHR-26APR171845TBPIT-TBYDIAZ2-1` | no | no (archive) | yes | yes | yes |
| Sports | `KXMLBTB-26JUN192040PITCOL-COLHGOODMAN15-3` | no | no (live) | yes | yes | yes |
| Sports | `KXNFL2QSPREAD-26AUG06CARARI-CAR3` | no | no (live) | yes | yes | yes |
| Financial | `EUROIMF-15JUL22-T0.990` | yes | yes (archive) | yes | yes | yes |
| Financial | `KXINX-26JAN07H1600-B6862` | no | no (archive) | yes | yes | yes |
| Financial | `KXNASDAQ100-25JUN10H1600-B21450` | no | no (archive) | yes | yes | yes |
| Financial | `KXXRPD-26AUG1217-T0.9599` | yes | yes (live) | yes | yes | yes |
| Other | `CASED-21OCT08-T95` | yes | yes (archive) | yes | yes | yes |
| Other | `KXGOLDD-26MAY0717-T4843` | no | no (archive) | yes | yes | yes |
| Other | `KXNETFLIXRANKMOVIEGLOBAL-26JAN26-PEO` | no | no (archive) | yes | yes | yes |
| Other | `KXSNLHOST-26-MILL` | no | no (archive) | yes | yes | yes |

### Step 3 — horizon timestamps

The gate: *every price used at horizon H is timestamped strictly before settlement
minus H*. Checked on **every** snapshot, not a sample.

- **PASS** — 0 violations out of 14,854 snapshots.
- Smallest margin observed between the source candle and `settlement_ts − H`: **65 s**.

Two independent conservatisms make this hard to fail by accident:

1. T is `close_time`, and `close_time ≤ settlement_ts` on every market, so a price
   before `close_time − H` is necessarily before `settlement_ts − H`.
2. The snapshot is the latest candle whose `end_period_ts ≤ T − H`, and
   `end_period_ts` is the **inclusive end** of its interval — verified by matching
   trades to candles (a trade 32 ms before a minute boundary lands in the candle whose
   `end_period_ts` is the ceiling).

`include_latest_before_start` was deliberately **not** used: it returns a candle
stamped at the requested instant rather than at the real source candle's timestamp,
which would defeat this gate, and it is unavailable on the historical tier anyway.
The same widen-the-window rule is used on both tiers so the eras are treated alike.

Unit tests covering this gate, including a **market that settled early** and a market
whose settlement lags close by three days, are in `tests/test_horizons.py`.

### Step 4 — event clustering

The build spec words this gate as *"assert exactly one resolves YES"*. **Exactly
one is the wrong invariant** and asserting it fails on correct data. Kalshi's own
documentation defines the flag as *"only one market in this event **can** resolve
to 'yes'"* — mutual exclusivity, i.e. **at most one**. It promises nothing about
exhaustiveness, and Kalshi's exclusive events frequently are not exhaustive:

| event | markets | outcome | why all-NO is correct |
|---|---|---|---|
| `KXWTI-25MAY15` | 15 | all NO | WTI settled outside every listed strike band |
| `KXAPPRANKFREE2-25SEP14` | 5 | all NO | a sixth app was #1 that day |

Both were re-fetched from the API and both market lists are **complete**, so all-NO
is the true outcome, not a missing market. The gate therefore asserts **at most one
YES**, which is what mutual exclusivity means and what a wrong grouping would break:
if markets from two different real events were merged, two YES resolutions would
appear in one event.

- **PASS** — **0** events with two or more YES, out of **581** exclusive events checked.
- YES-count distribution: `{'0': 55, '1': 526}`
- All-NO exclusive events (descriptive, not failures): **56**
- Skipped, not flagged exclusive: 803
- Skipped, partially voided by a `scalar` market: 6

Applied only to events Kalshi itself flags exclusive: **41% of events are not**
exclusive (a top-2-advance primary legitimately resolves two markets YES), and
asserting exclusivity on those would be asserting something false.

### Markets per event, and the effective sample size (§5)

| statistic | value |
|---|---|
| markets | 14,911 |
| distinct events | 1,391 |
| markets per event mean | 10.72 |
| markets per event median | 6 |
| markets per event max | 400 |
| effective n ratio | 0.0933 |

| markets per event | events |
|---|---|
| 1 | 235 |
| 2 | 206 |
| 3-5 | 151 |
| 6-10 | 387 |
| 11-50 | 374 |
| >50 | 38 |

§9 predicted the effective N would be *much* smaller than the market count. It is:
the ratio of distinct events to markets is **0.0933**.

---

## 4. Calibration tables — all 180 cells (BUILD step 5)

10 buckets × 6 categories × 3 horizons. Every cell is listed, including empty ones.
`diff (c)` is `realized frequency − mean implied price`, in cents of price: negative
means the market **overpriced** YES. `SE clust` is clustered at the event level and
**governs** per §5; `SE naive` is shown only for contrast.

- populated cells: **154** of 180
- empty cells: **26**

| horizon | category | bucket | n mkts | n events | mean implied | realized | diff (c) | SE naive | SE binom | SE binom-clu | SE CR0 | SE CR1 | SE gov | t naive | t clust | t unguarded | fee floor (c) | > floor | t>3.5 | t>2.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T-7d | Weather | [0,10) | 8 | 4 | 0.0219 | 0.0000 | -2.188 | 0.0087 | 0.0511 | 0.0691 | 0.0087 | 0.0100 | 0.0691 | -2.527 | -0.316 | -2.190 | 0.1498 | yes | no | no |
| T-7d | Weather | [10,20) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-7d | Weather | [20,30) | 1 | 1 | 0.2550 | 0.0000 | -25.500 | - | 0.4359 | 0.4359 | 0.0000 | - | - | - | - | - | 1.3298 | yes | no | no |
| T-7d | Weather | [30,40) | 1 | 1 | 0.3000 | 0.0000 | -30.000 | - | 0.4583 | 0.4583 | 0.0000 | - | - | - | - | - | 1.4700 | yes | no | no |
| T-7d | Weather | [40,50) | 1 | 1 | 0.4750 | 0.0000 | -47.500 | - | 0.4994 | 0.4994 | 0.0000 | - | - | - | - | - | 1.7456 | yes | no | no |
| T-7d | Weather | [50,60) | 1 | 1 | 0.5200 | 0.0000 | -52.000 | - | 0.4996 | 0.4996 | 0.0000 | - | - | - | - | - | 1.7472 | yes | no | no |
| T-7d | Weather | [60,70) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-7d | Weather | [70,80) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.3125 | - | - | - |
| T-7d | Weather | [80,90) | 1 | 1 | 0.8200 | 1.0000 | 18.000 | - | 0.3842 | 0.3842 | 0.0000 | - | - | - | - | - | 1.0332 | yes | no | no |
| T-7d | Weather | [90,100] | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.3325 | - | - | - |
| T-7d | Economics | [0,10) | 316 | 86 | 0.0280 | 0.0032 | -2.484 | 0.0033 | 0.0092 | 0.0207 | 0.0038 | 0.0038 | 0.0207 | -7.473 | -1.201 | -6.585 | 0.1906 | yes | no | no |
| T-7d | Economics | [10,20) | 59 | 51 | 0.1403 | 0.0847 | -5.551 | 0.0362 | 0.0451 | 0.0511 | 0.0423 | 0.0427 | 0.0511 | -1.532 | -1.086 | -1.300 | 0.8441 | yes | no | no |
| T-7d | Economics | [20,30) | 49 | 44 | 0.2469 | 0.1224 | -12.449 | 0.0470 | 0.0615 | 0.0674 | 0.0460 | 0.0465 | 0.0674 | -2.646 | -1.846 | -2.678 | 1.3017 | yes | no | no |
| T-7d | Economics | [30,40) | 36 | 31 | 0.3436 | 0.3889 | 4.528 | 0.0828 | 0.0790 | 0.0894 | 0.0855 | 0.0869 | 0.0894 | 0.547 | 0.507 | 0.521 | 1.5788 | yes | no | no |
| T-7d | Economics | [40,50) | 52 | 32 | 0.4662 | 0.2308 | -23.548 | 0.0593 | 0.0691 | 0.1076 | 0.0735 | 0.0747 | 0.1076 | -3.971 | -2.188 | -3.153 | 1.7420 | yes | no | yes |
| T-7d | Economics | [50,60) | 45 | 37 | 0.5404 | 0.5333 | -0.711 | 0.0749 | 0.0742 | 0.0892 | 0.0705 | 0.0715 | 0.0892 | -0.095 | -0.080 | -0.100 | 1.7385 | no | no | no |
| T-7d | Economics | [60,70) | 31 | 29 | 0.6510 | 0.4839 | -16.710 | 0.0900 | 0.0855 | 0.0908 | 0.0943 | 0.0960 | 0.0960 | -1.857 | -1.740 | -1.740 | 1.5905 | yes | no | no |
| T-7d | Economics | [70,80) | 25 | 24 | 0.7598 | 0.7600 | 0.020 | 0.0875 | 0.0852 | 0.0885 | 0.0867 | 0.0886 | 0.0886 | 0.002 | 0.002 | 0.002 | 1.2775 | no | no | no |
| T-7d | Economics | [80,90) | 56 | 49 | 0.8504 | 0.7857 | -6.473 | 0.0564 | 0.0475 | 0.0549 | 0.0750 | 0.0758 | 0.0758 | -1.149 | -0.854 | -0.854 | 0.8903 | yes | no | no |
| T-7d | Economics | [90,100] | 196 | 76 | 0.9658 | 0.9796 | 1.383 | 0.0101 | 0.0128 | 0.0234 | 0.0103 | 0.0104 | 0.0234 | 1.371 | 0.592 | 1.329 | 0.2314 | yes | no | no |
| T-7d | Politics | [0,10) | 194 | 62 | 0.0267 | 0.0567 | 3.001 | 0.0161 | 0.0114 | 0.0253 | 0.0349 | 0.0352 | 0.0352 | 1.866 | 0.853 | 0.853 | 0.1819 | yes | no | no |
| T-7d | Politics | [10,20) | 44 | 27 | 0.1461 | 0.2045 | 5.842 | 0.0606 | 0.0530 | 0.0804 | 0.0834 | 0.0850 | 0.0850 | 0.964 | 0.687 | 0.687 | 0.8734 | yes | no | no |
| T-7d | Politics | [20,30) | 36 | 21 | 0.2526 | 0.2778 | 2.514 | 0.0753 | 0.0723 | 0.1102 | 0.0921 | 0.0943 | 0.1102 | 0.334 | 0.228 | 0.266 | 1.3217 | yes | no | no |
| T-7d | Politics | [30,40) | 23 | 16 | 0.3424 | 0.2174 | -12.500 | 0.0888 | 0.0988 | 0.1380 | 0.0997 | 0.1029 | 0.1380 | -1.408 | -0.906 | -1.215 | 1.5761 | yes | no | no |
| T-7d | Politics | [40,50) | 26 | 17 | 0.4533 | 0.3846 | -6.865 | 0.0970 | 0.0974 | 0.1378 | 0.0999 | 0.1030 | 0.1378 | -0.708 | -0.498 | -0.667 | 1.7347 | yes | no | no |
| T-7d | Politics | [50,60) | 24 | 13 | 0.5373 | 0.5000 | -3.729 | 0.1052 | 0.1016 | 0.1579 | 0.1063 | 0.1106 | 0.1579 | -0.355 | -0.236 | -0.337 | 1.7403 | yes | no | no |
| T-7d | Politics | [60,70) | 25 | 17 | 0.6448 | 0.8400 | 19.520 | 0.0753 | 0.0955 | 0.1332 | 0.0759 | 0.0783 | 0.1332 | 2.593 | 1.466 | 2.494 | 1.6032 | yes | no | no |
| T-7d | Politics | [70,80) | 28 | 14 | 0.7529 | 0.6786 | -7.429 | 0.0908 | 0.0813 | 0.1342 | 0.0666 | 0.0692 | 0.1342 | -0.818 | -0.554 | -1.074 | 1.3024 | yes | no | no |
| T-7d | Politics | [80,90) | 27 | 14 | 0.8493 | 1.0000 | 15.074 | 0.0053 | 0.0687 | 0.1246 | 0.0050 | 0.0052 | 0.1246 | 28.502 | 1.209 | 29.055 | 0.8961 | yes | no | no |
| T-7d | Politics | [90,100] | 34 | 34 | 0.9680 | 1.0000 | 3.200 | 0.0051 | 0.0298 | 0.0298 | 0.0051 | 0.0051 | 0.0298 | 6.225 | 1.075 | 6.225 | 0.2168 | yes | no | no |
| T-7d | Sports | [0,10) | 13 | 2 | 0.0096 | 0.0000 | -0.962 | 0.0046 | 0.0267 | 0.0678 | 0.0060 | 0.0085 | 0.0678 | -2.083 | -0.142 | -1.128 | 0.0667 | yes | no | no |
| T-7d | Sports | [10,20) | 2 | 2 | 0.1700 | 0.5000 | 33.000 | 0.5250 | 0.2650 | 0.2650 | 0.3712 | 0.5250 | 0.5250 | 0.629 | 0.629 | 0.629 | 0.9877 | yes | no | no |
| T-7d | Sports | [20,30) | 37 | 8 | 0.2326 | 0.0541 | -17.851 | 0.0384 | 0.0694 | 0.3426 | 0.0306 | 0.0327 | 0.3426 | -4.654 | -0.521 | -5.462 | 1.2494 | yes | no | no |
| T-7d | Sports | [30,40) | 2 | 2 | 0.3800 | 0.0000 | -38.000 | 0.0050 | 0.3432 | 0.3432 | 0.0035 | 0.0050 | 0.3432 | -76.000 | -1.107 | -76.000 | 1.6492 | yes | no | no |
| T-7d | Sports | [40,50) | 5 | 5 | 0.4480 | 0.6000 | 15.200 | 0.2532 | 0.2220 | 0.2220 | 0.2265 | 0.2532 | 0.2532 | 0.600 | 0.600 | 0.600 | 1.7311 | yes | no | no |
| T-7d | Sports | [50,60) | 2 | 2 | 0.5475 | 1.0000 | 45.250 | 0.0325 | 0.3512 | 0.3512 | 0.0230 | 0.0325 | 0.3512 | 13.923 | 1.288 | 13.923 | 1.7342 | yes | no | no |
| T-7d | Sports | [60,70) | 5 | 5 | 0.6210 | 0.4000 | -22.100 | 0.2444 | 0.2169 | 0.2169 | 0.2186 | 0.2444 | 0.2444 | -0.904 | -0.904 | -0.904 | 1.6475 | yes | no | no |
| T-7d | Sports | [70,80) | 1 | 1 | 0.7650 | 1.0000 | 23.500 | - | 0.4240 | 0.4240 | 0.0000 | - | - | - | - | - | 1.2584 | yes | no | no |
| T-7d | Sports | [80,90) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-7d | Sports | [90,100] | 2 | 1 | 0.9950 | 1.0000 | 0.500 | 0.0000 | 0.0499 | 0.0705 | 0.0000 | - | - | - | - | - | 0.0348 | yes | no | no |
| T-7d | Financial | [0,10) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.3325 | - | - | - |
| T-7d | Financial | [10,20) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-7d | Financial | [20,30) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.3125 | - | - | - |
| T-7d | Financial | [30,40) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-7d | Financial | [40,50) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.7325 | - | - | - |
| T-7d | Financial | [50,60) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.7325 | - | - | - |
| T-7d | Financial | [60,70) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-7d | Financial | [70,80) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.3125 | - | - | - |
| T-7d | Financial | [80,90) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-7d | Financial | [90,100] | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.3325 | - | - | - |
| T-7d | Other | [0,10) | 224 | 28 | 0.0149 | 0.0089 | -0.594 | 0.0060 | 0.0080 | 0.0345 | 0.0059 | 0.0060 | 0.0345 | -0.991 | -0.172 | -0.984 | 0.1025 | yes | no | no |
| T-7d | Other | [10,20) | 10 | 8 | 0.1300 | 0.0000 | -13.000 | 0.0099 | 0.1059 | 0.1245 | 0.0077 | 0.0082 | 0.1245 | -13.073 | -1.044 | -15.831 | 0.7917 | yes | no | no |
| T-7d | Other | [20,30) | 10 | 6 | 0.2305 | 0.2000 | -3.050 | 0.1374 | 0.1329 | 0.1871 | 0.0909 | 0.0996 | 0.1871 | -0.222 | -0.163 | -0.306 | 1.2416 | yes | no | no |
| T-7d | Other | [30,40) | 4 | 4 | 0.3500 | 0.5000 | 15.000 | 0.2816 | 0.2383 | 0.2383 | 0.2438 | 0.2816 | 0.2816 | 0.533 | 0.533 | 0.533 | 1.5925 | yes | no | no |
| T-7d | Other | [40,50) | 20 | 8 | 0.4725 | 0.1000 | -37.250 | 0.0697 | 0.1116 | 0.2711 | 0.0770 | 0.0824 | 0.2711 | -5.343 | -1.374 | -4.523 | 1.7447 | yes | no | no |
| T-7d | Other | [50,60) | 5 | 3 | 0.5180 | 0.6000 | 8.200 | 0.2378 | 0.2232 | 0.2997 | 0.2921 | 0.3577 | 0.3577 | 0.345 | 0.229 | 0.229 | 1.7477 | yes | no | no |
| T-7d | Other | [60,70) | 7 | 7 | 0.6614 | 0.8571 | 19.571 | 0.1413 | 0.1786 | 0.1786 | 0.1308 | 0.1413 | 0.1786 | 1.385 | 1.096 | 1.385 | 1.5676 | yes | no | no |
| T-7d | Other | [70,80) | 8 | 7 | 0.7600 | 0.7500 | -1.000 | 0.1661 | 0.1507 | 0.1699 | 0.1631 | 0.1761 | 0.1761 | -0.060 | -0.057 | -0.057 | 1.2768 | no | no | no |
| T-7d | Other | [80,90) | 7 | 5 | 0.8614 | 1.0000 | 13.857 | 0.0114 | 0.1302 | 0.1832 | 0.0128 | 0.0143 | 0.1832 | 12.181 | 0.756 | 9.701 | 0.8356 | yes | no | no |
| T-7d | Other | [90,100] | 28 | 13 | 0.9602 | 1.0000 | 3.982 | 0.0051 | 0.0366 | 0.0710 | 0.0076 | 0.0079 | 0.0710 | 7.738 | 0.561 | 5.012 | 0.2676 | yes | no | no |
| T-24h | Weather | [0,10) | 413 | 161 | 0.0355 | 0.0291 | -0.648 | 0.0082 | 0.0090 | 0.0145 | 0.0081 | 0.0081 | 0.0145 | -0.793 | -0.445 | -0.798 | 0.2399 | yes | no | no |
| T-24h | Weather | [10,20) | 175 | 131 | 0.1433 | 0.1086 | -3.471 | 0.0236 | 0.0264 | 0.0334 | 0.0229 | 0.0230 | 0.0334 | -1.470 | -1.038 | -1.511 | 0.8593 | yes | no | no |
| T-24h | Weather | [20,30) | 144 | 107 | 0.2485 | 0.1806 | -6.799 | 0.0322 | 0.0359 | 0.0453 | 0.0296 | 0.0298 | 0.0453 | -2.112 | -1.501 | -2.284 | 1.3074 | yes | no | no |
| T-24h | Weather | [30,40) | 125 | 99 | 0.3457 | 0.3920 | 4.632 | 0.0436 | 0.0425 | 0.0517 | 0.0380 | 0.0382 | 0.0517 | 1.063 | 0.897 | 1.214 | 1.5833 | yes | no | no |
| T-24h | Weather | [40,50) | 82 | 74 | 0.4409 | 0.4756 | 3.476 | 0.0561 | 0.0547 | 0.0604 | 0.0545 | 0.0549 | 0.0604 | 0.620 | 0.575 | 0.633 | 1.7255 | yes | no | no |
| T-24h | Weather | [50,60) | 35 | 35 | 0.5389 | 0.5429 | 0.400 | 0.0849 | 0.0842 | 0.0842 | 0.0837 | 0.0849 | 0.0849 | 0.047 | 0.047 | 0.047 | 1.7394 | no | no | no |
| T-24h | Weather | [60,70) | 14 | 14 | 0.6429 | 0.6429 | -0.000 | 0.1341 | 0.1279 | 0.1279 | 0.1292 | 0.1341 | 0.1341 | -0.000 | -0.000 | -0.000 | 1.6071 | no | no | no |
| T-24h | Weather | [70,80) | 9 | 9 | 0.7267 | 0.5556 | -17.111 | 0.1729 | 0.1484 | 0.1484 | 0.1630 | 0.1729 | 0.1729 | -0.990 | -0.990 | -0.990 | 1.3904 | yes | no | no |
| T-24h | Weather | [80,90) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-24h | Weather | [90,100] | 2 | 2 | 0.9200 | 1.0000 | 8.000 | 0.0050 | 0.1918 | 0.1918 | 0.0035 | 0.0050 | 0.1918 | 16.000 | 0.417 | 16.000 | 0.5152 | yes | no | no |
| T-24h | Economics | [0,10) | 470 | 127 | 0.0231 | 0.0064 | -1.674 | 0.0036 | 0.0069 | 0.0151 | 0.0038 | 0.0038 | 0.0151 | -4.634 | -1.109 | -4.381 | 0.1581 | yes | no | no |
| T-24h | Economics | [10,20) | 81 | 69 | 0.1498 | 0.0741 | -7.574 | 0.0286 | 0.0395 | 0.0468 | 0.0289 | 0.0291 | 0.0468 | -2.651 | -1.618 | -2.601 | 0.8916 | yes | no | no |
| T-24h | Economics | [20,30) | 64 | 44 | 0.2450 | 0.2344 | -1.062 | 0.0529 | 0.0537 | 0.0752 | 0.0607 | 0.0614 | 0.0752 | -0.201 | -0.141 | -0.173 | 1.2948 | no | no | no |
| T-24h | Economics | [30,40) | 48 | 42 | 0.3549 | 0.2500 | -10.490 | 0.0629 | 0.0689 | 0.0784 | 0.0618 | 0.0626 | 0.0784 | -1.667 | -1.338 | -1.677 | 1.6026 | yes | no | no |
| T-24h | Economics | [40,50) | 78 | 51 | 0.4650 | 0.3205 | -14.449 | 0.0531 | 0.0564 | 0.0895 | 0.0685 | 0.0692 | 0.0895 | -2.719 | -1.615 | -2.088 | 1.7414 | yes | no | no |
| T-24h | Economics | [50,60) | 76 | 47 | 0.5372 | 0.6053 | 6.803 | 0.0569 | 0.0571 | 0.1010 | 0.0866 | 0.0875 | 0.1010 | 1.195 | 0.673 | 0.777 | 1.7403 | yes | no | no |
| T-24h | Economics | [60,70) | 39 | 35 | 0.6440 | 0.6410 | -0.295 | 0.0776 | 0.0765 | 0.0841 | 0.0800 | 0.0811 | 0.0841 | -0.038 | -0.035 | -0.036 | 1.6049 | no | no | no |
| T-24h | Economics | [70,80) | 42 | 33 | 0.7554 | 0.8333 | 7.798 | 0.0583 | 0.0662 | 0.0791 | 0.0646 | 0.0656 | 0.0791 | 1.337 | 0.985 | 1.189 | 1.2935 | yes | no | no |
| T-24h | Economics | [80,90) | 83 | 59 | 0.8423 | 0.8313 | -1.102 | 0.0421 | 0.0399 | 0.0540 | 0.0509 | 0.0514 | 0.0540 | -0.262 | -0.204 | -0.215 | 0.9296 | yes | no | no |
| T-24h | Economics | [90,100] | 312 | 110 | 0.9718 | 0.9904 | 1.861 | 0.0056 | 0.0092 | 0.0178 | 0.0055 | 0.0055 | 0.0178 | 3.339 | 1.044 | 3.353 | 0.1920 | yes | no | no |
| T-24h | Politics | [0,10) | 345 | 107 | 0.0217 | 0.0116 | -1.007 | 0.0057 | 0.0077 | 0.0178 | 0.0059 | 0.0059 | 0.0178 | -1.768 | -0.565 | -1.702 | 0.1484 | yes | no | no |
| T-24h | Politics | [10,20) | 116 | 63 | 0.1537 | 0.0948 | -5.888 | 0.0268 | 0.0334 | 0.0533 | 0.0266 | 0.0268 | 0.0533 | -2.200 | -1.105 | -2.197 | 0.9106 | yes | no | no |
| T-24h | Politics | [20,30) | 116 | 55 | 0.2513 | 0.2500 | -0.134 | 0.0404 | 0.0402 | 0.0672 | 0.0403 | 0.0407 | 0.0672 | -0.033 | -0.020 | -0.033 | 1.3172 | no | no | no |
| T-24h | Politics | [30,40) | 127 | 66 | 0.3468 | 0.2913 | -5.547 | 0.0402 | 0.0422 | 0.0674 | 0.0374 | 0.0377 | 0.0674 | -1.380 | -0.823 | -1.472 | 1.5857 | yes | no | no |
| T-24h | Politics | [40,50) | 94 | 52 | 0.4457 | 0.3830 | -6.271 | 0.0493 | 0.0512 | 0.0800 | 0.0540 | 0.0545 | 0.0800 | -1.271 | -0.784 | -1.151 | 1.7294 | yes | no | no |
| T-24h | Politics | [50,60) | 109 | 63 | 0.5455 | 0.4220 | -12.344 | 0.0473 | 0.0476 | 0.0714 | 0.0465 | 0.0468 | 0.0714 | -2.611 | -1.729 | -2.635 | 1.7355 | yes | no | no |
| T-24h | Politics | [60,70) | 119 | 55 | 0.6479 | 0.7059 | 5.798 | 0.0415 | 0.0437 | 0.0762 | 0.0390 | 0.0393 | 0.0762 | 1.398 | 0.761 | 1.474 | 1.5969 | yes | no | no |
| T-24h | Politics | [70,80) | 137 | 61 | 0.7467 | 0.7372 | -0.945 | 0.0374 | 0.0371 | 0.0659 | 0.0399 | 0.0402 | 0.0659 | -0.253 | -0.143 | -0.235 | 1.3240 | no | no | no |
| T-24h | Politics | [80,90) | 142 | 60 | 0.8508 | 0.8521 | 0.134 | 0.0296 | 0.0298 | 0.0533 | 0.0312 | 0.0315 | 0.0533 | 0.045 | 0.025 | 0.043 | 0.8887 | no | no | no |
| T-24h | Politics | [90,100] | 167 | 87 | 0.9617 | 0.9701 | 0.837 | 0.0130 | 0.0147 | 0.0252 | 0.0133 | 0.0133 | 0.0252 | 0.644 | 0.332 | 0.628 | 0.2579 | yes | no | no |
| T-24h | Sports | [0,10) | 260 | 32 | 0.0191 | 0.0115 | -0.754 | 0.0065 | 0.0084 | 0.0430 | 0.0045 | 0.0046 | 0.0430 | -1.164 | -0.176 | -1.654 | 0.1305 | yes | no | no |
| T-24h | Sports | [10,20) | 29 | 24 | 0.1459 | 0.1379 | -0.793 | 0.0642 | 0.0654 | 0.0759 | 0.0615 | 0.0628 | 0.0759 | -0.124 | -0.104 | -0.126 | 0.8571 | no | no | no |
| T-24h | Sports | [20,30) | 25 | 23 | 0.2568 | 0.2800 | 2.320 | 0.0909 | 0.0872 | 0.0943 | 0.0873 | 0.0892 | 0.0943 | 0.255 | 0.246 | 0.260 | 1.3093 | yes | no | no |
| T-24h | Sports | [30,40) | 28 | 25 | 0.3514 | 0.1786 | -17.286 | 0.0725 | 0.0901 | 0.1023 | 0.0629 | 0.0642 | 0.1023 | -2.385 | -1.690 | -2.694 | 1.4815 | yes | no | no |
| T-24h | Sports | [40,50) | 60 | 47 | 0.4536 | 0.3333 | -12.025 | 0.0614 | 0.0642 | 0.0892 | 0.0707 | 0.0715 | 0.0892 | -1.958 | -1.348 | -1.682 | 1.6048 | yes | no | no |
| T-24h | Sports | [50,60) | 39 | 38 | 0.5453 | 0.5897 | 4.449 | 0.0798 | 0.0796 | 0.0816 | 0.0818 | 0.0829 | 0.0829 | 0.557 | 0.536 | 0.536 | 1.5799 | yes | no | no |
| T-24h | Sports | [60,70) | 25 | 25 | 0.6446 | 0.6800 | 3.540 | 0.0945 | 0.0956 | 0.0956 | 0.0926 | 0.0945 | 0.0956 | 0.375 | 0.370 | 0.375 | 1.5395 | yes | no | no |
| T-24h | Sports | [70,80) | 17 | 17 | 0.7397 | 0.7647 | 2.500 | 0.1060 | 0.1062 | 0.1062 | 0.1028 | 0.1060 | 0.1062 | 0.236 | 0.235 | 0.236 | 1.3081 | yes | no | no |
| T-24h | Sports | [80,90) | 8 | 8 | 0.8712 | 1.0000 | 12.875 | 0.0091 | 0.1181 | 0.1181 | 0.0086 | 0.0091 | 0.1181 | 14.072 | 1.090 | 14.072 | 0.7361 | yes | no | no |
| T-24h | Sports | [90,100] | 23 | 12 | 0.9541 | 0.9565 | 0.239 | 0.0452 | 0.0433 | 0.0878 | 0.0287 | 0.0299 | 0.0878 | 0.053 | 0.027 | 0.080 | 0.2930 | no | no | no |
| T-24h | Financial | [0,10) | 3 | 1 | 0.0300 | 0.0000 | -3.000 | 0.0058 | 0.0984 | 0.1688 | 0.0000 | - | - | -5.196 | - | - | 0.2037 | yes | no | no |
| T-24h | Financial | [10,20) | 1 | 1 | 0.1350 | 0.0000 | -13.500 | - | 0.3417 | 0.3417 | 0.0000 | - | - | - | - | - | 0.8174 | yes | no | no |
| T-24h | Financial | [20,30) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.3125 | - | - | - |
| T-24h | Financial | [30,40) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-24h | Financial | [40,50) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.7325 | - | - | - |
| T-24h | Financial | [50,60) | 1 | 1 | 0.5350 | 1.0000 | 46.500 | - | 0.4988 | 0.4988 | 0.0000 | - | - | - | - | - | 1.7414 | yes | no | no |
| T-24h | Financial | [60,70) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-24h | Financial | [70,80) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.3125 | - | - | - |
| T-24h | Financial | [80,90) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.8925 | - | - | - |
| T-24h | Financial | [90,100] | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 0.3325 | - | - | - |
| T-24h | Other | [0,10) | 393 | 60 | 0.0177 | 0.0076 | -1.005 | 0.0044 | 0.0066 | 0.0215 | 0.0048 | 0.0048 | 0.0215 | -2.305 | -0.467 | -2.082 | 0.1216 | yes | no | no |
| T-24h | Other | [10,20) | 32 | 20 | 0.1480 | 0.1562 | 0.828 | 0.0632 | 0.0625 | 0.0887 | 0.0713 | 0.0732 | 0.0887 | 0.131 | 0.093 | 0.113 | 0.8825 | no | no | no |
| T-24h | Other | [20,30) | 24 | 14 | 0.2419 | 0.0833 | -15.854 | 0.0591 | 0.0872 | 0.1306 | 0.0531 | 0.0552 | 0.1306 | -2.682 | -1.214 | -2.875 | 1.2836 | yes | no | no |
| T-24h | Other | [30,40) | 17 | 12 | 0.3468 | 0.1765 | -17.029 | 0.0940 | 0.1151 | 0.1551 | 0.0984 | 0.1028 | 0.1551 | -1.812 | -1.098 | -1.657 | 1.5856 | yes | no | no |
| T-24h | Other | [40,50) | 49 | 19 | 0.4663 | 0.0612 | -40.510 | 0.0348 | 0.0712 | 0.1762 | 0.0422 | 0.0433 | 0.1762 | -11.654 | -2.300 | -9.348 | 1.7421 | yes | no | yes |
| T-24h | Other | [50,60) | 11 | 8 | 0.5368 | 0.5455 | 0.864 | 0.1574 | 0.1502 | 0.1973 | 0.1943 | 0.2077 | 0.2077 | 0.055 | 0.042 | 0.042 | 1.7405 | no | no | no |
| T-24h | Other | [60,70) | 16 | 9 | 0.6494 | 0.8125 | 16.313 | 0.0996 | 0.1191 | 0.1932 | 0.0880 | 0.0933 | 0.1932 | 1.637 | 0.844 | 1.748 | 1.5938 | yes | no | no |
| T-24h | Other | [70,80) | 18 | 11 | 0.7522 | 0.9444 | 19.222 | 0.0584 | 0.1015 | 0.1596 | 0.0593 | 0.0622 | 0.1596 | 3.290 | 1.205 | 3.090 | 1.3047 | yes | no | no |
| T-24h | Other | [80,90) | 33 | 10 | 0.8558 | 0.9697 | 11.394 | 0.0304 | 0.0609 | 0.1716 | 0.0302 | 0.0318 | 0.1716 | 3.746 | 0.664 | 3.580 | 0.8641 | yes | no | no |
| T-24h | Other | [90,100] | 104 | 36 | 0.9716 | 0.9808 | 0.918 | 0.0130 | 0.0161 | 0.0380 | 0.0139 | 0.0141 | 0.0380 | 0.708 | 0.241 | 0.651 | 0.1932 | yes | no | no |
| T-1h | Weather | [0,10) | 844 | 191 | 0.0071 | 0.0000 | -0.714 | 0.0003 | 0.0029 | 0.0059 | 0.0004 | 0.0004 | 0.0059 | -22.345 | -1.204 | -18.842 | 0.0496 | yes | no | no |
| T-1h | Weather | [10,20) | 10 | 10 | 0.1270 | 0.0000 | -12.700 | 0.0093 | 0.1049 | 0.1049 | 0.0088 | 0.0093 | 0.1049 | -13.677 | -1.210 | -13.677 | 0.7761 | yes | no | no |
| T-1h | Weather | [20,30) | 3 | 3 | 0.2317 | 0.0000 | -23.167 | 0.0159 | 0.2432 | 0.2432 | 0.0130 | 0.0159 | 0.2432 | -14.571 | -0.952 | -14.571 | 1.2460 | yes | no | no |
| T-1h | Weather | [30,40) | 4 | 4 | 0.3337 | 0.0000 | -33.375 | 0.0174 | 0.2353 | 0.2353 | 0.0150 | 0.0174 | 0.2353 | -19.219 | -1.418 | -19.219 | 1.5565 | yes | no | no |
| T-1h | Weather | [40,50) | 11 | 8 | 0.4655 | 0.1818 | -28.364 | 0.1238 | 0.1502 | 0.1973 | 0.0870 | 0.0930 | 0.1973 | -2.292 | -1.438 | -3.051 | 1.7416 | yes | no | no |
| T-1h | Weather | [50,60) | 3 | 3 | 0.5367 | 0.6667 | 13.000 | 0.3284 | 0.2872 | 0.2872 | 0.2682 | 0.3284 | 0.3284 | 0.396 | 0.396 | 0.396 | 1.7406 | yes | no | no |
| T-1h | Weather | [60,70) | 1 | 1 | 0.6000 | 1.0000 | 40.000 | - | 0.4899 | 0.4899 | 0.0000 | - | - | - | - | - | 1.6800 | yes | no | no |
| T-1h | Weather | [70,80) | 4 | 4 | 0.7537 | 1.0000 | 24.625 | 0.0024 | 0.2154 | 0.2154 | 0.0021 | 0.0024 | 0.2154 | 102.880 | 1.143 | 102.880 | 1.2993 | yes | no | no |
| T-1h | Weather | [80,90) | 7 | 7 | 0.8443 | 1.0000 | 15.571 | 0.0086 | 0.1368 | 0.1368 | 0.0079 | 0.0086 | 0.1368 | 18.209 | 1.138 | 18.209 | 0.9203 | yes | no | no |
| T-1h | Weather | [90,100] | 171 | 170 | 0.9897 | 1.0000 | 1.026 | 0.0010 | 0.0076 | 0.0077 | 0.0010 | 0.0010 | 0.0077 | 10.300 | 1.339 | 10.290 | 0.0711 | yes | no | no |
| T-1h | Economics | [0,10) | 700 | 166 | 0.0222 | 0.0029 | -1.931 | 0.0021 | 0.0055 | 0.0128 | 0.0024 | 0.0024 | 0.0128 | -9.104 | -1.514 | -7.984 | 0.1518 | yes | no | no |
| T-1h | Economics | [10,20) | 102 | 80 | 0.1385 | 0.0392 | -9.926 | 0.0189 | 0.0341 | 0.0429 | 0.0221 | 0.0223 | 0.0429 | -5.257 | -2.313 | -4.458 | 0.8351 | yes | no | yes |
| T-1h | Economics | [20,30) | 57 | 50 | 0.2475 | 0.1228 | -12.465 | 0.0440 | 0.0570 | 0.0662 | 0.0436 | 0.0440 | 0.0662 | -2.836 | -1.882 | -2.831 | 1.3036 | yes | no | no |
| T-1h | Economics | [30,40) | 68 | 54 | 0.3518 | 0.1765 | -17.537 | 0.0463 | 0.0578 | 0.0730 | 0.0484 | 0.0489 | 0.0730 | -3.785 | -2.401 | -3.586 | 1.5963 | yes | no | yes |
| T-1h | Economics | [40,50) | 81 | 50 | 0.4646 | 0.2963 | -16.827 | 0.0514 | 0.0553 | 0.0906 | 0.0743 | 0.0750 | 0.0906 | -3.275 | -1.857 | -2.243 | 1.7412 | yes | no | no |
| T-1h | Economics | [50,60) | 92 | 56 | 0.5326 | 0.6087 | 7.614 | 0.0515 | 0.0519 | 0.0863 | 0.0727 | 0.0734 | 0.0863 | 1.479 | 0.882 | 1.037 | 1.7426 | yes | no | no |
| T-1h | Economics | [60,70) | 45 | 38 | 0.6458 | 0.6444 | -0.133 | 0.0725 | 0.0712 | 0.0898 | 0.0773 | 0.0783 | 0.0898 | -0.018 | -0.015 | -0.017 | 1.6012 | no | no | no |
| T-1h | Economics | [70,80) | 59 | 53 | 0.7539 | 0.6780 | -7.593 | 0.0614 | 0.0560 | 0.0614 | 0.0653 | 0.0659 | 0.0659 | -1.238 | -1.153 | -1.153 | 1.2987 | yes | no | no |
| T-1h | Economics | [80,90) | 105 | 78 | 0.8471 | 0.9048 | 5.762 | 0.0293 | 0.0350 | 0.0478 | 0.0368 | 0.0370 | 0.0478 | 1.967 | 1.205 | 1.558 | 0.9064 | yes | no | no |
| T-1h | Economics | [90,100] | 619 | 153 | 0.9782 | 0.9855 | 0.722 | 0.0047 | 0.0058 | 0.0135 | 0.0065 | 0.0065 | 0.0135 | 1.531 | 0.535 | 1.109 | 0.1490 | yes | no | no |
| T-1h | Politics | [0,10) | 1,056 | 179 | 0.0115 | 0.0057 | -0.578 | 0.0023 | 0.0032 | 0.0092 | 0.0023 | 0.0024 | 0.0092 | -2.534 | -0.631 | -2.460 | 0.0793 | yes | no | no |
| T-1h | Politics | [10,20) | 97 | 39 | 0.1454 | 0.0722 | -7.320 | 0.0269 | 0.0357 | 0.0633 | 0.0230 | 0.0233 | 0.0633 | -2.721 | -1.156 | -3.140 | 0.8696 | yes | no | no |
| T-1h | Politics | [20,30) | 58 | 29 | 0.2409 | 0.1379 | -10.293 | 0.0462 | 0.0560 | 0.0907 | 0.0456 | 0.0464 | 0.0907 | -2.227 | -1.135 | -2.218 | 1.2799 | yes | no | no |
| T-1h | Politics | [30,40) | 58 | 30 | 0.3525 | 0.2414 | -11.112 | 0.0570 | 0.0626 | 0.1035 | 0.0699 | 0.0710 | 0.1035 | -1.950 | -1.074 | -1.564 | 1.5977 | yes | no | no |
| T-1h | Politics | [40,50) | 62 | 27 | 0.4508 | 0.2419 | -20.887 | 0.0548 | 0.0631 | 0.1172 | 0.0644 | 0.0657 | 0.1172 | -3.815 | -1.782 | -3.181 | 1.7331 | yes | no | no |
| T-1h | Politics | [50,60) | 28 | 20 | 0.5477 | 0.6786 | 13.089 | 0.0903 | 0.0940 | 0.1230 | 0.0894 | 0.0917 | 0.1230 | 1.450 | 1.064 | 1.427 | 1.7341 | yes | no | no |
| T-1h | Politics | [60,70) | 21 | 15 | 0.6552 | 0.7143 | 5.905 | 0.0989 | 0.1035 | 0.1338 | 0.1195 | 0.1237 | 0.1338 | 0.597 | 0.441 | 0.477 | 1.5813 | yes | no | no |
| T-1h | Politics | [70,80) | 23 | 16 | 0.7478 | 0.8696 | 12.174 | 0.0699 | 0.0904 | 0.1146 | 0.0856 | 0.0884 | 0.1146 | 1.743 | 1.063 | 1.377 | 1.3201 | yes | no | no |
| T-1h | Politics | [80,90) | 31 | 19 | 0.8379 | 0.9032 | 6.532 | 0.0539 | 0.0660 | 0.0965 | 0.0497 | 0.0510 | 0.0965 | 1.213 | 0.677 | 1.280 | 0.9507 | yes | no | no |
| T-1h | Politics | [90,100] | 844 | 162 | 0.9921 | 1.0000 | 0.790 | 0.0004 | 0.0030 | 0.0082 | 0.0006 | 0.0006 | 0.0082 | 19.091 | 0.965 | 14.149 | 0.0548 | yes | no | no |
| T-1h | Sports | [0,10) | 576 | 115 | 0.0225 | 0.0122 | -1.035 | 0.0046 | 0.0061 | 0.0202 | 0.0055 | 0.0055 | 0.0202 | -2.270 | -0.513 | -1.879 | 0.1275 | yes | no | no |
| T-1h | Sports | [10,20) | 129 | 68 | 0.1481 | 0.0930 | -5.508 | 0.0252 | 0.0312 | 0.0750 | 0.0260 | 0.0262 | 0.0750 | -2.182 | -0.734 | -2.101 | 0.7017 | yes | no | no |
| T-1h | Sports | [20,30) | 123 | 81 | 0.2452 | 0.1707 | -7.451 | 0.0344 | 0.0387 | 0.0676 | 0.0393 | 0.0396 | 0.0676 | -2.166 | -1.103 | -1.883 | 1.0955 | yes | no | no |
| T-1h | Sports | [30,40) | 133 | 83 | 0.3517 | 0.2030 | -14.865 | 0.0351 | 0.0413 | 0.0721 | 0.0385 | 0.0387 | 0.0721 | -4.241 | -2.062 | -3.838 | 1.3620 | yes | no | yes |
| T-1h | Sports | [40,50) | 235 | 89 | 0.4668 | 0.1745 | -29.234 | 0.0251 | 0.0325 | 0.0899 | 0.0318 | 0.0320 | 0.0899 | -11.662 | -3.253 | -9.146 | 1.3975 | yes | no | yes |
| T-1h | Sports | [50,60) | 93 | 73 | 0.5333 | 0.5054 | -2.796 | 0.0515 | 0.0516 | 0.0760 | 0.0601 | 0.0605 | 0.0760 | -0.542 | -0.368 | -0.462 | 1.5455 | yes | no | no |
| T-1h | Sports | [60,70) | 70 | 62 | 0.6489 | 0.7000 | 5.107 | 0.0545 | 0.0569 | 0.0639 | 0.0553 | 0.0558 | 0.0639 | 0.937 | 0.799 | 0.916 | 1.4694 | yes | no | no |
| T-1h | Sports | [70,80) | 51 | 47 | 0.7505 | 0.7647 | 1.422 | 0.0606 | 0.0605 | 0.0661 | 0.0610 | 0.0616 | 0.0661 | 0.234 | 0.215 | 0.231 | 1.2337 | yes | no | no |
| T-1h | Sports | [80,90) | 54 | 51 | 0.8415 | 0.9259 | 8.444 | 0.0370 | 0.0495 | 0.0534 | 0.0369 | 0.0373 | 0.0534 | 2.284 | 1.582 | 2.263 | 0.8732 | yes | no | no |
| T-1h | Sports | [90,100] | 311 | 97 | 0.9862 | 0.9936 | 0.736 | 0.0044 | 0.0065 | 0.0171 | 0.0045 | 0.0045 | 0.0171 | 1.676 | 0.431 | 1.640 | 0.0634 | yes | no | no |
| T-1h | Financial | [0,10) | 14 | 3 | 0.0136 | 0.0714 | 5.786 | 0.0687 | 0.0307 | 0.0620 | 0.0590 | 0.0722 | 0.0722 | 0.843 | 0.801 | 0.801 | 0.0937 | yes | no | no |
| T-1h | Financial | [10,20) | 3 | 2 | 0.1167 | 0.0000 | -11.667 | 0.0083 | 0.1852 | 0.2421 | 0.0079 | 0.0111 | 0.2421 | -14.000 | -0.482 | -10.500 | 0.7214 | yes | no | no |
| T-1h | Financial | [20,30) | 2 | 2 | 0.2425 | 0.0000 | -24.250 | 0.0375 | 0.3019 | 0.3019 | 0.0265 | 0.0375 | 0.3019 | -6.467 | -0.803 | -6.467 | 1.2859 | yes | no | no |
| T-1h | Financial | [30,40) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.5925 | - | - | - |
| T-1h | Financial | [40,50) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.7325 | - | - | - |
| T-1h | Financial | [50,60) | 0 | 0 | - | - | - | - | - | - | - | - | - | - | - | - | 1.7325 | - | - | - |
| T-1h | Financial | [60,70) | 1 | 1 | 0.6000 | 1.0000 | 40.000 | - | 0.4899 | 0.4899 | 0.0000 | - | - | - | - | - | 1.6800 | yes | no | no |
| T-1h | Financial | [70,80) | 1 | 1 | 0.7550 | 0.0000 | -75.500 | - | 0.4301 | 0.4301 | 0.0000 | - | - | - | - | - | 1.2948 | yes | no | no |
| T-1h | Financial | [80,90) | 2 | 2 | 0.8875 | 1.0000 | 11.250 | 0.0075 | 0.2234 | 0.2234 | 0.0053 | 0.0075 | 0.2234 | 15.000 | 0.504 | 15.000 | 0.6989 | yes | no | no |
| T-1h | Financial | [90,100] | 6 | 2 | 0.9900 | 1.0000 | 1.000 | 0.0026 | 0.0406 | 0.0675 | 0.0000 | 0.0000 | 0.0675 | 3.873 | 0.148 | - | 0.0693 | yes | no | no |
| T-1h | Other | [0,10) | 666 | 97 | 0.0145 | 0.0015 | -1.299 | 0.0016 | 0.0046 | 0.0158 | 0.0023 | 0.0023 | 0.0158 | -8.154 | -0.822 | -5.681 | 0.1000 | yes | no | no |
| T-1h | Other | [10,20) | 40 | 20 | 0.1410 | 0.0500 | -9.100 | 0.0348 | 0.0548 | 0.1017 | 0.0362 | 0.0371 | 0.1017 | -2.618 | -0.895 | -2.452 | 0.8478 | yes | no | no |
| T-1h | Other | [20,30) | 27 | 20 | 0.2419 | 0.1852 | -5.667 | 0.0748 | 0.0822 | 0.1059 | 0.0748 | 0.0768 | 0.1059 | -0.758 | -0.535 | -0.738 | 1.2835 | yes | no | no |
| T-1h | Other | [30,40) | 20 | 18 | 0.3470 | 0.2000 | -14.700 | 0.0917 | 0.1062 | 0.1164 | 0.1067 | 0.1098 | 0.1164 | -1.603 | -1.263 | -1.338 | 1.5861 | yes | no | no |
| T-1h | Other | [40,50) | 47 | 20 | 0.4751 | 0.1064 | -36.872 | 0.0451 | 0.0728 | 0.1490 | 0.0512 | 0.0526 | 0.1490 | -8.184 | -2.475 | -7.015 | 1.7457 | yes | no | yes |
| T-1h | Other | [50,60) | 19 | 16 | 0.5418 | 0.7368 | 19.500 | 0.1048 | 0.1141 | 0.1309 | 0.1020 | 0.1054 | 0.1309 | 1.861 | 1.490 | 1.851 | 1.7377 | yes | no | no |
| T-1h | Other | [60,70) | 13 | 13 | 0.6300 | 0.6154 | -1.462 | 0.1379 | 0.1337 | 0.1337 | 0.1325 | 0.1379 | 0.1379 | -0.106 | -0.106 | -0.106 | 1.6317 | no | no | no |
| T-1h | Other | [70,80) | 11 | 10 | 0.7355 | 0.7273 | -0.818 | 0.1400 | 0.1327 | 0.1445 | 0.1383 | 0.1457 | 0.1457 | -0.058 | -0.056 | -0.056 | 1.3619 | no | no | no |
| T-1h | Other | [80,90) | 25 | 15 | 0.8614 | 0.9200 | 5.860 | 0.0565 | 0.0688 | 0.1361 | 0.0806 | 0.0834 | 0.1361 | 1.037 | 0.430 | 0.702 | 0.8357 | yes | no | no |
| T-1h | Other | [90,100] | 207 | 63 | 0.9769 | 0.9952 | 1.831 | 0.0048 | 0.0103 | 0.0348 | 0.0056 | 0.0057 | 0.0348 | 3.791 | 0.526 | 3.234 | 0.1582 | yes | no | no |

---

## 5. Significance (BUILD step 6)

| test | threshold | cells passing |
|---|---|---|
| individual cells, **uncorrected** | t > 2.0 | **7** |
| individual cells, Bonferroni-corrected | t > 3.5 | **0** |

**7 cells would have been reported as findings at an uncorrected t > 2.0.**
After the §6 correction, 0 survive. That difference is the illustration of why
the correction exists — with 180 tests, cells at t > 2.0 are expected by chance many
times over.

All t-statistics above use **clustered** standard errors. Naive standard errors are
reported in the table for contrast and are used for no conclusion anywhere.

### The 3 pooled per-horizon tests (§6, t > 2.0)

| horizon | markets | **events (effective N)** | mean implied | realized | diff (c) | SE naive | SE CR1 | SE governing | t clustered | passes |
|---|---|---|---|---|---|---|---|---|---|---|
| T-7d | 1,731 | **273** | 0.3455 | 0.3247 | -2.087 | 0.0069 | 0.0138 | 0.0227 | -0.921 | no |
| T-24h | 4,980 | **752** | 0.3519 | 0.3343 | -1.751 | 0.0044 | 0.0058 | 0.0152 | -1.156 | no |
| T-1h | 8,143 | **1,066** | 0.3845 | 0.3598 | -2.468 | 0.0024 | 0.0040 | 0.0095 | -2.585 | YES |

`t clustered` is `diff / SE governing`, not `diff / SE CR1` — both columns are shown
so the guard's effect is visible wherever the model bound binds.

---

## 6. Fee overlay (BUILD step 7)

Measured miscalibration per bucket against the Step 0 fee-equivalent price error,
evaluated at each bucket's realised mean price and mean per-series fee multiplier.

| bucket | n obs | mean price (c) | mean fee mult | fee floor 1-leg (c) | fee floor 2-leg (c) | max abs pooled diff (c) |
|---|---|---|---|---|---|---|
| [0,10) | 6,495 | 1.83 | 0.985 | 0.1241 | 0.2482 | 1.063 |
| [10,20) | 930 | 14.52 | 0.971 | 0.8438 | 1.6876 | 7.766 |
| [20,30) | 776 | 24.63 | 0.975 | 1.2669 | 2.5339 | 9.293 |
| [30,40) | 694 | 34.89 | 0.969 | 1.5409 | 3.0819 | 14.988 |
| [40,50) | 903 | 45.99 | 0.944 | 1.6406 | 3.2811 | 26.544 |
| [50,60) | 583 | 53.88 | 0.976 | 1.6977 | 3.3954 | 5.177 |
| [60,70) | 432 | 64.67 | 0.985 | 1.5752 | 3.1504 | 4.826 |
| [70,80) | 434 | 74.98 | 0.992 | 1.3026 | 2.6053 | 3.097 |
| [80,90) | 581 | 84.84 | 0.993 | 0.8941 | 1.7882 | 6.882 |
| [90,100] | 3,026 | 98.04 | 0.965 | 0.1299 | 0.2598 | 1.893 |

**Cells clearing BOTH the statistical threshold and the fee floor:**

- with the 1-leg floor (primary): **0**
- with the 2-leg floor (stricter reading of "round-trip"): **0**

No cell clears both gates.

---

## 7. Null tests (BUILD step 8)

Two nulls are run. Both are reported in full; the second governs.

### Null 1 — within-category permutation, exactly as BUILD step 8 specifies

Settlement outcomes permuted **within each category**, which preserves each
category's YES count — and therefore its marginal YES rate — **exactly** in every
replication, not merely in expectation. The entire pipeline is re-run on each.

- replications: **8**
- cells passing corrected t > 3.5 per replication: `[55, 53, 56, 52, 54, 54, 55, 55]`
- cells passing uncorrected t > 2.0 per replication: `[72, 84, 78, 76, 78, 81, 80, 82]`
- maximum |t| per replication: `[35.01, 36.8, 33.61, 32.29, 33.6, 31.0, 30.28, 30.76]`

**A non-zero count here is forced by the design of this null, not by a defect in
the pipeline.** This test shuffles outcomes *across price buckets*, which drives
every bucket's realized frequency to the category mean, so the extreme buckets
must show large deviations on any dataset — including a perfectly calibrated one.
Measured on data calibrated by construction:

| | max abs deviation | cells at t > 3.5 |
|---|---|---|
| before permutation | 8.7c | 0 |
| after within-category permutation | 49.6c | 3 |

with the permuted table reading `[0,10) → +32c` and `[90,100] → −50c`. The
behaviour is pinned by a unit test in `tests/test_analysis.py`. See
`DECISIONS_008.md` decision 14.

### Null 2 — Bernoulli(implied price) resample — **this one governs**

Each outcome is redrawn from its own market's implied price. The market is then
calibrated at every price **by construction**, so the true difference in every cell
is zero. Any cell reaching t > 3.5 means the standard errors are too small — which
is exactly the failure BUILD step 8 exists to catch.

- replications: **8**
- cells passing corrected t > 3.5 per replication: `[0, 0, 0, 0, 0, 0, 0, 0]`
- cells passing uncorrected t > 2.0 per replication: `[1, 1, 2, 1, 1, 3, 3, 1]`
- maximum |t| per replication: `[2.06, 2.19, 2.83, 2.41, 2.21, 2.49, 3.13, 2.11]`
- maximum |difference| in cents per replication: `[54.75, 70.0, 74.5, 74.5, 76.5, 75.5, 60.0, 76.5]`

**PASS.** No cell passed t > 3.5 in any replication of the governing
null. The pipeline is not manufacturing significance from its own structure.

### Null 3 — comonotonic within-event resample — **also governs**

Null 2 draws each market independently, which destroys within-event dependence and
therefore **cannot see a clustering failure at all**. Null 3 fixes that: one uniform
draw per event, shared by every market in it, so each market's marginal probability
is still exactly its implied price — the market stays calibrated by construction —
but within-event dependence is *maximal*. That is the worst case for a clustered
standard error.

- replications: **8**
- cells passing corrected t > 3.5 per replication: `[0, 0, 0, 1, 0, 0, 0, 0]`
- cells passing uncorrected t > 2.0 per replication: `[1, 3, 4, 2, 3, 6, 3, 4]`
- maximum |t| per replication: `[2.11, 2.68, 2.9, 3.65, 2.65, 2.77, 3.16, 2.32]`

**The pass criterion is not "exactly zero".** With 1,232 tests (populated cells × replications) a correct
pipeline is *expected* to throw ~0.5732 cells above
t > 3.5 by chance, so demanding zero would stamp a valid run UNUSABLE
roughly a quarter of the time. The threshold is the 99th percentile of
Poisson(expected) = **3**.

| null | observed exceedances | expected | threshold | verdict |
|---|---|---|---|---|
| independent Bernoulli | 0 | 0.5732 | 3 | PASS |
| comonotonic Bernoulli | 1 | 0.5732 | 3 | PASS |

**PASS.** Both governing nulls are consistent with the nominal false-positive rate.

### What these nulls caught

On its first run the Bernoulli null failed, and it was right to. A cell of 18
markets in `[0,10)` at a mean implied price of 7.1c, all of which resolved NO, was
being reported at **t = −20.2**. An all-NO outcome for 18 contracts priced near 7c
has probability ≈ 0.27 — unremarkable. The residual-dispersion standard error
collapsed to 0.0035 because, with every outcome identical, the spread of `y − p`
measures the spread of the **prices**, not the sampling variability of the
**outcomes**.

This is §9's warning about the extreme buckets arriving through a *smaller*
standard error rather than a larger one.

**Then adversarial review caught a second, worse bug — in the fix itself.** The
first version of the guard used the *independence* model standard error
`√(Σ p(1−p))/n`. On a nested threshold ladder inside a single event — *"temp above
68 / above 69 / above 70"*, a real and common Kalshi structure in Weather and Sports
— that is the standard error for **n independent draws when there are only G**:

> 30 markets in 6 events, all priced 50c, market calibrated by construction, all six
> events resolving NO (probability 1/32). Every residual identical → cluster-robust
> meat exactly zero → the guard substituted `√(30 × 0.25)/30 = 0.0913` and reported
> **t = −5.48**, clearing t > 3.5 *and* the fee floor *and* the coarse re-cluster
> (which cannot help, because the independence form does not depend on the cluster
> key). Correct event-level standard error: `0.5/√6 = 0.2041`, i.e. **t = −2.45**.
> Exact enumeration over the 2⁶ event outcomes: **P(|t| > 3.5) = 1/32 = 3.1%**
> against a nominal 0.05%.

The shipped guard uses the **clustered** model standard error
`√( Σ_g ( Σ_{i∈g} √(p(1−p)) )² ) / n`, which assumes perfect positive dependence
within an event and collapses exactly to the independence form when every market is
its own event. That cell now gives 0.2041 and t = −2.45, and exact enumeration gives
**0/64**. Null 3 above exists precisely because Null 2 was blind to this.

**A claim made in an earlier draft is withdrawn.** It said the guard "can only make
a finding harder to declare, never easier". That is false in the zero-meat case,
where the unguarded statistic is `NaN` — which can never pass — and the guard
replaces it with a finite one. What is true is that the guard substitutes a
principled conservative bound for an estimate carrying no information. Both
t-statistics appear in the 180-cell table (`t clust` governs, `t unguarded` is the
raw clustered value) so the guard's effect is visible in every cell.

---

## 8. Conclusion (§8)

### DESCRIPTIVE ONLY

| §8 criterion | result |
|---|---|
| cells clearing fee floor **and** clustered t > 3.5 (after coarse re-test) | 0 |
| same directional bias at ≥2 of 3 horizons | n/a — not evaluated: s8's second bullet only applies to cells that cleared the first bullet, and no cell did |
| pooled \|realized − implied\| within the fee floor at every bucket, all horizons | False |

**Effective sample size beside every claim** — the number of distinct *events*, not
markets, per §5:

| horizon | markets | events (effective N) |
|---|---|---|
| T-7d | 1,731 | **273** |
| T-24h | 4,980 | **752** |
| T-1h | 8,143 | **1,066** |

### What the numbers actually say

The pooled deviation is **negative at all three horizons** — the market prices YES
slightly too high — and the sign is the same in every robustness cut. Only the
T−1h pooled test clears §6's pooled threshold of t > 2.0. No individual
bucket-category-horizon cell survives the Bonferroni correction, which is why §8's
bar for *"exploitable miscalibration exists"* is not met.

Read §9b before drawing anything from the size of the per-cell deviations. On a
genuinely two-sided book no wider than 5c the pooled deviation collapses to
−0.2c at T−7d, −0.8c at T−24h and −2.7c at T−1h, none of it significant. The large
per-cell numbers come from snapshots where the midpoint is not a price.

§8 permits no strategy to be designed from this without a new pre-registration that
states which category was selected and why, and acknowledges that the selection was
informed by this study.

---

## 9. Robustness checks

### The §2 reading of the exclusion rule (DECISIONS decision 6)

§2 makes "at least one recorded trade at each measurement horizon" a universe
criterion, while §3 excludes a market "from that horizon only". §3 governs the
primary result. Here are the three pooled tests re-run on the subsample of markets
that qualify at **all three** horizons — the §2 reading.

| horizon | markets | events | mean implied | realized | diff (c) | SE clustered | t clustered | passes t>2.0 |
|---|---|---|---|---|---|---|---|---|
| T-7d | 1,719 | 273 | 0.3457 | 0.3258 | -1.990 | 0.0226 | -0.881 | no |
| T-24h | 1,719 | 273 | 0.3486 | 0.3258 | -2.280 | 0.0205 | -1.114 | no |
| T-1h | 1,719 | 273 | 0.3586 | 0.3258 | -3.283 | 0.0175 | -1.879 | no |

### Snapshot freshness (DECISIONS decision 12)

The primary result imposes no staleness cap, because any cap preferentially drops
thin markets and §2 forbids filtering on liquidity. Here are the three pooled tests
re-run on snapshots no staler than one horizon-period (≤1h at T−1h, ≤24h at T−24h,
≤7d at T−7d), so it is visible whether any conclusion rests on stale quotes.

| horizon | markets | events | mean implied | realized | diff (c) | SE clustered | t clustered | passes t>2.0 |
|---|---|---|---|---|---|---|---|---|
| T-7d | 1,645 | 271 | 0.3558 | 0.3343 | -2.146 | 0.0236 | -0.910 | no |
| T-24h | 4,544 | 729 | 0.3608 | 0.3438 | -1.702 | 0.0162 | -1.048 | no |
| T-1h | 5,641 | 882 | 0.4081 | 0.3817 | -2.640 | 0.0121 | -2.184 | YES |

**Staleness distribution of the primary snapshots (seconds):**

| horizon | n | median | p90 | p99 | max |
|---|---|---|---|---|---|
| T-7d | 1,731 | 10,740 | 295,211 | 2,031,900 | 5,882,628 |
| T-24h | 4,980 | 3,338 | 75,600 | 965,236 | 6,401,028 |
| T-1h | 8,143 | 959 | 30,004 | 505,906 | 6,483,828 |

**Share of snapshots taken on a one-sided book** (kept per decision 5; excluding
them would be filtering on liquidity, which §2 forbids):

| horizon | one-sided share |
|---|---|
| T-7d | 0.423 |
| T-24h | 0.330 |
| T-1h | 0.708 |

---

## 9b. Where the deviation actually comes from — book quality

§9 pre-registered that *"a large, clean miscalibration would be surprising and
should be treated as a bug first"*. It was right to. This is that check.

§3 says "mid price" without saying what to do when the book barely exists, and on
Kalshi it frequently barely exists. A snapshot of `yes_bid = 0.0000, yes_ask = 0.94`
has a midpoint of 47c, which lands squarely in the `[40,50)` bucket — but it is not
a price. It means **nobody is bidding** and someone is offering at 94c. Inspecting
the largest single deviation in the table (T−1h, Sports, `[40,50)`, 235 snapshots,
−29.2c) found **67% with `yes_bid` exactly 0.0000 and 82% with a spread of 20c or
more**, almost all of them player-prop markets (`KXMLBHRR`, `KXMLBTB`, `KXNBAPTS`).

| stratum | n | events | mean implied | realized | diff (c) | t clustered | share |
|---|---|---|---|---|---|---|---|
| all snapshots | 14,854 | 1,074 | 0.3690 | 0.3472 | -2.183 | -2.065 | 1.000 |
| two-sided book | 6,713 | 951 | 0.4192 | 0.3997 | -1.951 | -1.122 | 0.452 |
| one-sided book | 8,141 | 805 | 0.3276 | 0.3039 | -2.375 | -2.975 | 0.548 |
| spread <= 2c | 7,659 | 801 | 0.3219 | 0.3158 | -0.606 | -0.799 | 0.516 |
| 2c < spread <= 5c | 2,923 | 694 | 0.3926 | 0.3852 | -0.737 | -0.488 | 0.197 |
| 5c < spread <= 10c | 1,747 | 524 | 0.4373 | 0.4230 | -1.432 | -0.690 | 0.118 |
| 10c < spread <= 20c | 781 | 294 | 0.4162 | 0.3905 | -2.565 | -0.875 | 0.053 |
| spread > 20c | 1,744 | 368 | 0.4468 | 0.3257 | -12.114 | -3.174 | 0.117 |
| T-7d: two-sided and spread <= 5c | 548 | 173 | 0.3744 | 0.3723 | -0.210 | -0.066 | 0.037 |
| T-24h: two-sided and spread <= 5c | 2,167 | 511 | 0.3833 | 0.3752 | -0.810 | -0.358 | 0.146 |
| T-1h: two-sided and spread <= 5c | 1,184 | 417 | 0.3996 | 0.3725 | -2.716 | -1.310 | 0.080 |

**Read the spread rows.** The deviation is flat and negligible on a tight book and
appears only where the spread is enormous. On the widest band the deviation is an
order of magnitude larger than on the tightest, on about a tenth of the snapshots.
Restricted to a genuinely two-sided book no wider than 5c, the pooled deviation at
every horizon collapses toward zero and none of it is significant.

**This is a diagnostic, not a result, and it changes no reported cell.** Splitting
on spread is conditioning on liquidity, which §2 forbids in terms — *"No filtering
on liquidity, volume or price"* — so the 180-cell table, the pooled tests and the
§8 verdict above all use every qualifying snapshot, wide books included. The split
is shown because it identifies **where** the headline number comes from, and because
it moves the answer toward "calibrated", not away from it: a reader who concluded
from §5 that Kalshi misprices these contracts by 10–40 cents would be reading an
artifact of the mid-price definition on an empty book.

It also means DECISIONS_008 decision 5 — keep one-sided books, exclude only when
**both** sides are sentinel — is too weak in practice. `bid = 0.00 / ask = 0.94`
has only one sentinel side, so it was kept, and its midpoint is meaningless. The
rule was chosen to avoid liquidity filtering and that reasoning still holds, but the
evidence above was not available when it was chosen. It is recorded here rather than
changed, because changing a frozen rule after seeing results is precisely what this
pre-registration exists to prevent.

---

## 10. What I built that does not work as intended

Required by the build spec, and written plainly.

1. **The universe is sampled, not exhaustive — a declared deviation from §2**  
   §2 asks for every settled market. The price measurement covers an outcome-blind random sample of events instead, because the full universe is ~1.74M markets and, at the measured 4 req/s public rate limit with one candlestick request per market, that is roughly 121 hours of continuous fetching. The census (market metadata, outcomes, categories, exclusion counts) IS exhaustive; only the prices are sampled. The draw is a fixed hash of the event ticker taken before any outcome was joined, so it cannot select on outcome, price, liquidity or volume — but it is still a sample, and every count in §4 onward is a sample count.

1. **Events are truncated by a market budget, which under-represents strike ladders**  
   Events are taken in fixed hash order until a per-category market budget is reached. Auto-generated crypto strike ladders put 300-400 markets in one event, so a single such event consumes a large share of a category's budget while contributing exactly one cluster to the effective N. The truncation is outcome-blind (the order is fixed by the seed before anything is known about any event) but it does mean the Financial category is represented by fewer distinct events than its market count suggests. The realised events-per-category counts are reported above; read them, not the market counts, as the statistical weight of each category.

1. **T−7d is measured on a different population from T−1h**  
   Only ~39% of Kalshi markets exist 7 days before close, versus ~99.6% at 1 hour. The T−7d population is therefore weighted toward long-dated politics, economics and weather, while T−1h is weighted toward intraday crypto and sports. §3 presents the three horizons as 'three separate measurements of the same question', and §9 predicts calibration 'should improve monotonically as horizon shortens' — but that prediction cannot be cleanly tested across three different populations. The §2-reading robustness check above restricts to markets present at all three horizons, which is the like-for-like comparison; prefer it for any cross-horizon claim.

1. **The T−7d and T−24h snapshots are taken from hourly candles**  
   One 60-minute request covers 208 days and serves both long horizons, so the snapshot can be up to 59 minutes earlier than the nominal horizon. Against horizons of 7 days and 24 hours that is negligible, and it errs early rather than late, so it cannot breach the Step 3 gate. T−1h uses a separate 1-minute fetch precisely because 59 minutes of slack would not be tolerable there.

1. **The within-category permutation null cannot pass, by construction**  
   BUILD step 8's literal test is reported but does not govern; see §7 above and DECISIONS_008 decision 14. It shuffles outcomes across price buckets, which forces large deviations in the extreme buckets on any dataset including a perfectly calibrated one. The Bernoulli(implied price) resample governs instead.

1. **A critical standard-error bug shipped, was caught by review, and is fixed**  
   The first version of the degenerate-cell guard used the INDEPENDENCE model standard error. On a nested threshold ladder inside one event it manufactured findings at 3.1% against a nominal 0.05%, verified by exact enumeration. It is fixed (clustered model SE) and pinned by regression tests, and the third null test exists because the second was structurally blind to it. Recorded here rather than quietly corrected, because it shipped in a form that would have produced a false 'exploitable miscalibration exists' verdict, and because it is a warning about the whole class: a guard added to prevent false findings can create them.

1. **A probe claim I could not reproduce, recorded rather than quietly dropped**  
   One API probe reported that passing a wrong `series_ticker` to the live candlestick endpoint returns HTTP 200 with an empty array — a silent failure. When I tested it directly, `/series/ZZZNOPE/markets/<real ticker>/candlesticks` returned real candles, i.e. the path segment appeared to be ignored rather than to cause a silent empty result. I could not reproduce the reported behaviour. The pipeline does not rely on either behaviour: it derives the series ticker from the market ticker and treats an empty candlestick response as a counted exclusion, never as 'no trading activity'.

1. **The Step 4 gate as the build spec words it would fail on correct data**  
   The spec says to assert that exactly one market resolves YES on a mutually exclusive event. Kalshi's flag means AT MOST one -- it says nothing about the listed outcomes being exhaustive -- and 55 of 581 exclusive events in the sample legitimately resolved all-NO (a WTI strike ladder settling outside every band; a 'which app is #1' event where a sixth app won). Both were re-fetched and their market lists are complete. The gate asserts at-most-one instead, which is the invariant a wrong grouping would actually break, and reports the all-NO count separately. Recorded because it is a deviation from the literal wording of the build spec, decided on evidence.

1. **Cells backed by a single event yield NaN and can never produce a finding**  
   A cluster-robust variance cannot be estimated from one cluster. Such cells are reported with a dash rather than a number. This is correct behaviour, but it means some populated cells are structurally incapable of contributing to §8 regardless of how large their apparent deviation is.

1. **Kalshi's fee schedule is a moving target**  
   The captured schedule is effective 2026-07-07 and was retrieved 2026-08-21, but per-series multipliers change over time — `/series/fee_changes?show_historical=true` shows changes as recent as 2026-08-20. The fee floor uses each series' CURRENT `fee_multiplier`, not the multiplier in force when each market traded. For markets that settled years ago the applicable fee may have differed. Since the standard multiplier is 1 for 13,174 of 13,339 series, the effect is small, but it is real.

1. **Pages 8-11 of the fee schedule PDF could not be read as text**  
   Those pages carry the remainder of the non-standard series table as raster images, not a text layer. The complete per-series multiplier list was taken instead from Kalshi's live fee-schedule page and from the API's own `fee_multiplier` field, both Kalshi-owned. The formula, the general fee table and the settlement-fee statement — everything the analysis actually depends on — came from the text layer of pages 2-5.

---

## 11. Reproducing this

```bash
pytest -q
python scripts/run_calibration.py --fees
python scripts/run_calibration.py --ingest
python scripts/run_calibration.py --gates
python scripts/run_calibration.py --permutation-null
python scripts/run_calibration.py --full
```

All HTTP responses are cached in `data/cache/http_cache.sqlite`, so re-running the
analysis costs no requests and reproduces the same numbers. The event sample is a
deterministic hash with seed `20260821`; the same census yields the same draw.

