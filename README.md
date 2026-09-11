# Kalshi research — experiment 008

This repository is a pre-registered measurement study of whether Kalshi prediction market prices are calibrated.

The core question is simple:

> Do contracts trading at price `p` resolve YES with frequency `p`?

In plain terms, if a market pays $1 for a YES outcome at 40 cents, is YES realized about 40% of the time in the relevant population? The project is not trying to build a trading strategy or a predictive model. It is trying to answer a statistical question about market pricing.

This is intentionally a measurement exercise. The repository’s output is designed to support a pre-registered conclusion under the constraints laid out in the project’s frozen research design, not to generate a strategy.

## Project goal

The project was designed to test whether Kalshi market prices are calibrated across a large, structured cross-section of settled markets.

The research design, as encoded in the project, has a few important characteristics:

- It uses the full public market census for metadata-level coverage.
- It samples price observations only after an outcome-blind event selection step.
- It studies calibration at multiple horizons relative to settlement.
- It stratifies by category and price bucket.
- It explicitly checks whether apparent miscalibration could be explained by fees, clustering, or null-model false positives.
- It requires a conservative rule before calling a result an "exploitable finding."

The intended output is not "find a trade". It is: "test whether quoted prices are informative probabilities, and if the observed deviations are large enough to be meaningful after accounting for fees and statistical uncertainty."

## Why this project exists

Kalshi markets are priced in dollars, but the economic interpretation of a price is usually probabilistic: a 60-cent YES contract captures a belief that the event resolves YES with probability roughly 60%.

The repository asks whether that relationship is empirically true in practice, in a broad sample of real markets, subject to:

- settlement outcomes,
- the price at several horizons before close,
- fees embedded in real pricing,
- correlation inside events,
- and statistical significance.

The project is therefore a calibration audit, not an implementation of a betting strategy.

## The pre-registered structure

The code and artifacts are built around an explicit experimental design:

- `PREREG_008.md`: frozen pre-registration, defining the research question and the decision rules.
- `BUILD_PROMPT_008.md`: build specification for the pipeline.
- `DECISIONS_008.md`: all implementation choices that were not fixed by the pre-registration, resolved before analysis.
- `FINDINGS_008.md`: generated narrative results report.
- `docs/sources/kalshi_fee_schedule_2026-07-07.md`: verbatim fee schedule captured from Kalshi's own PDF.

The code is very literal about this structure: the analysis pipeline is designed to enforce the pre-commitment regime rather than to let the data drive the conclusion ad hoc.

## The exact research question

The repository embodies a test of the following hypothesis:

- For a contract at price `p`, the realized YES rate in the relevant bucket should be near `p`.
- If it is systematically above or below `p`, the market is miscalibrated.
- If the divergence is large enough and survives standard-error and clustering corrections, it may be a meaningful finding.
- If the divergence is within fee-equivalent price error, it is not considered an exploitable miscalibration.

This is captured in the calibration table logic and the fee-floor overlay logic in the analysis code.

## Scope and constraints built into the project

The project deliberately avoids some things:

- It does not produce a buy/sell signal.
- It does not optimize execution.
- It does not choose categories after seeing results.
- It does not substitute source data from non-Kalshi endpoints.
- It explicitly stops if the API is unreachable rather than silently replacing data.

This was a hard design principle: the study is supposed to be reproducible and rule-bound.

## Data sources

The repository uses Kalshi’s public unauthenticated API only.

Endpoints used include:

- `GET /series`
- `GET /historical/markets?mve_filter=exclude`
- `GET /markets?status=settled&mve_filter=exclude&min_close_ts&max_close_ts`
- `GET /historical/markets/{ticker}/candlesticks`
- `GET /series/{s}/markets/{ticker}/candlesticks`
- `GET /historical/cutoff`

The implementation is careful about schema differences across data tiers:

- The archive and live candlestick APIs return different field names for the same concept (`price.close_dollars` vs `price.close`, `volume_fp` vs `volume`).
- No-trade periods are represented differently across tiers.
- The ingest layer normalizes these into one common shape before any analysis.

The API client also treats rate limits as part of the experiment design: requests are intentionally paced to a safe measured rate (about 4 requests/second), with HTTP cache persistence so re-runs are resumable.

## Main pipeline

The project is organized as a multi-stage pipeline.

### 1. Fee verification

The first step verifies Kalshi’s fee schedule against the published fee table and the actual arithmetic in the pricing rules.

This matters because the study does not treat price deviations in isolation. It asks whether a divergence is bigger than what can plausibly be explained by trading costs.

The code computes fee-equivalent price error per bucket and overlays it on the calibration results.

### 2. Census build

The pipeline builds a full market census from Kalshi’s settled markets, excluding combo markets and other non-conforming records as specified by the operational rules.

This yields a metadata inventory across:

- categories,
- market result distribution,
- timestamps,
- event membership,
- and other quality filters.

The full census is used for reporting and for the event sampling frame.

### 3. Outcome-blind event sampling

The project does not measure every market’s price path. It samples price observations from an outcome-blind event frame.

This step matters because a measurement study needs a manageable sample without selecting markets based on outcomes or prices.

In this repo, sampling is performed based on the event ticker only, with a fixed seed and no use of the outcome or market price in the selection process.

### 4. Horizon snapshots

Each sampled market is queried at multiple horizons before settlement:

- `T-7d`
- `T-24h`
- `T-1h`

At each horizon, the pipeline extracts a snapshot of the market’s implied price and the relevant settlement metadata. The snapshot logic enforces a timestamp gate to ensure the snapshot is taken before settlement minus the configured horizon boundary.

### 5. Calibration cells

The measurement is organized into a grid:

- 3 horizons
- 6 categories
- 10 price buckets

