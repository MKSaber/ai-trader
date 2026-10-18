"""Train baselines and challengers with chronological validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, r2_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from app.services.features.pipeline import FEATURE_DEFINITIONS, feature_matrix

try:
    import lightgbm as lgb

    _HAS_LIGHTGBM = True
except OSError:
    # Missing native OpenMP (common on macOS without libomp).
    lgb = None  # type: ignore[assignment]
    _HAS_LIGHTGBM = False


@dataclass
class TrainResult:
    """Artifacts and metrics from a training run."""

    model_type: str
    version: str
    artifact_path: str | None
    formula: dict[str, Any] | None
    feature_importance: dict[str, Any] | None
    metrics: dict[str, Any]
    train_start: date
    train_end: date
    feature_names: list[str]
    horizon: str


def _purge_mask(
    dates: pd.DatetimeIndex | pd.Index,
    train_end: date,
    embargo_sessions: int = 1,
) -> np.ndarray:
    """Exclude overlapping label periods after train_end (simple embargo)."""
    # Labels use next-session returns; embargo next session after train_end
    cutoff = pd.Timestamp(train_end) + pd.tseries.offsets.BDay(embargo_sessions)
    return np.asarray(pd.to_datetime(dates) <= cutoff)


def chronological_splits(
    dates: np.ndarray,
    n_folds: int = 3,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Shared calendar walk-forward folds (no random split)."""
    uniq = np.array(sorted(pd.to_datetime(pd.unique(dates))))
    if len(uniq) < n_folds + 2:
        # Single holdout: 70/30 chronological
        cut = int(len(uniq) * 0.7)
        train_dates = set(uniq[:cut])
        test_dates = set(uniq[cut:])
        train_idx = np.array([d in train_dates for d in pd.to_datetime(dates)])
        test_idx = np.array([d in test_dates for d in pd.to_datetime(dates)])
        return [(train_idx, test_idx)]

    folds: list[tuple[np.ndarray, np.ndarray]] = []
    fold_size = len(uniq) // (n_folds + 1)
    for i in range(1, n_folds + 1):
        train_end_i = fold_size * i
        test_end_i = fold_size * (i + 1)
        train_set = set(uniq[:train_end_i])
        test_set = set(uniq[train_end_i:test_end_i])
        train_idx = np.array([d in train_set for d in pd.to_datetime(dates)])
        test_idx = np.array([d in test_set for d in pd.to_datetime(dates)])
        if train_idx.sum() and test_idx.sum():
            folds.append((train_idx, test_idx))
    return folds


