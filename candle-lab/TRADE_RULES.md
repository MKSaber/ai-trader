# Trade rules — weaknesses and fixes

## Weaknesses found (trade-rules-v1 on 5m)

Under Trading 212 / GOV.UK costs (0.5% SDRT on buys, PTM £1.50 > £10k):

1. **5m pattern ranges were tiny** (~0.3–0.4%). Even a 2R take-profit often
   moved less than stamp duty once size hit the 10% position cap — so
   “winners” were net losers.
2. **Too many trades** — every bullish engulfing/hammer paid 0.5% SDRT again.
3. **Bearish signals forced exits** into small reds before targets could work.
4. **Session flat** cut overnight/continuation moves.
5. **No cost gate** — setups that could not clear round-trip costs still filled.

## trade-rules-v2 (locked after 10d hillclimb)

| Lever | v1 | v2 |
|-------|----|----|
| Bar interval | 5m | **60m** |
| Reward:risk | 2 | **4** |
| Stop | pattern low | **low − 1× pattern range** |
| Min pattern range | none | **≥ 0.3%** of price |
| Context | none for engulfing | **require downtrend** |
| Hours (London) | any | **10:00–15:00 only** |
| Trades / day / symbol | unlimited | **1** |
| Exit on bearish pattern | yes | **no** (stop/target only) |
| Force flat near close | yes | **no** |
| Cost gate | no | **skip if planned 4R ≤ costs** |

On the last **10** LSE sessions with T212 costs, v2 produced **positive P&L on
all five** names (VOD, BP, HSBA, GSK, AZN) in sample. That window was used in
the search — treat as research evidence, not out-of-sample proof.

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/backtest_20d.py --days 10 --rules trade-rules-v2 --broker trading212
# Shared £20k book, wider LSE set, 20 days:
python scripts/portfolio_20d.py --days 20 --cash 20000 --broker trading212
```

Human checklist (IG shapes → entry / stop / take-profit): [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
