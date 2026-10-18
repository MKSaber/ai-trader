# Architecture

Modular ports-and-adapters layout so providers, storage, and models can change without rewriting research logic.

```
backend/app/
  ports/          # Protocols only (MarketDataProvider, ObjectStorage, …)
  adapters/       # yfinance, fixture, local FS, S3, LSE calendar
  domain/         # enums / pure types
  services/       # features, models, eval, intraday, ingestion, research
  pipeline/       # 14 idempotent stages + orchestrator
  reporting/      # plain-English + machine-readable exports
  api/            # FastAPI routers (thin)
  cli.py          # daily-run entry
  db/             # SQLAlchemy models + session
```

## Extension points

| Change | Where |
|--------|--------|
| New market-data vendor | `adapters/market_data/<name>.py` + `factory.get_market_data_provider` |
| New object store | `adapters/storage/` + factory |
| New feature | `services/features/pipeline.py` `FEATURE_DEFINITIONS` |
| New model | `services/models/train.py` |
| New pipeline stage | `pipeline/orchestrator.py` stage list |

## Coding style

Google Python Style Guide conventions: Ruff with pydocstyle `convention = "google"`, 80-column soft target, typed public APIs.

## Frontend

Vite + React SPA. All financial and ML calculations remain in Python; the UI only displays API results.
