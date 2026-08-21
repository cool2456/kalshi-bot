# Experiment 008 — resolved specification gaps

PREREG_008.md is the sole source of truth. Where it did not determine what the code
should do, the gap was put to Pranav and resolved on **2026-08-21** before any analysis
was run. Nothing here changes §2–§7; each entry records a reading of an
underdetermined point, or a declared deviation where one was unavoidable.

Recorded before results were seen. The build was not re-run under a different choice
after seeing an outcome.

| # | Gap | Resolution |
|---|-----|------------|
| 1 | §2 "every settled market" vs. a ~121-hour fetch at the measured 4 req/s public rate limit | **Outcome-blind random sample of EVENTS**, drawn across the whole archive before any outcome is joined. **Declared deviation from §2.** |
| 2 | Are multivariate combo (MVE) parlays part of the universe? | **Excluded, counted separately** as an exclusion reason. |
| 3 | Kalshi publishes 18 categories; §4 freezes 6 | Politics ← Politics + Elections + Mentions; Financial ← Financials + Crypto; the rest as listed below. |
| 4 | Which timestamp is the horizon anchor T? | **`close_time`** (trading stops). |
| 5 | "Mid price" when the book is one-sided | Keep one-sided books, `mid = (bid+ask)/2`; exclude only when **both** sides are sentinel. |
| 6 | §2 (all-or-nothing exclusion) contradicts §3 (per-horizon exclusion) | **§3 primary**, §2 reading reported as a robustness check. |
| 7 | What is "a recorded trade at horizon H"? | Cumulative traded volume > 0 **at or before H**. |
| 8 | §6 "round-trip cost" — how many taker legs? | **One leg** primary, two-leg floor reported alongside. |

---

## 1. Universe realisation — DECLARED DEVIATION FROM §2

§2 asks for "every settled Kalshi market available through the public API". Measured
facts that make that unreachable:

- ~1.74M settled non-combo markets exist, back to **2021-08-07**.
- Each market needs its own candlestick request; there is no bulk historical price endpoint.
- Kalshi's unauthenticated rate limit measures at **4 req/s clean, 8 req/s throttled**
  (60/60 HTTP 200 at 4 req/s; 19/60 HTTP 429 at 8 req/s).
- 1.74M requests at 4 req/s ≈ **121 hours** of continuous fetching against a free public endpoint.
- Restricting by date does not help: **87.5%** of all markets closed in the last 12 months.

**Resolution.** A fixed random sample of **events** — the §5 clustering unit, and the
unit in which the effective sample size is denominated — is drawn across the entire
archive. The sample is drawn from a deterministic hash of the event ticker with a fixed
seed, **before any settlement outcome is joined to any market**, so it cannot select on
outcome, price, liquidity or volume. Every market belonging to a sampled event is kept;
none is dropped for any reason other than the §2/§3 criteria.

A **complete census** of the market universe (ticker, event, category, outcome,
timestamps, volume) is still taken for **every** non-combo settled market in the archive,
because it is cheap — it needs no candlestick calls. §2's required reporting of total
markets, exclusions by reason and counts per category is therefore computed on the
**full universe**, not on the sample. Only the price measurement is sampled.

This is a deviation from §2 and is reported as one in FINDINGS_008.md.

## 2. Multivariate combo (MVE) markets — excluded and counted

99.75% of recently settled markets are MVE combos: single contracts on conjunctions of
legs in other markets (one observed contract spans 13 separate football and tennis
events). They are excluded because:

- They are **derivative** of markets already in the dataset. Including them counts the
  same underlying resolutions many times over.
- They **break §5's clustering model**. §5 assumes markets nest inside an event whose
  outcomes are mutually exclusive. A combo's parent "event" is a synthetic collection
  spanning many unrelated real events, so clustering on it neither captures the
  dependence between a combo and its legs nor between two combos sharing a leg.
- They would **dominate every cell**: the pooled YES rate on a 6,000-market sample was
  3.9%, pushing nearly all observations into the [0,10) bucket.

Detection: `mve_collection_ticker` present, or the API's own `mve_filter=exclude`.
Note `exchange_index` is **not** a reliable discriminator — archived combos were observed
with `exchange_index = 0`.

## 3. Category mapping — Kalshi's 18 → §4's 6

§4 requires "Kalshi's own series categorisation" grouped into six. Kalshi's live
`/series` endpoint publishes 18 distinct category strings across 13,339 series. The
mapping, fixed before analysis:

