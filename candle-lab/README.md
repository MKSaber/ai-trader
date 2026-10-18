# Live Candle Pattern Test

Independent application for observing **IG-defined candlestick patterns** on
London shares, generating paper long setups, and learning from day charts.

**Does not share** database, models, or config with LSE Pattern Lab.

## Reference

Pattern *qualitative* definitions:
https://www.ig.com/uk/ig-academy/the-basics-of-technical-analysis/candlestick-patterns  

Numeric thresholds are experiment assumptions — see `PATTERN_DEFINITIONS.md`.

## Feed warning

Market data uses **Yahoo Finance via yfinance** (typically **delayed**,
unofficial). The UI labels this clearly. Delayed observation **cannot** prove
timely live execution. No broker orders are placed.

## Quick start

```bash
# API (SQLite by default — isolated file candle_lab.db)
cd candle-lab/backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8100

# UI
cd ../frontend
npm install
npm run dev   # http://localhost:3100
```

From the main Pattern Lab UI, open the **Candle patterns** tab (iframe to
port 3100) — it does not call Pattern Lab `/api` research endpoints.

## Learn subtab

1. Select a stock (VOD.L, BP.L, HSBA.L, GSK.L, AZN.L).
2. Pick a London calendar day.
3. View 5m candles, detected patterns, and illustrative entry / stop / take-profit.

## Tests

```bash
cd candle-lab/backend && . .venv/bin/activate && pytest -q
```

## 20-day paper backtest (pattern detector only)

Replays delayed Yahoo 5m bars for the last N LSE trading days, detects
`patterns-v1` signals, and paper-trades long setups with `trade-rules-v1`.

Cost profiles (GOV.UK SDRT 0.5%, Takeover Panel PTM £1.50 > £10k, plus
Trading 212 / eToro schedules) are documented in [COST_SOURCES.md](COST_SOURCES.md):

```bash
cd candle-lab/backend && . .venv/bin/activate
# Default trade-rules-v2 (60m, cost-aware) — see TRADE_RULES.md + IG_PLAYBOOK.md
python scripts/backtest_20d.py --days 10 --rules trade-rules-v2 --broker trading212 \
  --symbols VOD.L,BP.L,HSBA.L,GSK.L,AZN.L
# Shared £20k portfolio, top-10 LSE megacaps, 30 days:
python scripts/portfolio_20d.py --days 30 --cash 20000 --broker trading212
# Legacy 5m rules for comparison:
python scripts/backtest_20d.py --days 10 --rules trade-rules-v1 --broker trading212
```

## What was verified now vs later

- **Now:** unit tests for pattern boundaries, ambiguous exits, detector stability;
  learn chart API against Yahoo (if network allows).
- **Not claimed:** a full live LSE session observation unless the runner was
  left polling through a complete session with stored records.
