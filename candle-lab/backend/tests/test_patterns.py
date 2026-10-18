"""Boundary tests for patterns-v1 detectors."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.patterns import detect_closed_patterns
from app.paper import simulate_long_bar


def _bar(ts, o, h, l, c, closed=True):
    return {
        "bar_start": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 1,
        "closed": closed,
    }


def test_bullish_engulfing_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    # downtrend warm-up
    px = 100.0
    for i in range(6):
        rows.append(_bar(t0 + timedelta(minutes=5 * i), px, px + 0.2, px - 1, px - 0.8))
        px -= 0.8
    # red then green engulfing
    rows.append(_bar(t0 + timedelta(minutes=30), 95, 95.2, 94, 94.2))  # red
    rows.append(_bar(t0 + timedelta(minutes=35), 94.1, 96.5, 94.0, 96.2))  # green engulfs
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "bullish_engulfing" for d in dets)


def test_bearish_engulfing_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    px = 90.0
    for i in range(6):
        rows.append(_bar(t0 + timedelta(minutes=5 * i), px, px + 1, px - 0.2, px + 0.8))
        px += 0.8
    rows.append(_bar(t0 + timedelta(minutes=30), 95, 95.5, 94.8, 95.4))  # green
    rows.append(_bar(t0 + timedelta(minutes=35), 95.5, 95.6, 93.5, 93.8))  # red engulfs
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "bearish_engulfing" for d in dets)


def test_hammer_requires_downtrend_and_wick():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    px = 100.0
    for i in range(6):
        rows.append(_bar(t0 + timedelta(minutes=5 * i), px, px + 0.1, px - 1, px - 0.9))
        px -= 0.9
    # hammer: small body near high, long lower wick, tiny upper wick
    rows.append(_bar(t0 + timedelta(minutes=30), 93.8, 94.0, 92.0, 94.0))
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "hammer" for d in dets)


def test_shooting_star_requires_uptrend():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    px = 90.0
    for i in range(6):
        rows.append(_bar(t0 + timedelta(minutes=5 * i), px, px + 1, px - 0.1, px + 0.9))
        px += 0.9
    # shooting star: small body near low, long upper wick, tiny lower wick
    rows.append(_bar(t0 + timedelta(minutes=30), 96.0, 98.5, 96.0, 96.2))
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "shooting_star" for d in dets)


def test_forming_bar_excluded_by_caller_convention():
    """Detector itself assumes df contains only closed bars."""
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = [_bar(t0, 10, 11, 9, 10.5, closed=False)]
    df = pd.DataFrame(rows)
    # With a single bar, no pattern
    assert detect_closed_patterns(df) == []


def test_ambiguous_stop_target_bounds():
    sim = simulate_long_bar(100, 99, 102, high=103, low=98, close=101)
    assert sim is not None
    assert sim.ambiguous is True
    assert sim.conservative_reason == "stop_first"
    assert sim.optimistic_reason == "target_first"


def test_duplicate_pattern_indices_stable():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    px = 100.0
    for i in range(6):
        rows.append(_bar(t0 + timedelta(minutes=5 * i), px, px + 0.2, px - 1, px - 0.8))
        px -= 0.8
    rows.append(_bar(t0 + timedelta(minutes=30), 95, 95.2, 94, 94.2))
    rows.append(_bar(t0 + timedelta(minutes=35), 94.1, 96.5, 94.0, 96.2))
    df = pd.DataFrame(rows)
    a = detect_closed_patterns(df)
    b = detect_closed_patterns(df)
    assert [d.pattern for d in a] == [d.pattern for d in b]