| §4 category | Kalshi `series.category` values | Series |
|---|---|---|
| **Weather** | Climate and Weather | 354 |
| **Economics** | Economics | 726 |
| **Politics** | Politics, Elections, Mentions | 2,198 + 1,579 + 414 |
| **Sports** | Sports | 3,472 |
| **Financial** | Financials, Crypto | 914 + 272 |
| **Other** | Entertainment, Science and Technology, Companies, World, Health, Commodities, Social, Transportation, Exotics, Education | 2,510 + 305 + 175 + 143 + 96 + 77 + 52 + 38 + 13 + 1 |

Elections and Mentions join Politics because both are political-outcome markets and §4
names no separate bucket for them. Crypto joins Financial on §4's own parenthetical,
"Financial (crypto/index levels)". Commodities and Companies stay in Other because that
parenthetical names only crypto and index levels.

Any category string not in this table — should Kalshi add one — maps to **Other**, and
its appearance is reported.

## 4. Horizon anchor T = `close_time`

Kalshi exposes `close_time` (trading stops), `expected_expiration_time`,
`expiration_time` and `settlement_ts` (payout recorded). §3 says the horizons precede
"settlement".

`close_time` is used because it is the only anchor at which T−1h is a real tradeable
price — after close the book is frozen, so a settlement-anchored T−1h would silently
carry the final pre-close quote forward and manufacture precision. It is also
**strictly conservative for the Step 3 gate**: `close_time ≤ settlement_ts` on every
market, so a price strictly before `close_time − H` is necessarily strictly before
`settlement_ts − H` as well. The pipeline asserts that ordering on every market and
reports any violation.

## 5. Mid price on a one-sided book

`yes_bid.close = 0.0000` means no YES bids exist; `yes_ask.close = 1.0000` means no NO
bids exist. These are sentinels, not quotes, and they are common — 19 of 37 hourly
candles on one real weather market carried a 0.0000 bid.

- **Both** sides sentinel → no price information exists → excluded at that horizon, counted.
- **One** side sentinel → kept, `mid = (bid + ask) / 2`, with 0.0000 / 1.0000 read as
  genuine bounds of the book.

Dropping one-sided books was rejected because it would preferentially remove deep
longshots, i.e. it would be **filtering on liquidity**, which §2 forbids in terms.

## 6. §2 vs §3 exclusion contradiction

§2 makes "at least one recorded trade at each measurement horizon" a universe criterion;
§3 says a market with no trades at a horizon is "excluded from that horizon only". They
cannot both hold: only 39.3% of markets exist 7 days before close, so §2 read literally
cuts the universe by ~61% without saying so.

**§3 governs the primary result** (per-horizon inclusion, per-horizon counts reported, as
§3 itself demands). The **§2 reading is additionally reported as a robustness check**:
the three pooled per-horizon tests are re-run on the subsample of markets that qualify at
all three horizons, and both sets of numbers appear in FINDINGS_008.md.

## 7. "A recorded trade at horizon H"

A market qualifies at horizon H if **cumulative traded volume > 0 at or before H**.

Requiring a trade inside the interval ending at H was rejected: 62% of one-minute candles
have zero volume even on a liquid market, so that reading would discard most observations
and would select on trading intensity — again a volume filter §2 forbids. Requiring only
lifetime volume was rejected because it would admit horizons at which the market had
never traded.

## 8. Fee floor — one taker leg, two-leg reported alongside

Verified schedule: taker fee `= 0.07 × M × P × (1−P)` dollars per contract; **no
settlement fee**. A position entered as taker and held to resolution therefore pays
exactly one fee.

- **Primary floor**: `7 × P × (1−P)` cents — peaks at **1.75c** at 50c, **0.63c** at the
  10c and 90c bucket edges, **0.00c** at 0c and 100c.
- **Also reported**: the two-leg floor, `14 × P × (1−P)` cents, so the §8 conclusion can
  be read against the stricter meaning of "round-trip".
- The per-series `fee_multiplier` M from Kalshi's API is applied per market; 14 series
  carry M = 0 and therefore have a zero fee floor.

The round-up in the published formula is deliberately **not** applied to the floor: it is
an artifact of order size (a 1-contract order pays a whole cent, a 1000-contract order
pays the continuous amount per contract). The continuous form is the per-contract
economic floor and is the smaller, more conservative choice.

---

## 9. Non-definitive outcomes — exclude the market, keep clean siblings

Kalshi's `result` enum is `['yes','no','scalar','']`. There is no void or cancel value;
unwound markets surface as `scalar` carrying a fractional `settlement_value_dollars`
(observed 0.02–0.74, including 0.50 pushes).

- Any market whose `result` is not exactly `yes` or `no` is **excluded and counted**,
  broken out by the raw `result` value, per §2.
- Sibling markets in the same event that did settle `yes`/`no` are **kept**. §2 excludes
  the ambiguous *market*, not the event.