def fixed_session_holdout(
    dates: np.ndarray,
    *,
    train_sessions: int = 90,
    test_sessions: int = 5,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Train on the prior N sessions; test on the most recent M sessions.

    Sessions are unique trading dates shared across symbols (no random split).
    Rows on the same session stay entirely in train or entirely in test.
    """
    # Normalize to python date so set membership is stable across
    # Timestamp / datetime64 / tz-aware values.
    session_dates = np.array(
        [pd.Timestamp(d).date() for d in pd.to_datetime(dates)],
        dtype=object,
    )
    uniq = np.array(sorted(set(session_dates)), dtype=object)
    need = train_sessions + test_sessions
    if len(uniq) < need:
        raise ValueError(
            f"Need at least {need} unique sessions for "
            f"{train_sessions}d train / {test_sessions}d test; have {len(uniq)}"
        )
    test_set = set(uniq[-test_sessions:])
    train_set = set(uniq[-need:-test_sessions])
    train_idx = np.array([d in train_set for d in session_dates])
    test_idx = np.array([d in test_set for d in session_dates])
    if not train_idx.any() or not test_idx.any():
        raise ValueError("Holdout split produced an empty train or test fold")
    meta = {
        "train_sessions": train_sessions,
        "test_sessions": test_sessions,
        "train_start": min(train_set).isoformat(),
        "train_end": max(train_set).isoformat(),
        "test_start": min(test_set).isoformat(),
        "test_end": max(test_set).isoformat(),
        "n_train_rows": int(train_idx.sum()),
        "n_test_rows": int(test_idx.sum()),
        "unique_train_sessions": len(train_set),
        "unique_test_sessions": len(test_set),
    }
    return train_idx, test_idx, meta


def holdout_success_verdict(
    model_metrics: list[dict[str, Any]],
    *,
    min_accuracy: float = 0.55,
    min_test_rows: int = 10,
) -> dict[str, Any]:
    """Transparent pass/fail for a fixed holdout — not a trading green light."""
    usable = [
        m
        for m in model_metrics
        if m.get("model_type") not in {"naive", "momentum"}
        and m.get("accuracy") is not None
    ]
    if not usable:
        return {
            "passed": False,
            "reason": "no_fitted_models",
            "criterion": (
                f"Best non-baseline accuracy >= {min_accuracy:.0%} "
                f"on >= {min_test_rows} test rows, and beat naive"
            ),
        }
    best = max(usable, key=lambda m: float(m["accuracy"]))
    naive = next(
        (m for m in model_metrics if m.get("model_type") == "naive"),
        None,
    )
    n_test = int(best.get("n") or 0)
    acc = float(best["accuracy"])
    naive_acc = float(naive["accuracy"]) if naive and naive.get("accuracy") is not None else 0.5
    passed = (
        n_test >= min_test_rows
        and acc >= min_accuracy
        and acc > naive_acc
    )
    return {
        "passed": passed,
        "best_model": best.get("model_type"),
        "best_accuracy": acc,
        "naive_accuracy": naive_acc,
        "n_test": n_test,
        "criterion": (
            f"Best non-baseline accuracy >= {min_accuracy:.0%} "
            f"on >= {min_test_rows} test rows, and beat naive "
            f"({naive_acc:.1%})"
        ),
        "reason": (
            "passed_holdout_gate"
            if passed
            else (
                "insufficient_test_rows"
                if n_test < min_test_rows
                else (
                    "did_not_beat_chance_threshold"
                    if acc < min_accuracy
                    else "did_not_beat_naive"
                )
            )
        ),
        "note": (
            "Passing this gate means directional accuracy looked better than "
            "a simple baseline on one short holdout — not proven edge after costs."
        ),
    }


def _version_tag(model_type: str, train_end: date, payload: str) -> str:
    digest = hashlib.sha256(payload.encode()).hexdigest()[:8]
    return f"{model_type}-{train_end.isoformat()}-{digest}"


def train_all_models(
    feature_frame: pd.DataFrame,
    artifact_dir: Path,
    horizon: str = "next_session_open_to_close",
    *,
    train_sessions: int | None = None,
    test_sessions: int | None = None,
) -> list[TrainResult]:
    """Fit naive, momentum, ridge/logistic, and LightGBM challenger.

    Default: chronological walk-forward folds.
    With train_sessions + test_sessions: fixed holdout
    (prior N sessions train, last M sessions test).
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    frame = feature_frame.copy()
    dates = pd.to_datetime(frame.index)
    x, cols = feature_matrix(frame)
    y_reg = frame["target_next_session_oc"].to_numpy(dtype=float)
    y_clf = (y_reg > 0).astype(int)

    holdout_meta: dict[str, Any] | None = None
    if train_sessions is not None and test_sessions is not None:
        train_idx, test_idx, holdout_meta = fixed_session_holdout(
            dates.to_numpy(),
            train_sessions=train_sessions,
            test_sessions=test_sessions,
        )
        train_start = date.fromisoformat(holdout_meta["train_start"])
        train_end = date.fromisoformat(holdout_meta["train_end"])
        validation_label = (
            f"fixed_holdout_{train_sessions}train_{test_sessions}test"
        )
    else:
        folds = chronological_splits(dates.to_numpy())
        train_idx, test_idx = folds[-1]
        train_start = pd.to_datetime(dates.min()).date()
        train_end = pd.to_datetime(dates.max()).date()
        validation_label = "chronological_walk_forward"

    results: list[TrainResult] = []

    # --- Naive baseline: predict 0 return / 0.5 prob (evaluated on test) ---
    naive_metrics = _eval_predictions(
        y_reg[test_idx],
        np.zeros(int(test_idx.sum())),
        y_clf[test_idx],
        np.full(int(test_idx.sum()), 0.5),
    )
    results.append(
        TrainResult(
            model_type="naive",
            version=_version_tag("naive", train_end, "zero"),
            artifact_path=None,
            formula={
                "type": "naive",
                "expression": "expected_return = 0",
                "probability_up": 0.5,
                "horizon": horizon,
                "note": "No demonstrated edge; baseline only",
            },
            feature_importance=None,
            metrics=naive_metrics,
            train_start=train_start,
            train_end=train_end,
            feature_names=[],
            horizon=horizon,
        )
    )

    # --- Momentum baseline: sign of mom_20d (evaluated on test) ---
    if "mom_20d" in frame.columns:
        mom = frame["mom_20d"].to_numpy(dtype=float)
        mom_pred = np.nan_to_num(mom, nan=0.0)
        mom_prob = 1 / (1 + np.exp(-5 * mom_pred))
        mom_metrics = _eval_predictions(
            y_reg[test_idx],
            mom_pred[test_idx],
            y_clf[test_idx],
            mom_prob[test_idx],
        )
        results.append(
            TrainResult(
                model_type="momentum",
                version=_version_tag("momentum", train_end, "mom20"),
                artifact_path=None,
                formula={
                    "type": "momentum",
                    "expression": "expected_return ≈ mom_20d; P(up)=sigmoid(5*mom_20d)",
                    "horizon": horizon,
                },
                feature_importance={"mom_20d": 1.0},
                metrics=mom_metrics,
                train_start=train_start,
                train_end=train_end,
                feature_names=["mom_20d"],
                horizon=horizon,
            )
        )

    # Fit linear / tree on train fold only; score holdout / OOS test
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    x_train = imputer.fit_transform(x[train_idx])
    x_train = scaler.fit_transform(x_train)
    x_test = scaler.transform(imputer.transform(x[test_idx]))

    # Ridge regression
    ridge = Ridge(alpha=1.0, random_state=42)
    ridge.fit(x_train, y_reg[train_idx])
    ridge_pred = ridge.predict(x_test)
    ridge_prob = 1 / (1 + np.exp(-ridge_pred * 10))
    ridge_metrics = _eval_predictions(
        y_reg[test_idx], ridge_pred, y_clf[test_idx], ridge_prob
    )
    ridge_path = artifact_dir / "ridge.joblib"
    joblib.dump(
        {"model": ridge, "imputer": imputer, "scaler": scaler, "features": cols},
        ridge_path,
    )
    formula = {
        "type": "ridge",
        "intercept": float(ridge.intercept_),
        "coefficients": {c: float(v) for c, v in zip(cols, ridge.coef_)},
        "scaling": "StandardScaler fit on training fold only",
        "imputer": "median (train only)",
        "horizon": horizon,
        "train_dates": [train_start.isoformat(), train_end.isoformat()],
        "expression": _linear_expression(ridge.intercept_, cols, ridge.coef_),
    }
    results.append(
        TrainResult(
            model_type="ridge",
            version=_version_tag("ridge", train_end, json.dumps(formula, sort_keys=True)),
            artifact_path=str(ridge_path),
            formula=formula,
            feature_importance={
                c: abs(float(v)) for c, v in zip(cols, ridge.coef_)
            },
            metrics=ridge_metrics,
            train_start=train_start,
            train_end=train_end,
            feature_names=cols,
            horizon=horizon,
        )
    )

    # Logistic (skip when training fold is single-class)
    if len(np.unique(y_clf[train_idx])) >= 2:
        logit = LogisticRegression(max_iter=500, C=1.0, random_state=42)
        logit.fit(x_train, y_clf[train_idx])
        logit_prob = logit.predict_proba(x_test)[:, 1]
        logit_pred = logit_prob - 0.5
        logit_metrics = _eval_predictions(
            y_reg[test_idx], logit_pred, y_clf[test_idx], logit_prob
        )
        logit_path = artifact_dir / "logistic.joblib"
        joblib.dump(
            {
                "model": logit,
                "imputer": imputer,
                "scaler": scaler,
                "features": cols,
            },
            logit_path,
        )
        coef = logit.coef_.ravel()
        logit_formula = {
            "type": "logistic",
            "intercept": float(logit.intercept_.ravel()[0]),
            "coefficients": {c: float(v) for c, v in zip(cols, coef)},
            "scaling": "StandardScaler fit on training fold only",
            "horizon": horizon,
            "expression": (
                "P(up) = sigmoid("
                + _linear_expression(logit.intercept_.ravel()[0], cols, coef)
                + ")"
            ),
            "note": (
                "Probability of positive next-session open-to-close return — "
                "not the probability a stop/target strategy succeeds."
            ),
        }
        results.append(
            TrainResult(
                model_type="logistic",
                version=_version_tag(
                    "logistic",
                    train_end,
                    json.dumps(logit_formula, sort_keys=True),
                ),
                artifact_path=str(logit_path),
                formula=logit_formula,
                feature_importance={
                    c: abs(float(v)) for c, v in zip(cols, coef)
                },
                metrics=logit_metrics,
                train_start=train_start,
                train_end=train_end,
                feature_names=cols,
                horizon=horizon,
            )
        )

    # Gradient-boosted tree challenger (LightGBM when available).
    if _HAS_LIGHTGBM:
        tree = lgb.LGBMRegressor(
            n_estimators=80,
            learning_rate=0.05,
            max_depth=3,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            verbosity=-1,
        )
        model_type = "lightgbm"
    else:
        tree = GradientBoostingRegressor(
            n_estimators=80,
            learning_rate=0.05,
            max_depth=3,
            random_state=42,
        )
        model_type = "gbrt"
    tree.fit(x_train, y_reg[train_idx])
    tree_pred = tree.predict(x_test)
    tree_prob = 1 / (1 + np.exp(-tree_pred * 10))
    tree_metrics = _eval_predictions(
        y_reg[test_idx], tree_pred, y_clf[test_idx], tree_prob
    )
    tree_path = artifact_dir / f"{model_type}.joblib"
    joblib.dump(
        {"model": tree, "imputer": imputer, "scaler": scaler, "features": cols},
        tree_path,
    )
    raw_importance = getattr(tree, "feature_importances_", np.ones(len(cols)))
    importance = {c: float(v) for c, v in zip(cols, raw_importance)}
    results.append(
        TrainResult(
            model_type=model_type,
            version=_version_tag(model_type, train_end, str(importance)),
            artifact_path=str(tree_path),
            formula={
                "type": model_type,
                "note": (
                    "Nonlinear model — feature importance below is not an "
                    "exact formula. Any surrogate would be an approximation."
                    + (
                        " LightGBM unavailable; used sklearn GBRT fallback."
                        if not _HAS_LIGHTGBM
                        else ""
                    )
                ),
                "horizon": horizon,
            },
            feature_importance=importance,
            metrics=tree_metrics,
            train_start=train_start,
            train_end=train_end,
            feature_names=cols,
            horizon=horizon,
        )
    )

    # Attach feature registry for transparency
    for r in results:
        r.metrics["feature_definitions"] = {
            k: FEATURE_DEFINITIONS[k]
            for k in r.feature_names
            if k in FEATURE_DEFINITIONS
        }
        r.metrics["n_train"] = int(train_idx.sum())
        r.metrics["n_test"] = int(test_idx.sum())
        r.metrics["validation"] = validation_label
        if holdout_meta:
            r.metrics["holdout"] = holdout_meta
    return results


def _linear_expression(
    intercept: float, cols: list[str], coef: np.ndarray
) -> str:
    parts = [f"{intercept:.6f}"]
    for c, v in zip(cols, coef):
        parts.append(f"{v:+.6f}*{c}")
    return " ".join(parts)


def _json_float(value: float | None) -> float | None:
    """Convert NaN/Inf to None for JSON/Postgres compatibility."""
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return float(value)


def _eval_predictions(
    y_true_reg: np.ndarray,
    y_pred_reg: np.ndarray,
    y_true_clf: np.ndarray,
    y_prob: np.ndarray,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "n": int(len(y_true_reg)),
        "r2": _json_float(
            float(r2_score(y_true_reg, y_pred_reg))
            if len(y_true_reg) > 1
            else None
        ),
        "accuracy": _json_float(
            float(accuracy_score(y_true_clf, (y_prob >= 0.5).astype(int)))
        ),
    }
    try:
        metrics["auc"] = _json_float(float(roc_auc_score(y_true_clf, y_prob)))
    except ValueError:
        metrics["auc"] = None
    # Ranking: IC approximation
    if len(y_true_reg) > 2:
        metrics["pearson_ic"] = _json_float(
            float(np.corrcoef(y_true_reg, y_pred_reg)[0, 1])
        )
    else:
        metrics["pearson_ic"] = None
    return metrics


def predict_with_artifact(
    artifact_path: str, feature_frame: pd.DataFrame
) -> np.ndarray:
    """Score rows using a saved artifact."""
    bundle = joblib.load(artifact_path)
    cols = bundle["features"]
    x = feature_frame.reindex(columns=cols).to_numpy(dtype=float)
    x = bundle["scaler"].transform(bundle["imputer"].transform(x))
    model = bundle["model"]
    if hasattr(model, "predict_proba"):
        return model.predict_proba(x)[:, 1]
    return model.predict(x)
