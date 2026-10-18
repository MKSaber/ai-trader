# Daily research pipeline

Entry point: `python -m app.cli daily-run`

Options: `--session`, `--from`, `--to`, `--dry-run`, `--offline`, `--symbols`.

## Stages

1. Create run record + Postgres advisory lock  
2. Check config / provider health  
3. Determine missing completed LSE sessions (calendar-aware)  
4. Download and validate  
5. Store raw refs + normalised bars / watermarks  
6. Resolve prior predictions  
7. Replay sessions with as-of models; freeze setups  
8. Update paper ledger  
9. Analyse errors / drift → findings  
10. Retrain challenger only if criteria met  
11. Evaluate challengers (no locked-test contamination; no auto-promote)  
12. Save findings + promotion recommendation  
13. Generate `DAILY_REPORT.md`, `SUMMARY.txt`, CSVs, JSON  
14. Finalise status; unlock  

Incomplete runs are never labelled `success`.

## Scheduler (GitHub Actions)

- Workflow timezone for `cron` is **UTC**
- Cron is approximate — do not assume exact start time
- Europe/London DST, holidays, and early closes are handled via `exchange_calendars` (`XLON`)
- Prefer running after expected data completeness; the pipeline **verifies** completeness rather than trusting the clock
- Catch-up: pass `--from` / `--to` or let missing-session detection fill gaps still within provider lookback

## Persistence for CI

GitHub runners are disposable. Authoritative state:

| Concern | Local Docker | GitHub Actions |
|---------|--------------|----------------|
| DB | Compose Postgres | External `DATABASE_URL` (you provision) |
| Files / models | `./storage` | S3-compatible (`OBJECT_STORAGE_BACKEND=s3`) |
| Reports | `storage/artifacts` | Workflow artifacts (downloadable only) |

Secrets needed for durable CI: `DATABASE_URL`, S3 credentials. yfinance needs no key. Never commit secrets or print connection strings.

## Artifact bundle

- `DAILY_REPORT.md` — readable daily report  
- `SUMMARY.txt` — short nontechnical summary  
- `signals.csv`, `closed_trades.csv`  
- `metrics.json`, `run_manifest.json`  
- `data_quality_warnings.txt`, `sanitised.log`  