- The count of events that were **partially** voided is reported, because the §4
  exactly-one-YES gate cannot be applied to them and must account for them separately.

Scoring scalars as fractional outcomes was rejected: the unwind value frequently echoes
the prevailing market price, so scoring against it scores the market against itself and
manufactures near-perfect calibration in exactly those cells.

## 10. Bucket assignment mechanics

- **No rounding.** The mid from a 1-cent-tick book lands on a half-cent grid (bid 9c /
  ask 10c → 9.5c). The exact value in cents is bucketed, so 9.5 → `[0,10)`. §3 fixes the
  edges and says prices are "sorted into" them; rounding to whole cents first would push
  mass upward at all nine interior boundaries and would need a further tie-break rule at
  every `.5` that §3 does not supply.
- **One observation per market.** Each market contributes exactly one row: YES at its
  mid, outcome 1 if it settled `yes`. Adding the mirrored NO observation at `1−p` was
  rejected — it double-counts a single resolution and makes `[0,10)` and `[90,100]`
  artificial reflections of each other.

## 11. Clustering unit — event_ticker primary, coarser re-test for any hit

§5 mandates clustering "at the event level" and §7 freezes it, so `market.event_ticker`
is the primary clustering key for all 180 cells and the distinct-event count is the
effective N reported beside every claim.

But `event_ticker` leaves real dependence behind: an NFL game's moneyline, spread and
total are three separate events resolved by one score, and crypto strike ladders split
one underlying hour across sibling events. Under-clustering understates SEs and
manufactures exactly the `t > 3.5` cells §6 exists to suppress.

**Therefore:** any cell clearing `t > 3.5` under event clustering is re-tested under a
strictly coarser key — `series_ticker` + close date — which merges those siblings. Only
cells surviving **both** are reported as findings. This tightens the frozen rule rather
than replacing it: it can only remove findings, never add them.

## 12. Snapshot staleness — carry forward, with a freshness robustness check

Candles are emitted only when something changes (1,453 of 2,340 minutes on one liquid
market; gaps to 31 minutes; nothing at all in the last 77 minutes before close), so a
candle exactly at a horizon usually does not exist.

- The snapshot at horizon H is the **latest candle with `end_period_ts ≤ H` that falls at
  or after the market's `open_time`**. No staleness cap: any cap would preferentially
  drop thin markets, which is the liquidity filtering §2 forbids.
- The **exact age** of every snapshot is recorded and the staleness distribution is
  reported per horizon.
- **Robustness check:** the three pooled tests are additionally re-run on the subset whose
  snapshots are fresher than one horizon-period (≤1h at T−1h, ≤24h at T−24h, ≤7d at T−7d),
  so it is visible whether any conclusion rests on stale quotes.
- The Step 3 gate asserts on the **source candle's real `end_period_ts`**, never on a
  server-synthesised timestamp. `include_latest_before_start` is therefore NOT used: it
  returns a candle stamped at H itself, which would defeat the gate, and it is unavailable
  on the historical tier anyway. The same widen-the-window rule is used on both tiers so
  the two eras are treated identically.

## 13. Market "existed at H"

A market exists at horizon H iff `open_time ≤ H < close_time`. Combined with §11 of this
document (a trade recorded at or before H) and a non-empty book, these are the three
per-horizon inclusion conditions, each counted separately in the exclusion report.

## 14. The null test — run both, the Bernoulli null governs

BUILD step 8 says to permute outcomes within each category and expects no cell to pass
`t > 3.5`, failing which "the pipeline is manufacturing significance and no result from
it is usable."

**That test cannot pass on any calibrated dataset**, and the reason is structural, not a
defect in this pipeline. Shuffling outcomes *across* price buckets drives every bucket's
realized frequency to the category mean. Measured on data that is calibrated by
construction:

| | max abs deviation | cells at t > 3.5 |
|---|---|---|
| before permutation | 8.7c | 0 |
| after within-category permutation | 49.6c | 3 |

with the permuted table reading `[0,10) → +32c` and `[90,100] → −50c`. Those numbers are
forced by the shuffle.

**Resolution.** Both nulls are run and both are reported in full:

1. **Within-category permutation**, exactly as BUILD step 8 specifies, with the marginal
   YES rate preserved *exactly* (within-group shuffling, not merely in expectation). Its
   numbers are reported, along with the note that a non-zero count is expected by design.
2. **Bernoulli(implied price) resample** — each outcome redrawn from its own market's
   implied price. The market is then calibrated at every price *by construction*, so the
   true difference in every cell is zero and any cell reaching `t > 3.5` really does mean
   the standard errors are too small. **This test governs** whether results are usable.

Both run for at least 8 replications, as BUILD step 8 requires.

## 15. Standard-error guard — governing SE is max(clustered CR1, binomial)

