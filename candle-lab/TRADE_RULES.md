# Trade rules — weaknesses and fixes

## Golden formula (trade-rules-v2.5) — full session

**One static profile for every book.** Trades the **entire London cash session**
(10:00–15:00), not a single hour. Selectivity comes from **pattern / context /
exit geometry**, not the clock.

| Lever | Value |
|-------|-------|
| Interval | 60m |
| Hours (London) | **10, 11, 12, 13, 14, 15** (full session) |
| Pattern | bullish engulfing only |
| Context | downtrend with prior-close drop **≥ 2%** over 5 bars |
| Reward:risk | **7** |
| Stop | pattern low − 1× range |
| Cooloff after stop | yes |
| Max stops / symbol | **2** |
| Risk / max position | **1.5% / 35%** |
| Symbol blocklist | banks† / defence / chronic drags |
| Cost gate | yes (7R) |

† HSBA kept (top-10 megacap).

**Why not hour-15-only (v2.4):** valid for P&L, but too sparse for day trading —
most days had no orders. Full-day A/B replaced the clock filter with a **deeper
downtrend requirement (2%)** and **RR=7** (pick `dt2+rr7`).

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/portfolio_20d.py --days 60 --cash 20000 --rules trade-rules-v2.5 --broker trading212
```

Human checklist: [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
