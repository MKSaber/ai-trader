# Trade rules — weaknesses and fixes

## Golden formula (trade-rules-v2.6) — patterns-v2

**One static profile for every book.** Full London cash session (10:00–15:00).
Detector `patterns-v2`; A/B pick `engulf+harami`.

| Lever | Value |
|-------|-------|
| Interval | 60m |
| Hours (London) | **10, 11, 12, 13, 14, 15** (full session) |
| Patterns | **bullish engulfing + bullish harami** |
| Context | downtrend with prior-close drop **≥ 2%** over 5 bars |
| Reward:risk | **7** |
| Stop | pattern low − 1× range |
| Cooloff after stop | yes |
| Max stops / symbol | **2** |
| Risk / max position | **1.5% / 35%** |
| Symbol blocklist | banks† / defence / chronic drags |
| Cost gate | yes (7R) |
| Volume / next-open confirm | **off** (A/B: too sparse or dual-red) |

† HSBA kept (top-10 megacap).

**Why not v2.5 engulfing-only:** still dual-green under patterns-v2, but
`engulf+harami` raised min PnL on top10£20k + top50£100k across 60/90/120d
(~£938 / ~£6610 at 60d) without collapsing trade count.

**Why not volume / next-open:** volume≥1.2× often left 0–3 top10 trades;
next-open confirm flipped several windows red or to zero activity.

```bash
cd candle-lab/backend && . .venv/bin/activate
python scripts/portfolio_20d.py --days 60 --cash 20000 --rules trade-rules-v2.6 --broker trading212
```

Human checklist: [IG_PLAYBOOK.md](IG_PLAYBOOK.md).
Artifact: `backend/artifacts/ab_patterns_v2.json`, `golden_v26_patterns_report.json`.
