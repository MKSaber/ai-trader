"""Rolling walk-forward evaluation with trade-style stop/TP scoring.

Protocol: train on prior `train_sessions`, test on next `test_sessions`,
then slide forward by `step_sessions` across available history.

Correctness notes (see docs/DIAGNOSIS.md):
- Naive baselines use the *training* fold only.
- Label purge drops train rows whose next-session outcome overlaps the test window.
- Main research comparison defaults to long-only.
- Stamp duty applies to long purchases only; named SDRT scenarios are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler

from app.services.eval.baselines import naive_test_scores
from app.services.eval.costs import (
    CostAssumptions,
    estimate_round_trip_cost_fraction,
    load_cost_assumptions,
)
from app.services.features.pipeline import feature_matrix
from app.services.models.train import holdout_success_verdict

try:
    import lightgbm as lgb

    _HAS_LIGHTGBM = True
except OSError:
    lgb = None  # type: ignore[assignment]
    _HAS_LIGHTGBM = False

ExecutionMode = Literal["stop_tp_costs", "oc_zero_cost", "oc_with_costs"]


@dataclass
class FoldSpec:
    """One rolling window."""

    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    n_train: int
    n_test: int


def _session_dates(index: pd.Index) -> np.ndarray:
    return np.array(
        [pd.Timestamp(d).date() for d in pd.to_datetime(index)],
        dtype=object,
    )


def iter_rolling_folds(
    session_dates: np.ndarray,
    *,
    train_sessions: int = 85,
    test_sessions: int = 5,
    step_sessions: int = 5,
    max_folds: int | None = None,
) -> list[tuple[np.ndarray, np.ndarray, FoldSpec]]:
    """Build sliding chronological folds (no leakage across the cut)."""
    uniq = np.array(sorted(set(session_dates)), dtype=object)
    need = train_sessions + test_sessions
    if len(uniq) < need:
        raise ValueError(
            f"Need >= {need} unique sessions; have {len(uniq)}"
        )

    folds: list[tuple[np.ndarray, np.ndarray, FoldSpec]] = []
    start_i = 0
    fold_i = 0
    while start_i + need <= len(uniq):
        train_set = set(uniq[start_i : start_i + train_sessions])
        test_set = set(
            uniq[
                start_i
                + train_sessions : start_i
                + train_sessions
                + test_sessions
            ]
        )
        train_idx = np.array([d in train_set for d in session_dates])
        test_idx = np.array([d in test_set for d in session_dates])
        folds.append(
            (
                train_idx,
                test_idx,
                FoldSpec(
                    fold=fold_i,
                    train_start=min(train_set),
                    train_end=max(train_set),
                    test_start=min(test_set),
                    test_end=max(test_set),
                    n_train=int(train_idx.sum()),
                    n_test=int(test_idx.sum()),
                ),
            )
        )
        fold_i += 1
        start_i += step_sessions
        if max_folds is not None and fold_i >= max_folds:
            break
    if not folds:
        raise ValueError("No rolling folds could be constructed")
    return folds


def apply_label_purge(
    train_idx: np.ndarray,
    session_dates: np.ndarray,
    next_session: dict[tuple[int, date], date],
    instrument_ids: np.ndarray,
    test_start: date,
) -> np.ndarray:
    """Drop train rows whose next-session label outcome is on/after test_start.

    For target_next_session_oc, the label for session T uses T+1 OHLC.
    Those T+1 prices must not appear in the test window.
    """
    purged = train_idx.copy()
    for i in np.where(train_idx)[0]:
        d = session_dates[i]
        iid = int(instrument_ids[i])
        nxt = next_session.get((iid, d))
        if nxt is None or nxt >= test_start:
            purged[i] = False
    return purged


def _fit_predictors(
    x_train: np.ndarray,
    y_reg_train: np.ndarray,
    y_clf_train: np.ndarray,
    x_test: np.ndarray,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Fit compact model suite; return name -> (reg_pred, prob_up)."""
    n_test = len(x_test)
    reg_n, prob_n, _meta = naive_test_scores(y_clf_train, n_test)
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {
        "naive": (reg_n, prob_n),
    }
    # Constant train probability (diagnostic baseline)
    out["naive_const_p"] = (
        np.zeros(n_test),
        np.full(n_test, float(np.mean(y_clf_train)) if len(y_clf_train) else 0.5),
    )

    ridge = Ridge(alpha=1.0, random_state=42)
    ridge.fit(x_train, y_reg_train)
    ridge_pred = ridge.predict(x_test)
    out["ridge"] = (ridge_pred, 1 / (1 + np.exp(-ridge_pred * 10)))

    if len(np.unique(y_clf_train)) >= 2:
        logit = LogisticRegression(max_iter=400, C=1.0, random_state=42)
        logit.fit(x_train, y_clf_train)
        prob = logit.predict_proba(x_test)[:, 1]
        out["logistic"] = (prob - 0.5, prob)

    if _HAS_LIGHTGBM:
        tree = lgb.LGBMRegressor(
            n_estimators=60,
            learning_rate=0.05,
            max_depth=3,
            min_child_samples=20,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            verbosity=-1,
        )
        tree.fit(x_train, y_reg_train)
        pred = tree.predict(x_test)
        out["lightgbm"] = (pred, 1 / (1 + np.exp(-pred * 10)))
    return out