This produces 180 calibration cells.

The categories are:

- Weather
- Economics
- Politics
- Sports
- Financial
- Other

Buckets are fixed price ranges in cents, covering 0–100% in 10 equal bands.

Each cell computes:

- mean implied price,
- realized YES frequency,
- difference in price points,
- standard errors,
- t-statistics,
- and whether the effect survives clustering and correction rules.

### 6. Significance and null tests

This is a critical part of the project. It does not take one raw difference and call it a finding. It tests whether the observed pattern is larger than would be expected under a null model.

The repo includes multiple null tests:

- within-category permutation null,
- Bernoulli(implied price) null,
- clustered Bernoulli null.

The implementation is very explicit that the Bernoulli null is the governing check for the final signal, because it is the one that preserves the actual market-level implied prices while simulating the null distribution.

This prevents the analysis from mistaking the structure of the data as evidence of a real mispricing effect.

### 7. Fee overlay and real finding definition

A large raw difference is not automatically considered an exploitable finding.

The repo computes the fee-equivalent price error for each bucket and only treats a cell as a meaningful finding when it clears both:

- a statistical threshold,
- and a fee-equivalent floor threshold.

This is a strong safeguard against overinterpreting small deviations that are smaller than the cost of trading or that arise from statistical noise.

### 8. Final conclusion gate

The project includes a final pre-committed conclusion rule based on the defined hypotheses and the passing conditions.

The result can be one of several states, including:

- calibrated,
- descriptive only,
- unusable under failed null tests,
- or a specific finding if the evidence is strong enough.

The actual repository output currently records a conservative verdict: the study is descriptive only, and no cell cleared the pre-registered finding criteria once the full set of gates and null tests were applied.

## Repository layout

```text
.
├── README.md
├── data/
│   ├── cache/
│   └── derived/
├── docs/
│   └── sources/
├── scripts/
│   └── run_calibration.py
├── src/
│   └── kalshi008/
│       ├── __init__.py
│       ├── analysis.py
│       ├── api.py
│       ├── buckets.py
│       ├── categories.py
│       ├── config.py
│       ├── fees.py
│       ├── gates.py
│       ├── horizons.py
│       ├── ingest.py
│       ├── pipeline.py
│       ├── report.py
│       ├── stats.py
│       └── ...
├── tests/
│   ├── conftest.py
│   ├── test_analysis.py
│   ├── test_buckets.py
│   ├── test_fees.py
│   ├── test_horizons.py
│   ├── test_ingest.py
│   └── test_stats.py
└── ...
```

## Key modules

### `src/kalshi008/config.py`
Defines the frozen research parameters:

- horizons,
- categories,
- bucket boundaries,
- thresholds,
- constants for the research design.

### `src/kalshi008/fees.py`
Implements the fee schedule arithmetic and verifies it against Kalshi’s published table.

### `src/kalshi008/ingest.py`
Normalizes the raw market and candlestick data, joining metadata from the market universe and creating a consistent schema across live and historical data.

### `src/kalshi008/horizons.py`
Handles the horizon snapshot logic and the timestamp gating required for the study.

### `src/kalshi008/gates.py`
Runs the study’s gate checks: outcome validity, settlement join validity, timestamp validity, and mutually-exclusive-event constraints.

### `src/kalshi008/pipeline.py`
Coordinates the full end-to-end sequence:

- census,
- draw event sample,
- market collection,
- snapshot production,
- and derived artifact writing.

### `src/kalshi008/analysis.py`
Contains the actual calibration analysis:

- cell construction,
- pooled tests,
- fee overlay,
- null tests,
- and conclusion logic.

### `src/kalshi008/report.py`
Builds the machine-readable and narrative results documents, including the findings report.

## Running the project

The repo includes a command-line driver for the full workflow.

```bash
pytest -q
python scripts/run_calibration.py --fees
python scripts/run_calibration.py --ingest
python scripts/run_calibration.py --gates
python scripts/run_calibration.py --permutation-null
python scripts/run_calibration.py --full
```

The intended sequence is:

1. verify fee rules,
2. ingest the data,
3. run gate checks,
4. run the null tests,
5. build the calibration tables and final conclusion.

The ingest stage is the long pole because it is constrained by Kalshi’s public API rate limits and the volume of data. It is designed to be resumable and cached.

You can also use `--offline` to work from the local cache without making new requests.

## Generated outputs

The repo writes artifacts under `data/derived` and the project root, including:

- `census_report.json`
- `sample_info.json`
- `ingest_info.json`
- `gates.json`
- `null_tests.json`
- `conclusion.json`
- `calibration_cells.csv`
- `pooled_by_horizon.csv`
- `pooled_by_horizon_bucket.csv`
- `fee_floors.csv`
- `snapshots.jsonl`
- `sampled_markets.jsonl`
- `FINDINGS_008.md`

These are the machine-readable and narrative outputs of the measurement study.

## Current project status

The stored pipeline output in the repo is intentionally conservative. The generated conclusion in `data/derived/conclusion.json` records:

- `verdict: "descriptive only"`
- `n_findings_after_all_gates: 0`

That is consistent with the project’s purpose: it is a careful measurement study, not a strategy generator. It attempts to determine whether exploitable miscalibration exists, and in the available data it does not conclude that a calibrated market has been reliably violated in a way that passes all gates and the governing null tests.

## Bottom line

This project was trying to answer a very specific question:

> Are Kalshi prices empirically calibrated probabilities, once fees, event clustering, settlement logic, and statistical testing are accounted for?

The answer in this repo is not a trading recommendation. It is a disciplined measurement exercise designed to be reproducible, pre-committed, and conservative enough that claims of miscalibration require more than raw statistical noise or fee artifacts.
