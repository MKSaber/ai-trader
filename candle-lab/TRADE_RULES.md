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

## trade-rules-v2 → v2.1 → v2.2

| Lever | v1 | v2 | v2.1 | **v2.2** |
|-------|----|----|------|----------|
| Bar interval | 5m | 60m | 60m | 60m |
| Patterns traded | engulf+hammer | engulf+hammer | engulfing only | engulfing only |
| Reward:risk | 2 | 4 | 5 | **5** |
| Stop | pattern low | low − 1× range | low − 1× range | low − 1× range |
| Hours (London) | any | 10–15 | 11, 12, 14, 15 | **15 only** |
| Cooloff after stop | — | — | — | **yes** |
| Max stops / symbol | — | — | — | **2** |
| Risk / max position | — | 1% / 25% | 1% / 25% | **1.5% / 35%** |
| Cost gate | no | yes (4R) | yes (5R) | yes (5R) |

**Why v2.1:** on the top-10 / 30d / £20k book, hammers and hours 10 & 13 were
net losers; raising RR to 5 let winners pay for more stops.

**Why v2.2 (60d stay-green):** v2.1 made +£420 on 30d but −£314 on 60d.
Root causes: H1 stop cluster (−£797) vs H2 (+£483); AZN/GSK drags; 35 stops
vs 4 TPs. A/B on the same top-10 book: **hour 15 only** was the dual-+ve base;
adding cooloff + max 2 stops/symbol + risk 1.5% / max pos 35% locked the
best dual-+ve pick. Rejected: min_stop 1.5% (over-filtered to 0 trades with
hours 11/15) and trail-to-breakeven (hurt 60d). Still in-sample research —
not guaranteed live edge.

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/portfolio_20d.py --days 60 --cash 20000 --rules trade-rules-v2.2 --broker trading212
```


Human checklist (IG shapes → entry / stop / take-profit): [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
