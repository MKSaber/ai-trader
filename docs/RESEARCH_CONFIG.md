# Research configuration (baseline preserved)

Environment defaults live in `backend/app/core/config.py` and `.env`.

## Market data

| Key | Default | Notes |
|-----|---------|-------|
| `MARKET_DATA_PROVIDER` | `yfinance` | Live; fixture only if `DEMO_MODE` / offline |
| Fetch `lookback_days` | `1825` (~5y) | Daily; intraday still ~60d |
| Universe | VOD.L, BP.L, HSBA.L, GSK.L, AZN.L | Narrow; selection bias risk |

## Labels & features

| Key | Value |
|-----|-------|
| Horizon | `next_session_open_to_close` |
| Features | ret_1d, ret_5d, mom_20d, ma_gap_20, rvol_20, atr_norm_14, vol_change_5, overnight_gap |

Forecast issued conceptually at session **T close**; entry at **T+1 open**.
This is **not** an intraday timing model.

## Rolling protocol

| Key | Default |
|-----|---------|
| Train / test / step | 85 / 5 / 5 |
| Label purge | on |
| Long only | on (main comparison) |
| `min_prob` | 0.55 buy; shorts off unless `long_only=false` |
| Stop / TP | 1.5× / 2.0× ATR (stop_tp mode) |
| Execution modes | `stop_tp_costs`, `oc_with_costs`, `oc_zero_cost` |

### Reserved evaluation window

The corrected diagnostic batch used `max_folds=40` and ended at
**`DIAGNOSTIC_WINDOW_END = 2023-01-05`** (`rolling.DIAGNOSTIC_WINDOW_END`).

- That window (and the older unrestricted 231-fold long+short run) is
  **research history**, not fresh validation.
- Bounded follow-ups must set `min_test_start=2023-01-06` so test folds
  start **after** the diagnostic window.
- Only if the **direction gate PASSes** on that reserved period (vs
  train-majority naive) should costs/holds be revisited. Do not chase PASS.

### Bounded experiment (252 / reserved)

```bash
# Gross edge check (zero cost) on reserved folds
curl -X POST 'http://localhost:8000/api/research/rolling?fetch=false&train_sessions=252&test_sessions=5&step_sessions=5&long_only=true&execution_mode=oc_zero_cost&stamp_scenario=sdrt_0_5pct&min_test_start=2023-01-06&purge_label_overlap=true'

# Same forecasts with realistic SDRT costs (only meaningful if direction gate passed)
curl -X POST 'http://localhost:8000/api/research/rolling?fetch=false&train_sessions=252&test_sessions=5&step_sessions=5&long_only=true&execution_mode=oc_with_costs&stamp_scenario=sdrt_0_5pct&min_test_start=2023-01-06&purge_label_overlap=true'
```

## Costs

| Component | Default |
|-----------|---------|
| Commission | 5 bps each side |
| Spread | 10 bps full quote → half each side |
| Slippage | 5 bps each side |
| Stamp scenario `stress_1pct` | **1%** (historical stress; Settings `stamp_duty_rate`) |
| Stamp scenario `sdrt_0_5pct` | **0.5%** (GOV.UK principal SDRT) |
| Long stress round-trip | ≈ **1.4%** |
| Short (no stamp) | ≈ **0.4%** |

Paper cash: £100,000. Equity curve uses non-overlapping 2% notional fractions.

## Gates (unchanged thresholds)

- Direction: accuracy ≥ **55%** and beat train-majority naive.
- Trading: direction pass + ≥10 trades + **equity compounded return &gt; 0**.

Do not lower gates to force PASS.

## API examples

```bash
# Corrected long-only rolling (no refetch)
curl -X POST 'http://localhost:8000/api/research/rolling?fetch=false&long_only=true&execution_mode=stop_tp_costs&stamp_scenario=stress_1pct'

# Diagnostic: open-close zero cost
curl -X POST 'http://localhost:8000/api/research/rolling?fetch=false&execution_mode=oc_zero_cost&max_folds=40'

# Realistic stamp sensitivity
curl -X POST 'http://localhost:8000/api/research/rolling?fetch=false&stamp_scenario=sdrt_0_5pct&execution_mode=oc_with_costs'
```

Batch diagnostics: `python -m scripts.run_diagnostics` from `backend/` (writes
`sample_artifacts/DIAGNOSTIC_MANIFEST.json`).
