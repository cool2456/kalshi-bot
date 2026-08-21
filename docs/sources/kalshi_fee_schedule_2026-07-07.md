# Kalshi Fee Schedule — verbatim capture

**Source (primary, canonical):** <https://kalshi.com/docs/kalshi-fee-schedule.pdf>
**Document title (PDF metadata / tab title):** `Fee Schedule for July 2026  - 7.7.26 Update`
**Document footer on every page:** `Last updated and effective: July 7, 2026`
**Retrieved:** 2026-08-21 (UTC) by experiment 008.
**Retrieval method:** `kalshi.com` sits behind a Vercel JS security checkpoint that returns HTTP 429 to
`curl` and to plain HTTP fetchers. The PDF was fetched inside a real browser session (Chrome), and its
text layer was extracted by inflating the PDF content streams (`DecompressionStream('deflate')`) and
decoding the Identity-H hex strings through each font's `/ToUnicode` CMap. No third-party mirror,
aggregator or secondary write-up was used at any point.

**Secondary Kalshi-owned corroboration (all retrieved 2026-08-21):**
- <https://kalshi.com/fee-schedule> — Kalshi's live fee-schedule page.
- <https://docs.kalshi.com/getting_started/fee_rounding> — fee rounding mechanics.
- <https://help.kalshi.com/en/articles/13823805-fees> — help-centre fees article (last updated April 19, 2026).
- Kalshi public API `GET /trade-api/v2/series/{series_ticker}` → `fee_type`, `fee_multiplier`.
- Kalshi public API `GET /trade-api/v2/series/fee_changes?show_historical=true` → historical multiplier changes.

---

## PAGE 1

(Cover page. Kalshi wordmark only, no text content.)

## PAGE 2 — Trading Fees / Maker Fees  [VERBATIM]

```
Trading Fees

The following terms apply to all event contract markets on the exchange, apart from specific products
listed below, which have their own fee schedule.

Trading fees are only charged for orders that are immediately matched with orders sitting on the
orderbook. Trading fees are not charged for orders placed that are not immediately matched and are
instead left as resting orders on the orderbook unless they are included in our "Maker Fees" section.

Trading fees are charged as a variable percentage fee of the expected earnings on an individual
contract, which is calculated by multiplying the maximum potential earnings from the contract by the
implied probability of making those earnings, or the price of the contract divided by $1. The current
general fee charged for a trade in dollars is given by the following formula:

 fees = round up(M x 0.07 x C x P x (1-P))
 P = the price of a contract in dollars (50 cents is 0.5)
 C = the number of contracts being traded
 M = the multiplier for each contract (default is 1 unless otherwise indicated)
 round up = rounds up such that the fee + positionCost is rounded to a centicent

Maker Fees

 fees = round up(M x 0.0175 x C x P x (1-P))
 P = the price of a contract in dollars (50 cents is 0.5)
 C = the number of contracts being traded
 M = the multiplier for each contract (default is 0 unless otherwise indicated)
 round up = rounds up such that the fee + positionCost is rounded to a centicent

Please refer to https://kalshi.com/fee-schedule for scheduled upcoming fee changes.

Maker fees are charged for orders placed that are not immediately matched and are instead left as
resting orders on the orderbook. These fees are only charged when a trade is ultimately executed,
there are no fees associated with canceling a resting order.

Last updated and effective: July 7, 2026
```

## PAGE 3 — Settlement / Membership / Deposit / Withdrawal Fees  [VERBATIM]

```
Settlement Fees

There is no settlement fee.

Membership Fees

There is no membership fee.

ACH Deposit and Withdrawal Fees

There is no fee associated with ACH deposits from your bank account to your Kalshi account. There is
no fee associated with ACH withdrawals to your bank account from your Kalshi account.

Wire Deposit and Withdrawal Fees

Fees for wire transfers vary from bank to bank. Kalshi does not charge any additional fees for wire
deposit transfers.  (Withdrawals by wire are not currently supported for transactions under $500,000).

Debit Deposit and Withdrawal Fees

Kalshi charges a maximum fee of 2% on card deposits, which may be reduced from time to time based upon
standards applied fairly and uniformly across members.

Crypto Deposit and Withdrawal Fees

Crypto deposits and withdrawals may have associated fees charged by Kalshi's third-party payment
processor. Such fees will be clearly disclosed prior to any associated transaction.

Alternate Payment Method Deposit and Withdrawal Fees

Kalshi reserves the right to charge between 0% and 2% fees on all rails, and the right to change those
rates at our discretion.

Futures Commission Merchant Customers

Users accessing Kalshi via a third-party Futures Commission Merchant may be charged fees by their
Futures Commission Merchant that vary from the above fee schedule. Such fees will be disclosed prior
to any associated transaction.

Last updated and effective: July 7, 2026
```

