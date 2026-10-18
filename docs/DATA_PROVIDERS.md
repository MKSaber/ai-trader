# Market data providers

## Interface

All providers implement `MarketDataProvider` (`backend/app/ports/market_data.py`):

- `fetch_daily`, `fetch_intraday`, `fetch_corporate_actions`, `healthcheck`
- Downloaded bars are **market transactions**, never labelled as our paper executions

Adapters live under `backend/app/adapters/market_data/` and are selected by `MARKET_DATA_PROVIDER`.

## Default: Yahoo Finance via yfinance (prototype)

- Package: [yfinance](https://ranaroussi.github.io/yfinance/)
- LSE symbols use the `.L` suffix (e.g. `VOD.L`)
- Supports `interval="5m"`; [documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) states **intraday data cannot extend beyond the last 60 days**
- No API key required
- Unofficial Yahoo integration intended for personal research/education — review Yahoo terms before automated collection, long-term retention, or redistribution (especially public GitHub artifacts)
- Prefer private object storage for raw downloads; public workflow artifacts should carry sanitised reports/metrics, not full tick dumps
- Empty responses fail the live pipeline stage — **never** silently substitute fixture data

Export helper:

```bash
docker compose run --rm api python scripts/export_yahoo_intraday.py --symbol VOD.L --out /data/artifacts/VOD_L_5min.csv
```

## Offline: Fixture provider

Used only when `DEMO_MODE=true`, `--offline`, or `MARKET_DATA_PROVIDER=fixture`.

Sample files in `backend/sample_data/` are labelled `evidence_label=synthetic`.

## Not used: Twelve Data free tier

Twelve Data places London on the paid Grow tier and labels that coverage end-of-day, not intraday. It is not the free starting point for this project.

## Future paid adapters

Add a new class under `adapters/market_data/` implementing the port, register it in `adapters/factory.py`. No core service changes required. Document subscription and licensing before enabling in CI.
