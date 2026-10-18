"""Regression tests for confirmed research-path correctness bugs."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services.eval.baselines import naive_test_scores, train_majority_class
from app.services.eval.costs import (
    STAMP_SCENARIOS,
    estimate_round_trip_cost_fraction,
    load_cost_assumptions,
)
from app.services.eval.rolling import apply_label_purge, iter_rolling_folds
from app.services.features.pipeline import build_daily_features


def _bars(n: int = 80) -> pd.DataFrame:
    start = date(2024, 1, 2)
    rows = []
    price = 100.0
    d = start
    while len(rows) < n:
        if d.weekday() < 5:
            shock = 1.0 + (((len(rows) * 7) % 11) - 5) * 0.003
            o, c = price, price * shock
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
    return pd.DataFrame(rows).set_index("session_date")


def test_naive_uses_train_majority_not_test_balance() -> None:
    """Naive must not equal the test-period up-rate by construction."""
    y_train = np.array([1, 1, 1, 0, 0])  # majority up
    y_test = np.array([0, 0, 0, 0, 0])  # all down
    _reg, prob, meta = naive_test_scores(y_train, len(y_test))
    assert meta["train_majority_class"] == 1.0
    assert train_majority_class(y_train) == 1
    # Always predict up from train majority → 0% on all-down test
    preds = (prob >= 0.5).astype(int)
    assert float(np.mean(preds == y_test)) == 0.0
    # Contrast: a test-derived "naive" would score 100% by predicting down
    assert float(np.mean(y_test == 0)) == 1.0


def test_short_does_not_pay_stamp() -> None:
    a = load_cost_assumptions(stamp_scenario="stress_1pct")
    assert estimate_round_trip_cost_fraction(a, side="long") > 0.01
    assert estimate_round_trip_cost_fraction(a, side="short") < 0.01


def test_sdrt_scenario_is_half_percent() -> None:
    assert STAMP_SCENARIOS["sdrt_0_5pct"] == 0.005
    a = load_cost_assumptions(stamp_scenario="sdrt_0_5pct")
    # 2*(10+5+5)/10000 + 0.005 = 0.004 + 0.005 = 0.009
    assert abs(estimate_round_trip_cost_fraction(a, side="long") - 0.009) < 1e-9


def test_label_purge_drops_overlapping_outcome() -> None:
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(20)], dtype=object
    )
    iids = np.ones(len(dates), dtype=int)
    next_map = {(1, dates[i]): dates[i + 1] for i in range(len(dates) - 1)}
    train_idx = np.array([True] * 10 + [False] * 10)
    test_start = dates[10]
    purged = apply_label_purge(train_idx, dates, next_map, iids, test_start)
    # Last train row (dates[9]) has next=dates[10] overlapping test → purged
    assert purged[9] is np.False_ or purged[9] == False
    assert purged[8] == True


def test_future_bars_do_not_change_earlier_features() -> None:
    """Causality: appending future sessions must not alter past feature rows."""
    bars = _bars(60)
    feat1 = build_daily_features(bars.iloc[:-5])
    feat2 = build_daily_features(bars)
    # Align on shared index dates
    shared = feat1.frame.index.intersection(feat2.frame.index)
    assert len(shared) > 10
    cols = [
        c
        for c in feat1.frame.columns
        if c not in {"target_next_session_oc", "target_up"}
    ]
    a = feat1.frame.loc[shared, cols].sort_index()
    b = feat2.frame.loc[shared, cols].sort_index()
    # Drop last shared row: its label/features may still be fine, but
    # rolling windows at the edge can differ if NaN drop changes membership.
    common = a.dropna().index.intersection(b.dropna().index)
    assert len(common) > 5
    pd.testing.assert_frame_equal(
        a.loc[common].reset_index(drop=True),
        b.loc[common].reset_index(drop=True),
        check_exact=False,
        rtol=1e-10,
    )


def test_rolling_folds_are_time_ordered() -> None:
    dates = np.array(
        [date(2020, 1, 1) + timedelta(days=i) for i in range(200)], dtype=object
    )
    folds = iter_rolling_folds(
        dates, train_sessions=85, test_sessions=5, step_sessions=5, max_folds=3
    )
    for tr, te, spec in folds:
        assert spec.train_end < spec.test_start
        assert tr.sum() and te.sum()
