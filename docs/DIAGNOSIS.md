# Evidence-based diagnosis — LSE Pattern Lab

Generated from source inspection and corrected diagnostic runs. This document
does **not** promise profitability.

## Plain-English summary

The system is not “finding patterns that recommend the right buy/sell” because:

1. **The features have little out-of-sample predictive power** for next-session
   open-to-close returns on this five-name universe (confirmed by rolling
   accuracies ≈ 50–52%, below or near a train-majority naive).
2. **The objective does not match a trader’s P&amp;L.** Models optimise direction /
   squared error on open→close; execution uses stops/targets and ~1.4% stress
   round-trip costs. A small directional “edge” cannot clear that hurdle.
3. **Several implementation defects inflated losses or mis-stated baselines**
   (fixed below). After correction, the story is still: **no demonstrated edge**.
4. **Evidence is thin for live tips** (13 resolved forecasts; near-50% probabilities
   correctly yield `no_trade`).

Near-50% probabilities and abstention are appropriate when there is no edge.

---

## Path the code actually takes

```
yfinance (curl_cffi) → persist daily/intraday bars (GBP via GBX×0.01)
  → build_daily_features (as-of features + target_next_session_oc)
  → rolling/holdout splits (shared session calendar)
  → imputer/scaler fit on train only → ridge/logistic/lightgbm
  → P(up) → long if ≥ min_prob (shorts optional)
  → enter next open → stop/TP or close → subtract costs
  → metrics + equity curve + experiment row
```

Key locations:

| Stage | Location |
|-------|----------|
| Fetch | `backend/app/api/routes.py` `_yahoo_fetch_into_db`, `YFinanceMarketDataProvider` |
| Persist / FX | `backend/app/services/ingestion/persist.py`, `currency.py` |
| Features / labels | `backend/app/services/features/pipeline.py` |
| Train / holdout | `backend/app/services/models/train.py`, `research.py` |
| Rolling / execution | `backend/app/services/eval/rolling.py` |
| Costs | `backend/app/services/eval/costs.py` |
| Gates | `holdout_success_verdict` in `train.py` |

---

## Issue table

| Sev | Type | Finding | Source | Effect | Fix |
|-----|------|---------|--------|--------|-----|
| **Critical** | Bug | Naive baseline used P=0.5 → always-predict-up; accuracy = **test** up-rate | `train.py`, `rolling.py` | Gate compared models to a test-peeking baseline | Train-fold majority (`baselines.py`) |
| **Critical** | Bug | Shorts charged full stamp duty | `estimate_round_trip_cost_fraction` default | Inflated short losses (~+1% per short) | `side=` aware; stamp on longs only |
| **High** | Bug | Label purge helper unused; train labels overlap test session | `_purge_mask` dead; rolling folds | Mild leakage / optimistic train fit | `apply_label_purge` on by default |
| **High** | Design | Research default mixed long+short without borrow model | `rolling.py` | Unjustified short P&amp;L | Default **long_only=True** |
| **High** | Design | Sum of fractional trade returns treated like performance | prior trading metrics | −39 “sum net” ≠ portfolio loss | Cash equity curve from £100k |
| **Medium** | Design | `stamp_duty_rate=0.01` vs GOV.UK principal SDRT **0.5%** | `config.py` | Stress costs ~2× realistic stamp | Keep stress; add `sdrt_0_5pct` scenario |
| **Medium** | Design | One-bar OHLC stop/TP; ambiguous path → stop-first | `_simulate_trade` | Conservative; most exits are close | Document; sensitivity later |
| **Medium** | Design | Objective = next-session OC, not intraday timing | features + horizon | Cannot identify intraday entry | Needs timestamped bars + during-session labels |
| **Medium** | Design | 85 sessions × 5 correlated names ≠ 425 independent rows | rolling protocol | Overfit risk for trees | Longer window / stronger regularisation experiments |
| **Low** | Design | `auto_adjust=False`; corporate actions incomplete | yfinance provider | Possible artificial jumps | Track actions; prefer executable prices |
| **Low** | Hypothesis | Weak IC / negative R² | metrics | Features lack signal | Ablations / regimes (exploratory) |
| **Info** | Design | `overnight_gap` uses session-T open | `pipeline.py` | OK at T close for T+1 label | Documented; not leakage for this horizon |

### Confirmed vs hypothesis

- **Confirmed bugs:** naive test-peeking; stamp on shorts; unused purge.
- **Design limits:** cost hurdle vs OC horizon; long/short asymmetry; OHLC ambiguity; narrow universe; objective mismatch.
- **Hypothesis:** technical features simply have no stable edge on these names.

---

## Why reported metrics looked the way they did

### AUC 0.547, R² −0.07, rolling &lt; naive

Consistent with **weak signal + unstable fit**, not a single metric bug:
- Slightly above chance on one frozen split does not survive rolling mean accuracy.
- Negative R² means predictions worse than predicting the mean return.
- After fixing naive, models must beat **train majority**, not the test balance.

### Win rate 13.6% and avg net ≈ −1.34%

With stress round-trip ≈ **1.4%** on longs:

`2 * ((10+5+5)/10000) + 0.01 = 0.014`

If gross moves are typically &lt;1% (session OC or early stop), **almost every trade loses after costs**. That matches exits dominated by `session_close` and avg net ≈ −cost. This is cost hurdle + weak gross edge, not only accounting error — though charging stamp on shorts was an additional bug.