def _simulate_trade(
    side: str,
    entry: float,
    high: float,
    low: float,
    close: float,
    stop: float,
    take_profit: float,
    costs: CostAssumptions,
    *,
    execution_mode: ExecutionMode = "stop_tp_costs",
) -> dict[str, Any]:
    """One-session OHLC path with explicit cost/side handling."""
    if execution_mode == "oc_zero_cost":
        gross = (close / entry) - 1.0 if side == "long" else (entry / close) - 1.0
        return {
            "exit_reason": "session_close",
            "gross_return": float(gross),
            "net_return": float(gross),
            "cost_frac": 0.0,
            "win": gross > 0,
        }

    if execution_mode == "oc_with_costs":
        gross = (close / entry) - 1.0 if side == "long" else (entry / close) - 1.0
        cost_frac = estimate_round_trip_cost_fraction(costs, side=side)
        net = gross - cost_frac
        return {
            "exit_reason": "session_close",
            "gross_return": float(gross),
            "net_return": float(net),
            "cost_frac": float(cost_frac),
            "win": net > 0,
        }

    # stop_tp_costs
    cost_frac = estimate_round_trip_cost_fraction(costs, side=side)
    if side == "long":
        hit_stop = low <= stop
        hit_tp = high >= take_profit
        if hit_stop and hit_tp:
            exit_px, reason = stop, "stop_loss_ambiguous"
        elif hit_stop:
            exit_px, reason = stop, "stop_loss"
        elif hit_tp:
            exit_px, reason = take_profit, "take_profit"
        else:
            exit_px, reason = close, "session_close"
        gross = (exit_px / entry) - 1.0
    else:
        hit_stop = high >= stop
        hit_tp = low <= take_profit
        if hit_stop and hit_tp:
            exit_px, reason = stop, "stop_loss_ambiguous"
        elif hit_stop:
            exit_px, reason = stop, "stop_loss"
        elif hit_tp:
            exit_px, reason = take_profit, "take_profit"
        else:
            exit_px, reason = close, "session_close"
        gross = (entry / exit_px) - 1.0
    net = gross - cost_frac
    return {
        "exit_reason": reason,
        "gross_return": float(gross),
        "net_return": float(net),
        "cost_frac": float(cost_frac),
        "win": net > 0,
    }


def _trade_levels(
    side: str,
    entry: float,
    atr_norm: float,
    *,
    stop_atr: float = 1.5,
    tp_atr: float = 2.0,
) -> tuple[float, float]:
    """ATR-based stop and take-profit distances."""
    dist = max(float(atr_norm), 0.004)
    if side == "long":
        stop = entry * (1.0 - stop_atr * dist)
        tp = entry * (1.0 + tp_atr * dist)
    else:
        stop = entry * (1.0 + stop_atr * dist)
        tp = entry * (1.0 - tp_atr * dist)
    return stop, tp


def _equity_curve(
    trades: list[dict[str, Any]],
    *,
    starting_cash: float = 100_000.0,
    notional_frac: float = 0.02,
) -> dict[str, Any]:
    """Cash-constrained sequential equity (fixed fraction per trade, no overlap)."""
    cash = starting_cash
    equity = starting_cash
    peak = starting_cash
    max_dd = 0.0
    path: list[dict[str, Any]] = []
    for t in trades:
        notional = equity * notional_frac
        if notional <= 0 or cash < notional * 0.5:
            continue
        pnl = notional * float(t["net_return"])
        cash += pnl
        equity = cash
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak else 0.0
        max_dd = max(max_dd, dd)
        path.append(
            {
                "entry_date": t.get("entry_date"),
                "equity": equity,
                "pnl": pnl,
                "side": t.get("side"),
            }
        )
    compounded = (equity / starting_cash) - 1.0 if starting_cash else 0.0
    return {
        "starting_cash": starting_cash,
        "ending_equity": equity,
        "compounded_return": compounded,
        "max_drawdown": max_dd,
        "n_funded_trades": len(path),
        "notional_frac": notional_frac,
        "note": (
            "Non-overlapping fixed-fraction sizing; sum of fractional "
            "trade returns is NOT portfolio growth — this curve is."
        ),
    }


