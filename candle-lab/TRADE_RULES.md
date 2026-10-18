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

## trade-rules-v2 → v2.1

| Lever | v1 | v2 | **v2.1** |
|-------|----|----|----------|
| Bar interval | 5m | 60m | 60m |
| Patterns traded | engulf+hammer | engulf+hammer | **engulfing only** |
| Reward:risk | 2 | 4 | **5** |
| Stop | pattern low | low − 1× range | low − 1× range |
| Hours (London) | any | 10–15 | **11, 12, 14, 15** (skip 10 & 13) |
| Cost gate | no | yes (4R) | yes (**5R**) |

**Why v2.1:** on the top-10 / 30d / £20k book, hammers and hours 10 & 13 were
net losers; raising RR to 5 let winners pay for more stops. Still in-sample
research — not guaranteed live edge.

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/portfolio_20d.py --days 30 --cash 20000 --rules trade-rules-v2.1 --broker trading212
```


Human checklist (IG shapes → entry / stop / take-profit): [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