## PAGES 4-5 — General Trading Fees Table  [VERBATIM]

`General Trading Fees Table (See below for fees on specific markets)`

| Price of 1 contract | Fee for 1 contract | Price for 100 contracts | Fee for 100 contracts |
|---|---|---|---|
| $0.01 | $0.01 | $1.00  | $0.07 |
| $0.05 | $0.01 | $5.00  | $0.34 |
| $0.10 | $0.01 | $10.00 | $0.63 |
| $0.15 | $0.01 | $15.00 | $0.90 |
| $0.20 | $0.02 | $20.00 | $1.12 |
| $0.25 | $0.02 | $25.00 | $1.32 |
| $0.30 | $0.02 | $30.00 | $1.47 |
| $0.35 | $0.02 | $35.00 | $1.60 |
| $0.40 | $0.02 | $40.00 | $1.68 |
| $0.45 | $0.02 | $45.00 | $1.74 |
| $0.50 | $0.02 | $50.00 | $1.75 |
| $0.55 | $0.02 | $55.00 | $1.74 |
| $0.60 | $0.02 | $60.00 | $1.68 |
| $0.65 | $0.02 | $65.00 | $1.60 |
| $0.70 | $0.02 | $70.00 | $1.47 |
| $0.75 | $0.02 | $75.00 | $1.32 |
| $0.80 | $0.02 | $80.00 | $1.12 |
| $0.85 | $0.01 | $85.00 | $0.90 |
| $0.90 | $0.01 | $90.00 | $0.63 |
| $0.95 | $0.01 | $95.00 | $0.34 |
| $0.99 | $0.01 | $99.00 | $0.07 |

`Last updated and effective: July 7, 2026`

The "Fee for 100 contracts" column reproduces `ceil_cent(0.07 * 100 * P * (1-P))` exactly at every one
of the 21 listed prices. This is the arithmetic check that pins the formula.

## PAGES 6-7 — Non-Standard Fees (text-extractable portion)  [VERBATIM]

```
Non-Standard Fees

Series                                          Maker Multipler   Taker Multiplier
KXAAAGASM        US gas price                          1                 1
KXATPMATCH       ATP Tennis Match                      1                 1
KXBALLONDOR      Ballon d'Or                           1                 1
KXBTCMAX150      When will bitcoin hit 150k?           1                 1
KXBTCY           BTC price range EOY                   0                 0
KXCITRINI        Will the Citrini scenario materialize? 0                0
KXCPI            CPI                                   1                 1
KXCPIYOY         Inflation                             1                 1
KXDOED           DOE eliminated                        0                 0
KXEGGS           Egg prices                            1                 1
KXELECTIRAN      Will Iran hold a presidential election? 0               0
KXEMMYCACTO      Emmys Award for Lead Comedy Actor     1                 1
KXEMMYCACTR      Emmys Award for Lead Comedy Actress   1                 1
KXEMMYCSERIES    Emmys Award for Comedy Series         1                 1
KXEMMYDACTO      Emmys Award for Lead Drama Actor      1                 1
KXEMMYDACTR      Emmys Award for Lead Drama Actress    1                 1
KXEMMYDSERIES    Emmys Award for Drama Series          1                 1
KXETHY           ETH price EOY                         0                 0
KXFED            Fed funds rate                        1                 1
KXFEDDECISION    Fed meeting                           1                 1
KXGAMBLINGREPEAL Gambling Repeal                       0                 0
KXGDP            US GDP growth                         1                 1
KXGREENLAND      Greenland purchase                    0                 0
KXHEISMAN        Heisman Trophy Winner                 1                 1
KXINXY           S&P 500 yearly range                  1                 1
KXIPO            IPOs                                  1                 1
KXIRANDEMOCRACY  Will Iran become a democracy in 2026? 0                 0
KXLALIGA         LA LIGA                               1                 1
KXLAYOFFSYINFO   Tech layoffs                          0                 0
KXLLM1           Year-end top LLM                      1                 1

KXMVE  Combos (excluding uncorrelated NFL combos)      1                 2

Last updated and effective: July 7, 2026
```

