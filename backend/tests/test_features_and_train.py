"""Feature as-of rules and chronological training smoke tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services.features.pipeline import build_daily_features
from app.services.models.train import (
    chronological_splits,
    fixed_session_holdout,
    holdout_success_verdict,
    train_all_models,
)


def _make_bars(n: int = 80) -> pd.DataFrame:
    start = date(2024, 1, 2)
    rows = []
    price = 100.0
    d = start
    while len(rows) < n:
        if d.weekday() < 5:
            o = price
            # Mix up/down days so classification targets are not single-class.
            shock = 1.0 + (((len(rows) * 7) % 11) - 5) * 0.003
            c = price * shock
            rows.append(
                {
                    "session_date": d,
                    "instrument_id": 1,
                    "open_gbp": o,
                    "high_gbp": max(o, c) * 1.01,
                    "low_gbp": min(o, c) * 0.99,
                    "close_gbp": c,
                    "volume": 1e6,
                }
            )
            price = c
        d += timedelta(days=1)
    frame = pd.DataFrame(rows).set_index("session_date")
    return frame


def test_features_exclude_insufficient_history() -> None:
    """Short series yields empty usable frame rather than fabricated values."""
    frame = _make_bars(5)
    feat = build_daily_features(frame)
    assert len(feat.frame) == 0 or feat.frame["mom_20d"].isna().all() or len(feat.frame) < 5


def test_chronological_not_random() -> None:
    """Walk-forward folds are time-ordered."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B").to_numpy()
    folds = chronological_splits(dates, n_folds=3)
    assert folds
    train_idx, test_idx = folds[-1]
    train_dates = dates[train_idx]
    test_dates = dates[test_idx]
    assert train_dates.max() <= test_dates.min()


def test_train_smoke(tmp_path) -> None:
    """Training produces interpretable ridge formula."""
    feat = build_daily_features(_make_bars(90))
    assert len(feat.frame) > 30
    results = train_all_models(feat.frame, tmp_path)
    types = {r.model_type for r in results}
    assert "naive" in types
    assert "ridge" in types
    ridge = next(r for r in results if r.model_type == "ridge")
    assert ridge.formula is not None
    assert "coefficients" in ridge.formula
    assert ridge.metrics.get("validation") == "chronological_walk_forward"


def test_fixed_holdout_90_5(tmp_path) -> None:
    """90-session train / 5-session test stays time-ordered."""
    feat = build_daily_features(_make_bars(130))
    assert len(pd.to_datetime(feat.frame.index).unique()) >= 95
    results = train_all_models(
        feat.frame,
        tmp_path,
        train_sessions=90,
        test_sessions=5,
    )
    ridge = next(r for r in results if r.model_type == "ridge")
    assert ridge.metrics["validation"] == "fixed_holdout_90train_5test"
    holdout = ridge.metrics["holdout"]
    assert holdout["unique_train_sessions"] == 90
    assert holdout["unique_test_sessions"] == 5
    assert holdout["train_end"] < holdout["test_start"]

    dates = pd.to_datetime(feat.frame.index).to_numpy()
    train_idx, test_idx, _ = fixed_session_holdout(
        dates, train_sessions=90, test_sessions=5
    )
    assert dates[train_idx].max() < dates[test_idx].min()


def test_holdout_verdict_gate() -> None:
    """Success gate requires beating chance threshold and naive."""
    fail = holdout_success_verdict(
        [
            {"model_type": "naive", "accuracy": 0.5, "n": 25},
            {"model_type": "ridge", "accuracy": 0.52, "n": 25},
        ]
    )
    assert fail["passed"] is False
    ok = holdout_success_verdict(
        [
            {"model_type": "naive", "accuracy": 0.48, "n": 25},
            {"model_type": "lightgbm", "accuracy": 0.6, "n": 25},
        ]
    )
    assert ok["passed"] is True
