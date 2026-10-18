"""Boundary tests for patterns-v1 / patterns-v2 detectors."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.patterns import DETECTOR_VERSION, detect_closed_patterns
from app.paper import simulate_long_bar


def _bar(ts, o, h, l, c, closed=True, volume=1000):
    return {
        "bar_start": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": volume,
        "closed": closed,
    }


def _downtrend_warmup(t0, n=12, px=110.0, step=1.0):
    rows = []
    for i in range(n):
        rows.append(
            _bar(
                t0 + timedelta(minutes=60 * i),
                px,
                px + 0.2,
                px - step,
                px - step + 0.1,
                volume=1000,
            )
        )
        px -= step
    return rows, px, n


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


def test_detector_version_is_patterns_v2():
    assert DETECTOR_VERSION == "patterns-v2"


def test_piercing_line_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows, px, n = _downtrend_warmup(t0)
    # long bearish then pierce (close above mid, below prior open)
    rows.append(_bar(t0 + timedelta(hours=n), 98, 98.2, 90, 90.5, volume=2000))
    rows.append(
        _bar(t0 + timedelta(hours=n + 1), 89.5, 95.5, 89.0, 94.8, volume=2500)
    )
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    pierce = [d for d in dets if d.pattern == "piercing_line"]
    assert pierce
    assert pierce[-1].conditions.get("volume_ratio") is not None


def test_bullish_harami_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows, px, n = _downtrend_warmup(t0)
    # long red, then small body inside
    rows.append(_bar(t0 + timedelta(hours=n), 100, 100.2, 90, 90.5, volume=2000))
    rows.append(
        _bar(t0 + timedelta(hours=n + 1), 96, 97, 95, 95.5, volume=800)
    )
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "bullish_harami" for d in dets)


def test_morning_star_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows, px, n = _downtrend_warmup(t0)
    # long red, small star, strong green into first body
    rows.append(_bar(t0 + timedelta(hours=n), 100, 100.2, 90, 90.5, volume=2000))
    rows.append(
        _bar(t0 + timedelta(hours=n + 1), 90.0, 90.8, 89.0, 89.5, volume=900)
    )
    rows.append(
        _bar(t0 + timedelta(hours=n + 2), 90.0, 97.5, 89.8, 96.5, volume=2200)
    )
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    ms = [d for d in dets if d.pattern == "morning_star"]
    assert ms
    assert "pattern_high" in ms[-1].conditions


def test_three_outside_up_detected():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows, px, n = _downtrend_warmup(t0)
    # bearish, bullish engulf, higher close confirm
    rows.append(_bar(t0 + timedelta(hours=n), 96, 96.2, 93, 93.5, volume=1500))
    rows.append(
        _bar(t0 + timedelta(hours=n + 1), 93.4, 97.5, 93.0, 97.0, volume=2000)
    )
    rows.append(
        _bar(t0 + timedelta(hours=n + 2), 97.0, 98.5, 96.5, 98.0, volume=2100)
    )
    df = pd.DataFrame(rows)
    dets = detect_closed_patterns(df)
    assert any(d.pattern == "three_outside_up" for d in dets)


def test_engulfing_carries_volume_ratio_and_pattern_range():
    t0 = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    rows = []
    px = 100.0
    for i in range(12):
        rows.append(_bar(t0 + timedelta(hours=i), px, px + 0.2, px - 1, px - 0.8))
        px -= 0.8
    rows.append(_bar(t0 + timedelta(hours=12), 95, 95.2, 94, 94.2, volume=1000))
    rows.append(
        _bar(t0 + timedelta(hours=13), 94.1, 96.5, 94.0, 96.2, volume=1800)
    )
    df = pd.DataFrame(rows)
    dets = [d for d in detect_closed_patterns(df) if d.pattern == "bullish_engulfing"]
    assert dets
    c = dets[-1].conditions
    assert c.get("volume_ratio") is not None
    assert c["pattern_high"] >= c["pattern_low"]
    assert c["pattern_close"] == 96.2