The Bernoulli null above caught a real defect on its first run, which is recorded here
because it would otherwise have produced false findings.

The residual-dispersion standard error — `sd(y − p)/√n`, and the cluster-robust estimator
built the same way — is unbiased but catastrophically unstable in the extreme buckets.
Observed in validation:

```
18 markets in [0,10), mean implied 0.0711, ALL 18 resolved NO
residuals all equal to -p_i, spanning only -0.05 to -0.09
sd(r) = 0.0149  ->  SE = 0.0035  ->  t = -20.2
```

An all-NO outcome for 18 contracts priced near 7c has probability ≈ 0.27. It is
unremarkable, but with every outcome identical the residual spread measures the spread of
the **prices**, not the sampling variability of the **outcomes**, so the standard error
collapsed and reported a 20-sigma event. This is §9's warning about the extreme buckets,
arriving through a smaller standard error rather than a larger one.

**Fix, and a correction to the first version of this fix.** Under the calibration null
`Var(y_i) = p_i(1 − p_i)` exactly, giving a stable model-based standard error. The
governing standard error is

```
SE_governing = max( SE_clustered_CR1, SE_bin_clustered )

SE_bin_clustered = √( Σ_g ( Σ_{i∈g} √(p_i(1 − p_i)) )² ) / n
```

`SE_bin_clustered` assumes **perfect positive dependence within each event** and
independence across events. When every market is its own event it collapses exactly to
the independence form `√(Σ p(1−p))/n`.

**It must be the clustered form.** The first version of this guard used the independence
form, and adversarial review showed that was a bug bad enough to manufacture findings:

> 30 markets in 6 events, markets inside each event perfectly co-moving — a nested
> threshold ladder inside one `event_ticker` (*"temp above 68 / above 69 / above 70"*),
> which is a real and common Kalshi structure in Weather and Sports. All priced 50c,
> market perfectly calibrated. All 6 events resolve NO (probability 1/32).
>
> Every residual identical → CR meat exactly 0 → `se_clustered_cr1 = 0`. The independence
> form gives `√(30 × 0.25)/30 = 0.0913` — the standard error for **30 independent draws
> when there are only 6**. Result: `t = −5.48`, clearing t > 3.5 and the fee floor, and
> surviving the coarse re-cluster (because the independence form does not depend on the
> cluster key at all). The correct event-level standard error is `0.5/√6 = 0.2041`,
> i.e. `t = −2.45`, not significant.
>
> Exact enumeration over the 2⁶ event outcomes: **P(|t| > 3.5) = 1/32 = 3.1%** against a
> nominal 0.05%. On data calibrated by construction.

With the clustered form that cell gives `SE = 0.2041`, `t = −2.45`, and exact enumeration
gives **P(|t| > 3.5) = 0/64**.

**An earlier claim in this document was wrong and is withdrawn.** It said the guard "can
only make a finding harder to declare, never easier". That is false in the zero-meat case:
there the unguarded statistic is `NaN`, which can never pass any threshold, and the guard
replaces it with a finite one. What is true is that the guard substitutes a *principled
conservative bound* for an estimate carrying no information. It is stated that way now
rather than papered over.

`SE_bin_clustered` is also not a lower bound on the true standard error in general: within
a **mutually exclusive** event exactly one market resolves YES, which is *negative*
dependence and reduces the variance below even the independent value. For those events the
guard deliberately overstates uncertainty. That is the direction a study whose purpose is
to avoid false findings should err in.

All five standard errors (naive, binomial, binomial-clustered, CR0, CR1) and both
t-statistics (governing and unguarded) appear in the 180-cell table, so the guard's effect
is visible in every cell rather than buried. A cell backed by a single event still yields
NaN and can never produce a finding.

## 16. A third null test — comonotonic within-event resampling

The independent Bernoulli null of decision 14 **cannot** see the failure above: it draws
each market's outcome independently, which destroys within-event dependence and makes the
independence standard error exactly correct. A null blind to the failure mode it is meant
to police is not much of a null.

A third null is therefore run: **one uniform draw per event**, shared by every market in
it, so market *i* resolves YES iff `u_g < p_i`. Each market's marginal probability is still
exactly its implied price — the market stays calibrated by construction — but within-event
dependence is now *maximal* (the comonotonic coupling), which is the worst case for a
clustered standard error.

On 8 events × 5 co-moving markets concentrated near 50c, 200 replications:

| guard | false positives at t > 3.5 |
|---|---|
| `max(CR1, binomial-independence)` — the buggy version | 2/200 = **1.0%** |
| `max(CR1, binomial-clustered)` — shipped | 0/200 = **0.0%** |

against a nominal 0.05%. This null governs alongside the independent one.
