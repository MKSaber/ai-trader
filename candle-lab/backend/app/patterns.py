"""Versioned candlestick detectors.

patterns-v1: IG-qualitative engulfing / hammer / shooting star.
patterns-v2: adaptive body thresholds + piercing / harami / morning-star /
             three-outside-up, with volume ratio when available.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

DETECTOR_VERSION = "patterns-v2"
TREND_LOOKBACK = 5
UPPER_WICK_MAX_BODY_MULT = 0.25  # "little or no" upper/lower wick assumption
BODY_AVG_PERIOD = 10  # TA-Lib-style adaptive "long body" window


@dataclass
class Detection:
    pattern: str
    direction: str  # up | down
    confirm_index: int
    conditions: dict[str, Any]
    bar_starts: list[str]


def _eps(row: pd.Series) -> float:
    mid = (float(row["high"]) + float(row["low"])) / 2.0
    return max(1e-8, 1e-4 * max(mid, 1e-8))


def _valid_range(row: pd.Series) -> bool:
    eps = _eps(row)
    return float(row["high"]) > float(row["low"]) + eps


def in_downtrend(df: pd.DataFrame, i: int) -> bool:
    """True if close of bar i-1 is below close of bar i-1-TREND_LOOKBACK."""
    j = i - 1
    k = j - TREND_LOOKBACK
    if k < 0:
        return False
    return float(df.iloc[j]["close"]) < float(df.iloc[k]["close"])


def downtrend_depth_pct(df: pd.DataFrame, i: int, lookback: int = TREND_LOOKBACK) -> float:
    """Fraction the prior close has fallen over `lookback` bars (0 if flat/up)."""
    j = i - 1
    k = j - lookback
    if k < 0:
        return 0.0
    c0 = float(df.iloc[k]["close"])
    c1 = float(df.iloc[j]["close"])
    if c0 <= 0:
        return 0.0
    return max(0.0, (c0 - c1) / c0)


def in_uptrend(df: pd.DataFrame, i: int) -> bool:
    """True if close of bar i-1 is above close of bar i-1-TREND_LOOKBACK."""
    j = i - 1
    k = j - TREND_LOOKBACK
    if k < 0:
        return False
    return float(df.iloc[j]["close"]) > float(df.iloc[k]["close"])


def _downtrend(df: pd.DataFrame, i: int) -> bool:
    return in_downtrend(df, i)


def _uptrend(df: pd.DataFrame, i: int) -> bool:
    return in_uptrend(df, i)


def _unpack(row: pd.Series) -> tuple[float, float, float, float, float, float, float]:
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return o, h, l, c, body, upper, lower


def _avg_body(df: pd.DataFrame, end_i: int, period: int = BODY_AVG_PERIOD) -> float:
    """Mean real body of bars [end_i-period, end_i) — excludes end_i (TA-Lib style)."""
    start = max(0, end_i - period)
    if start >= end_i:
        return 0.0
    total = 0.0
    n = 0
    for j in range(start, end_i):
        o = float(df.iloc[j]["open"])
        c = float(df.iloc[j]["close"])
        total += abs(c - o)
        n += 1
    return total / n if n else 0.0


def _is_body_long(body: float, avg_body: float, factor: float = 1.0) -> bool:
    if avg_body <= 0:
        return body > 0
    return body >= factor * avg_body


def _is_body_short(body: float, avg_body: float, factor: float = 1.0) -> bool:
    if avg_body <= 0:
        return True
    return body <= factor * avg_body


def _volume_ratio(df: pd.DataFrame, i: int, period: int = BODY_AVG_PERIOD) -> float | None:
    if "volume" not in df.columns:
        return None
    vol = float(df.iloc[i]["volume"] or 0.0)
    start = max(0, i - period)
    if start >= i:
        return None
    prior = [float(df.iloc[j]["volume"] or 0.0) for j in range(start, i)]
    avg = sum(prior) / len(prior) if prior else 0.0
    if avg <= 0:
        return None
    return vol / avg


def _bar_starts(df: pd.DataFrame, idxs: list[int]) -> list[str]:
    if "bar_start" not in df.columns:
        return [str(i) for i in idxs]
    return [str(df.iloc[i]["bar_start"]) for i in idxs]


def _pattern_hl(df: pd.DataFrame, idxs: list[int]) -> tuple[float, float]:
    highs = [float(df.iloc[j]["high"]) for j in idxs]
    lows = [float(df.iloc[j]["low"]) for j in idxs]
    return max(highs), min(lows)


def detect_closed_patterns(df: pd.DataFrame) -> list[Detection]:
    """Detect patterns using only closed bars in `df` (ascending time).

    Expects columns: open, high, low, close, bar_start (optional), volume (optional).
    Last row must be a closed candle — caller must exclude the forming bar.
    """
    if df is None or len(df) < 2:
        return []
    out: list[Detection] = []
    for i in range(1, len(df)):
        if not _valid_range(df.iloc[i]) or not _valid_range(df.iloc[i - 1]):
            continue
        prev, cur = df.iloc[i - 1], df.iloc[i]
        eps = _eps(cur)
        o0, h0, l0, c0, b0, u0, lo0 = _unpack(prev)
        o1, h1, l1, c1, b1, u1, lo1 = _unpack(cur)
        avg_body = _avg_body(df, i)
        vol_r = _volume_ratio(df, i)
        ph, pl = _pattern_hl(df, [i - 1, i])

        # --- Bullish engulfing ---
        if (
            c0 < o0 - eps
            and c1 > o1 + eps
            and o1 <= c0 + eps
            and c1 >= o0 - eps
            and b1 > b0 + eps
        ):
            out.append(
                Detection(
                    pattern="bullish_engulfing",
                    direction="up",
                    confirm_index=i,
                    conditions={
                        "prior_bearish": True,
                        "current_bullish": True,
                        "body_engulfs": True,
                        "current_body_larger": True,
                        "body_prev": b0,
                        "body_cur": b1,
                        "body_long": _is_body_long(b1, avg_body),
                        "avg_body": avg_body,
                        "volume_ratio": vol_r,
                        "pattern_high": ph,
                        "pattern_low": pl,
                        "pattern_close": c1,
                        "ig_ref": "Bullish engulfing (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # --- Bearish engulfing ---
        if (
            c0 > o0 + eps
            and c1 < o1 - eps
            and o1 >= c0 - eps
            and c1 <= o0 + eps
            and b1 > b0 + eps
        ):
            out.append(
                Detection(
                    pattern="bearish_engulfing",
                    direction="down",
                    confirm_index=i,
                    conditions={
                        "prior_bullish": True,
                        "current_bearish": True,
                        "body_engulfs": True,
                        "current_body_larger": True,
                        "body_prev": b0,
                        "body_cur": b1,
                        "volume_ratio": vol_r,
                        "pattern_high": ph,
                        "pattern_low": pl,
                        "pattern_close": c1,
                        "ig_ref": "Bearish engulfing (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # --- Piercing line (bullish 2-bar; distinct from full engulf) ---
        prior_mid = (o0 + c0) / 2.0
        if (
            c0 < o0 - eps
            and c1 > o1 + eps
            and o1 < c0 - eps  # opens below prior close
            and c1 > prior_mid + eps  # closes above prior midpoint
            and c1 < o0 - eps  # does not clear prior open (else engulfing)
            and _is_body_long(b0, avg_body)
        ):
            out.append(
                Detection(
                    pattern="piercing_line",
                    direction="up",
                    confirm_index=i,
                    conditions={
                        "prior_bearish_long": True,
                        "opens_below_prior_close": True,
                        "closes_above_prior_mid": True,
                        "not_full_engulf": True,
                        "body_prev": b0,
                        "body_cur": b1,
                        "volume_ratio": vol_r,
                        "pattern_high": ph,
                        "pattern_low": pl,
                        "pattern_close": c1,
                        "ref": "Piercing line (2-bar bullish reversal)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # --- Bullish harami ---
        if (
            c0 < o0 - eps
            and _is_body_long(b0, avg_body)
            and _is_body_short(b1, avg_body)
            and max(o1, c1) < o0 - eps
            and min(o1, c1) > c0 + eps
            and b1 < b0 - eps
        ):
            out.append(
                Detection(
                    pattern="bullish_harami",
                    direction="up",
                    confirm_index=i,
                    conditions={
                        "prior_bearish_long": True,
                        "current_inside": True,
                        "body_prev": b0,
                        "body_cur": b1,
                        "volume_ratio": vol_r,
                        "pattern_high": ph,
                        "pattern_low": pl,
                        "pattern_close": c1,
                        "ref": "Bullish harami (Lu & Shiu confirmation family)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # --- Three outside up: engulfing + confirmation close ---
        if i >= 2 and _valid_range(df.iloc[i - 2]):
            o_m2, h_m2, l_m2, c_m2, b_m2, _, _ = _unpack(df.iloc[i - 2])
            # bars i-2 bearish, i-1 bullish engulfing of i-2, i closes above i-1 close
            engulf_m1 = (
                c_m2 < o_m2 - eps
                and c0 > o0 + eps
                and o0 <= c_m2 + eps
                and c0 >= o_m2 - eps
                and b0 > b_m2 + eps
            )
            if engulf_m1 and c1 > c0 + eps and c1 > o1 + eps:
                ph3, pl3 = _pattern_hl(df, [i - 2, i - 1, i])
                out.append(
                    Detection(
                        pattern="three_outside_up",
                        direction="up",
                        confirm_index=i,
                        conditions={
                            "engulf_then_higher_close": True,
                            "body_engulf": b0,
                            "confirm_close": c1,
                            "volume_ratio": vol_r,
                            "pattern_high": ph3,
                            "pattern_low": pl3,
                            "pattern_close": c1,
                            "ref": "Three outside up (engulf + confirm bar)",
                        },
                        bar_starts=_bar_starts(df, [i - 2, i - 1, i]),
                    )
                )

        # --- Morning star (3-bar) ---
        if i >= 2 and _valid_range(df.iloc[i - 2]):
            o2, h2, l2, c2, b2, _, _ = _unpack(df.iloc[i - 2])
            avg2 = _avg_body(df, i - 1)
            star_small = _is_body_short(b0, avg2) or b0 <= max(eps, 0.5 * b2)
            if (
                c2 < o2 - eps
                and _is_body_long(b2, avg2)
                and star_small
                and c1 > o1 + eps
                and c1 > (o2 + c2) / 2.0 + eps  # closes into first body
                and o0 < c2 + eps  # star opens near/below first close
            ):
                ph3, pl3 = _pattern_hl(df, [i - 2, i - 1, i])
                out.append(
                    Detection(
                        pattern="morning_star",
                        direction="up",
                        confirm_index=i,
                        conditions={
                            "first_bearish_long": True,
                            "star_small": True,
                            "third_bullish_into_body": True,
                            "volume_ratio": vol_r,
                            "pattern_high": ph3,
                            "pattern_low": pl3,
                            "pattern_close": c1,
                            "ref": "Morning star (3-bar bullish reversal)",
                        },
                        bar_starts=_bar_starts(df, [i - 2, i - 1, i]),
                    )
                )

        # --- Hammer ---
        if (
            i >= TREND_LOOKBACK + 1
            and _downtrend(df, i)
            and b1 > eps
            and lo1 >= 2 * b1
            and u1 <= max(eps, UPPER_WICK_MAX_BODY_MULT * b1)
        ):
            out.append(
                Detection(
                    pattern="hammer",
                    direction="up",
                    confirm_index=i,
                    conditions={
                        "downtrend": True,
                        "lower_wick_ge_2x_body": True,
                        "upper_wick_small": True,
                        "lower": lo1,
                        "upper": u1,
                        "body": b1,
                        "volume_ratio": vol_r,
                        "pattern_high": h1,
                        "pattern_low": l1,
                        "pattern_close": c1,
                        "upper_wick_max_body_mult": UPPER_WICK_MAX_BODY_MULT,
                        "trend_lookback": TREND_LOOKBACK,
                        "ig_ref": "Hammer (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i]),
                )
            )

        # --- Shooting star ---
        if (
            i >= TREND_LOOKBACK + 1
            and _uptrend(df, i)
            and b1 > eps
            and u1 >= 2 * b1
            and lo1 <= max(eps, UPPER_WICK_MAX_BODY_MULT * b1)
        ):
            out.append(
                Detection(
                    pattern="shooting_star",
                    direction="down",
                    confirm_index=i,
                    conditions={
                        "uptrend": True,
                        "upper_wick_ge_2x_body": True,
                        "lower_wick_small": True,
                        "lower": lo1,
                        "upper": u1,
                        "body": b1,
                        "volume_ratio": vol_r,
                        "pattern_high": h1,
                        "pattern_low": l1,
                        "pattern_close": c1,
                        "upper_wick_max_body_mult": UPPER_WICK_MAX_BODY_MULT,
                        "trend_lookback": TREND_LOOKBACK,
                        "ig_ref": "Shooting star (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i]),
                )
            )
    return out


def detection_to_dict(d: Detection) -> dict[str, Any]:
    return asdict(d)