### Latest all `no_trade` ~50.1%

Appropriate: calibrated-ish indifference. Raising `min_prob` without validation would just sparsify noise.

### 13 forecasts / 2 band hits

Insufficient for a success rate claim; report uncertainty, do not extrapolate.

---

## Timing / leakage (session T close → trade T+1 open)

| Feature | Inputs known by T close? |
|---------|---------------------------|
| ret_*, mom_*, ma_gap, rvol, atr, vol_change | Yes (through T close) |
| overnight_gap | Yes (T open already traded) |
| Label `target_next_session_oc` | Uses **T+1** open/close — future vs T |

Imputer/scaler: fit on train fold only (confirmed).  
Shared calendar splits: yes.  
Purge: now drops train rows whose T+1 outcome falls in the test window.

**Intraday entry models** would need: features using only data ≤ signal timestamp, labels defined on post-signal paths, and real intraday history (Yahoo 5m ≈ 60d — cannot backfill 5y).

---

## Data quality notes

- LSE quotes treated as **GBX → GBP × 0.01** (`currency.py`).
- `auto_adjust=False`: unadjusted OHLC; splits/dividends can create jumps; actions fetch is best-effort.
- Daily vs intraday: intraday depth ≠ 5y daily; daily is not silently swapped into intraday labs when missing (intraday endpoints disable instead).

---

## Three highest-priority next actions

1. **Keep correctness defaults** (train-majority naive, long-only, purge, side-aware costs) and treat prior unrestricted rolling runs as **research history**, not fresh validation.
2. **Run cost decomposition diagnostics** (`oc_zero_cost` vs `oc_with_costs` vs `stop_tp_costs`) on a frozen fold budget; only if gross OC shows a stable edge, study costs/holds.
3. **Bounded next experiment:** longer train window (e.g. 252) + stronger leaf regularisation + long-only OC with `sdrt_0_5pct`, evaluated on **folds after** the diagnostic window — do not retune thresholds until the direction gate passes on reserved data.

If those still show no gross edge: state “no edge on this universe/objective” and expand data/objective rather than chasing PASS.

---

## Before / after (corrected diagnostics)

Protocol frozen for comparison: 85/5/step5, `max_folds=40`, long-only,
purge on, `min_prob=0.55`. Manifest:
`backend/sample_artifacts/DIAGNOSTIC_MANIFEST.json`.

Prior unrestricted run (research history, pre-fix / long+short): direction
FAIL; 2976 trades; win 13.6%; sum fractional net −39.8; no equity curve.

| Mode | Stamp | Trades | Win | Avg gross | Avg net | Equity compounded | Dir gate | Trade gate |
|------|-------|--------|-----|-----------|---------|-------------------|----------|------------|
| oc_zero_cost | n/a | 355 | 49.3% | +0.075% | +0.075% | **+0.53%** | FAIL (LGBM 51.6% vs naive 50.1%) | FAIL |
| oc_with_costs | stress 1% | 355 | 16.3% | +0.075% | **−1.33%** | −9.0% | FAIL | FAIL |
| oc_with_costs | SDRT 0.5% | 355 | 26.8% | +0.075% | −0.83% | −5.7% | FAIL | FAIL |
| stop_tp_costs | stress 1% | 355 | 16.3% | +0.076% | −1.32% | −9.0% | FAIL | FAIL |
| stop_tp_costs | SDRT 0.5% | 355 | 26.8% | +0.076% | −0.82% | −5.7% | FAIL | FAIL |

**Interpretation:** Even with zero costs, gross edge is tiny and direction gate
fails. Costs (especially stamp) turn a near-flat gross into large net losses.
Stop/TP on one session barely changes the outcome versus open→close. **No
profitable edge is demonstrated** after correctness fixes.

### What data/modelling would be needed for intraday entries

- Timestamped intraday bars covering the evaluation period (Yahoo 5m ≠ 5y).
- Features using only information ≤ signal time.
- Labels = path after signal (touch stop/TP / time stop), with purge spanning the hold.
- Execution at next bar open; costs per side; long-only until short borrow is modelled.

---

## Bounded reserved experiment (252 / after diagnostic window)

Policy: diagnostic window ends **2023-01-05** (`DIAGNOSTIC_WINDOW_END`). Fresh
folds use `min_test_start=2023-01-06`. Old 231-fold long+short run remains history.

Config: train **252**, test 5, step 5, long-only, purge on, `sdrt_0_5pct`.
Artifact: `backend/sample_artifacts/BOUNDED_252_RESERVED.json`.

| Mode | Folds | Best acc | Naive | Avg gross | Equity | Dir gate |
|------|-------|----------|-------|-----------|--------|----------|
| oc_zero_cost | 191 | LGBM **51.2%** | 51.0% | +0.07% | +1.7% | **FAIL** |
| oc_with_costs | 191 | 51.2% | 51.0% | +0.07% | −17.6% | **FAIL** |

**Decision:** `NO_GROSS_EDGE_EXPAND_UNIVERSE_OR_OBJECTIVE` — do **not** revisit
stops/holds/threshold tuning. Next bounded work should change **universe**
and/or **prediction objective**, not chase the 55% gate on this feature set.
