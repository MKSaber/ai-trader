"""Rolling walk-forward fold construction tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services.eval.rolling import iter_rolling_folds, run_rolling_walkforward
from app.services.features.pipeline import build_daily_features


def _bars(n: int = 200, instruments: int = 2) -> pd.DataFrame:
    start = date(2020, 1, 2)
    rows = []
    for iid in range(1, instruments + 1):
        price = 100.0 + iid
        d = start
        count = 0
        while count < n:
            if d.weekday() < 5:
                shock = 1.0 + (((count * 7 + iid) % 11) - 5) * 0.004
                o = price
                c = price * shock
                rows.append(
                    {
                        "session_date": d,
                        "instrument_id": iid,
                        "open_gbp": o,
                        "high_gbp": max(o, c) * 1.01,
                        "low_gbp": min(o, c) * 0.99,
                        "close_gbp": c,
                        "volume": 1e6,
                    }
                )
                price = c
                count += 1
            d += timedelta(days=1)
    return pd.DataFrame(rows).set_index("session_date")


def test_iter_rolling_folds_ordered() -> None:
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(120)],
        dtype=object,
    )
    # business-like: duplicate none, use weekdays only already sequential
    folds = iter_rolling_folds(
        dates, train_sessions=85, test_sessions=5, step_sessions=5
    )
    assert len(folds) >= 6
    _tr, te, spec = folds[0]
    assert spec.train_end < spec.test_start
    assert te.sum() == 5


def test_rolling_walkforward_smoke() -> None:
    bars = _bars(160, instruments=2)
    feat = build_daily_features(bars)
    assert len(pd.to_datetime(feat.frame.index).unique()) >= 90
    result = run_rolling_walkforward(
        feat.frame,
        bars,
        train_sessions=85,
        test_sessions=5,
        step_sessions=5,
        max_folds=3,
        min_prob=0.55,
    )
    assert result["status"] == "ok"
    assert result["protocol"]["folds"] == 3
    assert "trading" in result
    assert "recommendations" in result
