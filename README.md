# LSE Pattern Lab

Local-first research application for London-listed equities. Import market data, derive interpretable predictive formulas, paper-trade intraday setups, and run a daily GitHub research pipeline.

**This is not a trading bot.** There is no broker connection, no live order placement, and no automatic model promotion. “Insufficient evidence” and “no demonstrated edge” are valid outputs. Synthetic and short Yahoo histories do **not** establish profitability.

## Start (one command)

```bash
cp .env.example .env
docker compose up --build
```

- UI: [http://localhost:3000](http://localhost:3000)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Offline end-to-end demo (synthetic labelled data):

```bash
docker compose run --rm api python scripts/e2e_demo.py
```

Daily research CLI (no dashboard required):

```bash
docker compose run --rm api python -m app.cli daily-run --offline
docker compose run --rm api python -m app.cli daily-run --session 2024-03-15 --offline
```

## What works

- Upload CSV/XLSX/PDF/TXT with hash dedupe, GBX→GBP normalisation, OCR flag for scanned PDFs
- Feature pipeline with as-of rules (no fabricated missing values)
- Models: naive, momentum, ridge, logistic, LightGBM — chronological walk-forward
- Immutable predictions; outcomes appended later
- Manual champion promotion
- Intraday long-only paper setups with cost model, same-bar ambiguity handling
- Daily 14-stage pipeline + plain-English artifact bundle
- yfinance provider (prototype) + explicit fixture/`--offline` mode
- Apple-style React UI

## Limitations

- yfinance is unofficial; intraday lookback ~60 days; personal-use terms apply — see [docs/DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md)
- No OCR engine (scanned PDFs are flagged `needs_ocr`)
- External Postgres + S3 required for durable GitHub Actions runs (not auto-provisioned)
- Twelve Data free tier is **not** used (LSE intraday not on free tier)

## Live Candle Pattern Test (separate app)

Independent of Pattern Lab models/DB. IG-defined candlestick detection on
delayed Yahoo 5m bars, paper longs, and a **Learn · stock day** chart with
entry/stop/take-profit overlays. See [candle-lab/README.md](candle-lab/README.md).

Open via Pattern Lab UI tab **Candle patterns**, or run:

```bash
cd candle-lab/backend && pip install -e ".[dev]" && uvicorn app.main:app --port 8100
cd candle-lab/frontend && npm install && npm run dev   # :3100
```

## Tests

```bash
docker compose run --rm api pytest -q
cd candle-lab/backend && pytest -q
```

## Architecture

Ports/adapters layout and extension points: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)  
Pipeline stages and scheduler notes: [docs/PIPELINE.md](docs/PIPELINE.md)

## Report schemas (upload)

**Market OHLCV CSV** (required columns — aliases accepted):

| Column | Aliases |
|--------|---------|
| symbol | ticker, yahoo_symbol |
| session_date | date, timestamp |
| open, high, low, close | open_raw, … |
| volume | optional |
| currency | optional, default GBX |

Label synthetic files with `evidence_label=synthetic`.

## Cost assumptions (defaults)

Visible in Settings / env: commission 5 bps, spread 10 bps, slippage 5 bps, UK stamp duty 1% on purchases. Stress and change via `.env`.

## License / data

Respect Yahoo and any paid-provider terms. Do not commit credentials or redistribute restricted tick dumps in public artifacts.