## PAGES 8-11 — Non-Standard Fees, continued

**NOT TEXT-EXTRACTABLE.** These pages carry the remainder of the non-standard series table as raster
images (`/XObject << /Im1 ... /Im2 ... >>`), not as a text layer. The only text objects present are the
page footer `Last updated and effective: July 7, 2026` and the single `KXMVE` combos row transcribed
above. This is recorded as a known limitation of this capture.

**Substitute source used for the complete per-series list (both Kalshi-owned):**
1. <https://kalshi.com/fee-schedule> — live page, reports **156 total series** with non-standard fees
   and, for standard markets, `Fee multiplier 1` with a `Fee range (100 contracts)` of
   `$0.07 - $1.75 taker fees`, and combos maker fees at `50% of taker`.
2. Kalshi public API `GET /trade-api/v2/series/{series_ticker}` → `fee_type` and `fee_multiplier` per
   series. This is machine-readable, covers **every** series rather than only the non-standard ones,
   and is what this experiment actually joins onto each market. Observed `fee_type` values:
   `quadratic`, `quadratic_with_maker_fees`, `quadratic_with_combo_maker_fees`, `flat`.

## PAGE 12 — Perpetual Futures Fees  [VERBATIM]

```
Perpetual Futures Fees

Table 1: Exchange Taker Fee Schedule
Tier  30D Trailing Perps + Prediction Volume   Taker Fee (bps)
0     $0                                       12.0
1     >= $100K                                 10.0
2     >= $300K                                  8.0
3     >= $1M                                    6.0
4     >= $3M                                    5.0
5     >= $10M                                   4.0
6     >= $30M                                   3.5
7     >= $100M                                  3.2
8     >= $300M                                  3.0
9     >= $1,000M                                2.8
10    >= $3,000M                                2.6

Table 2: Exchange Maker Fee Schedule
Tier  30D Trailing Perps + Prediction Volume   Minimum Percent of Perps Maker Volume   Maker Fee (bps)
0     $0            OR  N/A       5.0
1     >= $100K      OR  N/A       4.0
2     >= $300K      OR  N/A       3.2
3     >= $1M        OR  N/A       2.4
4     >= $3M        OR  N/A       2.0
5     >= $10M       OR  N/A       1.6
6     >= $30M       OR  >= 0.1%   1.4
7     >= $100M      OR  >= 0.3%   1.2
8     >= $300M      OR  >= 1.0%   1.0
9     >= $1,000M    OR  >= 3.0%   0.8
10    >= $3,000M    OR  >= 10.0%  0.6
```

**NOT APPLICABLE to this experiment.** Perpetual futures are a separate product from the binary event
contracts PREREG_008 §2 defines as the universe. Recorded only to document that it was read and
excluded deliberately.

---

## Resolution of the §6 disagreement

PREREG_008 §6 notes that "public write-ups disagree, with some reporting 0% trading fees and others a
tier capping at 7% of winnings." Against the primary source both readings are wrong, and it is now
clear how each arose:

- **"0% trading fees"** — true only for *resting* (maker) orders on standard series, because the maker
  multiplier `M` defaults to **0**. It is also literally true for the handful of series carrying
  `M = 0` on both sides (e.g. `KXBTCY`, `KXETHY`, `KXDOED`, `KXGREENLAND`, `KXLAYOFFSYINFO`).
  It is false for any order that crosses the spread on a standard series.
- **"a tier capping at 7% of winnings"** — a misreading of the constant `0.07`. The 7% is not a cap on
  winnings; it is the coefficient on `P x (1-P)`. The fee peaks at `0.07 x 0.25 = $0.0175` per
  contract at `P = $0.50`, i.e. **1.75% of notional**, not 7% of anything.

Neither secondary reading survives contact with the primary document.
