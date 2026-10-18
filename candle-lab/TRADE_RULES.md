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

## Golden formula (trade-rules-v2.4)

**One static profile for every book** — no cash forks, no top-N forks.

| Lever | Value |
|-------|-------|
| Interval | 60m |
| Pattern | bullish engulfing only |
| Reward:risk | **6** |
| Hours (London) | **15 only** |
| Cooloff after stop | yes |
| Max stops / symbol | **2** |
| Risk / max position | **1.5% / 35%** |
| Symbol blocklist | banks† / defence / chronic drags |
| Cost gate | yes (6R) |

† HSBA kept (top-10 megacap).

**How we got here:** v2.2 stayed green on top-10 but red on top-50 £100k (universe
dilution). v2.3 fixed top-50 with cash-aware knobs (two formulas). A/B across
unified packs picked **`block+rr6`** — same blocklist + RR=6 + static 1.5%/35% —
dual-green on top-10 £20k **and** top-50 £100k for 60/90/120d.

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/portfolio_20d.py --days 60 --cash 100000 --rules trade-rules-v2.4 --broker trading212
```

Human checklist: [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