def run_rolling_walkforward(
    feature_frame: pd.DataFrame,
    bars_frame: pd.DataFrame,
    *,
    train_sessions: int = 85,
    test_sessions: int = 5,
    step_sessions: int = 5,
    max_folds: int | None = None,
    min_prob: float = 0.55,
    long_only: bool = True,
    execution_mode: ExecutionMode = "stop_tp_costs",
    stamp_scenario: str = "stress_1pct",
    purge_label_overlap: bool = True,
    starting_cash: float = 100_000.0,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Rolling OOS directional + execution diagnostics.

    Signal uses features as-of session T close. Trade enters next session open.
    """
    del artifact_dir
    frame = feature_frame.copy()
    if frame.empty:
        return {"status": "insufficient_data", "message": "Empty feature frame"}

    sessions = _session_dates(frame.index)
    instrument_ids = frame["instrument_id"].to_numpy(dtype=int)
    folds = iter_rolling_folds(
        sessions,
        train_sessions=train_sessions,
        test_sessions=test_sessions,
        step_sessions=step_sessions,
        max_folds=max_folds,
    )
    x, _cols = feature_matrix(frame)
    y_reg = frame["target_next_session_oc"].to_numpy(dtype=float)
    y_clf = (y_reg > 0).astype(int)
    costs = load_cost_assumptions(stamp_scenario=stamp_scenario)

    bar_lookup: dict[tuple[int, date], dict[str, float]] = {}
    if not bars_frame.empty:
        for idx, row in bars_frame.iterrows():
            d = pd.Timestamp(idx).date() if hasattr(idx, "year") else pd_to_date(idx)
            bar_lookup[(int(row["instrument_id"]), d)] = {
                "open": float(row["open_gbp"]),
                "high": float(row["high_gbp"]),
                "low": float(row["low_gbp"]),
                "close": float(row["close_gbp"]),
            }

    by_inst: dict[int, list[date]] = {}
    for idx, row in frame.iterrows():
        d = pd.Timestamp(idx).date()
        iid = int(row["instrument_id"])
        by_inst.setdefault(iid, []).append(d)
    next_session: dict[tuple[int, date], date] = {}
    for iid, dates in by_inst.items():
        ordered = sorted(set(dates))
        for i, d in enumerate(ordered[:-1]):
            next_session[(iid, d)] = ordered[i + 1]

    model_fold_acc: dict[str, list[float]] = {}
    all_trades: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    oos_rows = 0
    purged_rows_total = 0

    for train_idx, test_idx, spec in folds:
        if purge_label_overlap:
            purged = apply_label_purge(
                train_idx,
                sessions,
                next_session,
                instrument_ids,
                spec.test_start,
            )
            purged_rows_total += int(train_idx.sum() - purged.sum())
            train_idx = purged
        if train_idx.sum() < 30 or test_idx.sum() < 1:
            continue
        imputer = SimpleImputer(strategy="median")
        scaler = StandardScaler()
        x_tr = scaler.fit_transform(imputer.fit_transform(x[train_idx]))
        x_te = scaler.transform(imputer.transform(x[test_idx]))
        preds = _fit_predictors(
            x_tr, y_reg[train_idx], y_clf[train_idx], x_te
        )
        fold_acc: dict[str, float] = {}
        y_true = y_clf[test_idx]
        for name, (_reg, prob) in preds.items():
            # For naive majority, threshold at 0.5 on {0,1} probs still works
            acc = float(accuracy_score(y_true, (prob >= 0.5).astype(int)))
            fold_acc[name] = acc
            model_fold_acc.setdefault(name, []).append(acc)

        trade_model = (
            "logistic"
            if "logistic" in preds
            else ("ridge" if "ridge" in preds else "naive")
        )
        _reg, prob = preds[trade_model]
        test_positions = np.where(test_idx)[0]
        fold_trades = 0
        fold_wins = 0
        fold_net = 0.0
        fold_gross = 0.0
        for local_i, row_i in enumerate(test_positions):
            oos_rows += 1
            row = frame.iloc[row_i]
            iid = int(row["instrument_id"])
            asof = pd.Timestamp(frame.index[row_i]).date()
            p_up = float(prob[local_i])
            if p_up >= min_prob:
                side = "long"
            elif (not long_only) and p_up <= (1.0 - min_prob):
                side = "short"
            else:
                continue
            nxt = next_session.get((iid, asof))
            if nxt is None:
                continue
            bar = bar_lookup.get((iid, nxt))
            if not bar:
                continue
            entry = bar["open"]
            atr_n = float(row.get("atr_norm_14", 0.01) or 0.01)
            stop, tp = _trade_levels(side, entry, atr_n)
            sim = _simulate_trade(
                side,
                entry,
                bar["high"],
                bar["low"],
                bar["close"],
                stop,
                tp,
                costs,
                execution_mode=execution_mode,
            )
            fold_trades += 1
            fold_wins += int(sim["win"])
            fold_net += sim["net_return"]
            fold_gross += sim["gross_return"]
            all_trades.append(
                {
                    "fold": spec.fold,
                    "signal_date": asof.isoformat(),
                    "entry_date": nxt.isoformat(),
                    "instrument_id": iid,
                    "side": side,
                    "probability_up": p_up,
                    "model": trade_model,
                    "entry": entry,
                    "stop_loss": stop,
                    "take_profit": tp,
                    **sim,
                }
            )

        fold_summaries.append(
            {
                "fold": spec.fold,
                "train_start": spec.train_start.isoformat(),
                "train_end": spec.train_end.isoformat(),
                "test_start": spec.test_start.isoformat(),
                "test_end": spec.test_end.isoformat(),
                "n_train": int(train_idx.sum()),
                "n_test": spec.n_test,
                "accuracy": fold_acc,
                "trades": fold_trades,
                "win_rate": (fold_wins / fold_trades) if fold_trades else None,
                "sum_net_return": fold_net,
                "sum_gross_return": fold_gross,
            }
        )

    model_summary = []
    for name, accs in model_fold_acc.items():
        model_summary.append(
            {
                "model_type": name,
                "mean_accuracy": float(np.mean(accs)),
                "std_accuracy": float(np.std(accs)) if len(accs) > 1 else 0.0,
                "folds": len(accs),
                "accuracy": float(np.mean(accs)),
                "n": oos_rows,
            }
        )

    n_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["win"])
    net_total = float(sum(t["net_return"] for t in all_trades)) if all_trades else 0.0
    gross_total = (
        float(sum(t["gross_return"] for t in all_trades)) if all_trades else 0.0
    )
    by_reason: dict[str, int] = {}
    for t in all_trades:
        by_reason[t["exit_reason"]] = by_reason.get(t["exit_reason"], 0) + 1

    recommendations = _latest_recommendations(
        frame,
        bars_frame,
        model_summary,
        min_prob=min_prob,
        costs=costs,
        long_only=long_only,
    )
    equity = _equity_curve(all_trades, starting_cash=starting_cash)

    # Gate excludes diagnostic naive_const_p
    gate_models = [
        {
            "model_type": m["model_type"],
            "accuracy": m["mean_accuracy"],
            "n": max(10, m["folds"] * test_sessions),
        }
        for m in model_summary
        if m["model_type"] != "naive_const_p"
    ]
    verdict = holdout_success_verdict(
        gate_models, min_accuracy=0.55, min_test_rows=10
    )
    trader_passed = bool(
        verdict["passed"] and n_trades >= 10 and equity["compounded_return"] > 0
    )

    return {
        "status": "ok",
        "protocol": {
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
            "step_sessions": step_sessions,
            "folds": len(fold_summaries),
            "min_prob": min_prob,
            "long_only": long_only,
            "execution_mode": execution_mode,
            "stamp_scenario": stamp_scenario,
            "purge_label_overlap": purge_label_overlap,
            "purged_train_rows": purged_rows_total,
            "period_start": fold_summaries[0]["train_start"]
            if fold_summaries
            else None,
            "period_end": fold_summaries[-1]["test_end"]
            if fold_summaries
            else None,
            "costs": costs.to_dict(),
        },
        "models": model_summary,
        "folds": fold_summaries,
        "direction_success": verdict,
        "trading": {
            "n_trades": n_trades,
            "win_rate": (wins / n_trades) if n_trades else None,
            "sum_gross_return": gross_total,
            "sum_net_return": net_total,
            "avg_gross_return": (gross_total / n_trades) if n_trades else None,
            "avg_net_return": (net_total / n_trades) if n_trades else None,
            "exit_reasons": by_reason,
            "costs": costs.to_dict(),
            "equity_curve": equity,
            "passed": trader_passed,
            "criterion": (
                "Directional gate passed AND >=10 trades AND "
                "cash equity compounded return > 0 "
                f"(execution_mode={execution_mode}, long_only={long_only})"
            ),
        },
        "recommendations": recommendations,
        "sample_trades": all_trades[-20:],
        "note": (
            "Rolling walk-forward. Sum of fractional trade returns is not "
            "portfolio growth — see trading.equity_curve. "
            "Passing does not prove live edge."
        ),
    }


def _latest_recommendations(
    feature_frame: pd.DataFrame,
    bars_frame: pd.DataFrame,
    model_summary: list[dict[str, Any]],
    *,
    min_prob: float,
    costs: CostAssumptions,
    long_only: bool = True,
) -> list[dict[str, Any]]:
    """Fit on all-but-last-5 sessions; recommend on latest as-of rows."""
    sessions = _session_dates(feature_frame.index)
    uniq = np.array(sorted(set(sessions)), dtype=object)
    if len(uniq) < 90:
        return []
    train_set = set(uniq[:-5])
    test_set = set(uniq[-1:])
    train_idx = np.array([d in train_set for d in sessions])
    latest_idx = np.array([d in test_set for d in sessions])
    if not train_idx.any() or not latest_idx.any():
        return []

    x, _ = feature_matrix(feature_frame)
    y_reg = feature_frame["target_next_session_oc"].to_numpy(dtype=float)
    y_clf = (y_reg > 0).astype(int)
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    x_tr = scaler.fit_transform(imputer.fit_transform(x[train_idx]))
    x_te = scaler.transform(imputer.transform(x[latest_idx]))
    preds = _fit_predictors(x_tr, y_reg[train_idx], y_clf[train_idx], x_te)
    ranked = sorted(
        [
            m
            for m in model_summary
            if m["model_type"] not in {"naive", "naive_const_p"}
        ],
        key=lambda m: m["mean_accuracy"],
        reverse=True,
    )
    model_name = ranked[0]["model_type"] if ranked else "ridge"
    if model_name not in preds:
        model_name = next(iter(preds.keys()))
    _reg, prob = preds[model_name]

    tips: list[dict[str, Any]] = []
    positions = np.where(latest_idx)[0]
    for local_i, row_i in enumerate(positions):
        row = feature_frame.iloc[row_i]
        iid = int(row["instrument_id"])
        asof = pd.Timestamp(feature_frame.index[row_i]).date()
        p_up = float(prob[local_i])
        if p_up >= min_prob:
            side = "buy"
        elif (not long_only) and p_up <= (1.0 - min_prob):
            side = "sell_short"
        else:
            tips.append(
                {
                    "instrument_id": iid,
                    "as_of": asof.isoformat(),
                    "action": "no_trade",
                    "probability_up": p_up,
                    "model": model_name,
                    "reason": "Probability inside no-trade band",
                }
            )
            continue
        entry = 0.0
        if not bars_frame.empty:
            for b_idx, b_row in bars_frame.iterrows():
                if int(b_row["instrument_id"]) != iid:
                    continue
                if pd.Timestamp(b_idx).date() != asof:
                    continue
                entry = float(b_row["close_gbp"])
                break
        if entry <= 0:
            continue
        atr_n = float(row.get("atr_norm_14", 0.01) or 0.01)
        trade_side = "long" if side == "buy" else "short"
        stop, tp = _trade_levels(trade_side, entry, atr_n)
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        tips.append(
            {
                "instrument_id": iid,
                "as_of": asof.isoformat(),
                "action": side,
                "probability_up": p_up,
                "model": model_name,
                "entry_ref": entry,
                "stop_loss": stop,
                "take_profit": tp,
                "risk_reward": (reward / risk) if risk else None,
                "estimated_round_trip_cost_frac": estimate_round_trip_cost_fraction(
                    costs, side=trade_side
                ),
                "note": (
                    "Research levels only — not a live order. "
                    "entry_ref is last close; live entry would be next open. "
                    "Forecast is next-session open-to-close, not intraday timing."
                ),
            }
        )
    return tips


def pd_to_date(idx) -> date:
    """Normalize index to date."""
    if hasattr(idx, "date"):
        return idx.date()
    return pd.Timestamp(idx).date()
