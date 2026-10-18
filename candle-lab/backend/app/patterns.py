"""Versioned candlestick detectors (patterns-v1).

Qualitative definitions from IG Academy candlestick patterns page.
Numeric thresholds are experiment assumptions — see PATTERN_DEFINITIONS.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

DETECTOR_VERSION = "patterns-v1"
TREND_LOOKBACK = 5
UPPER_WICK_MAX_BODY_MULT = 0.25  # "little or no" upper/lower wick assumption


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


def detect_closed_patterns(df: pd.DataFrame) -> list[Detection]:
    """Detect patterns using only closed bars in `df` (ascending time).

    Expects columns: open, high, low, close, bar_start (optional).
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

        # Bullish engulfing
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
                        "ig_ref": "Bullish engulfing (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # Bearish engulfing
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
                        "ig_ref": "Bearish engulfing (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i - 1, i]),
                )
            )

        # Hammer
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
                        "upper_wick_max_body_mult": UPPER_WICK_MAX_BODY_MULT,
                        "trend_lookback": TREND_LOOKBACK,
                        "ig_ref": "Hammer (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i]),
                )
            )

        # Shooting star
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
                        "upper_wick_max_body_mult": UPPER_WICK_MAX_BODY_MULT,
                        "trend_lookback": TREND_LOOKBACK,
                        "ig_ref": "Shooting star (IG qualitative)",
                    },
                    bar_starts=_bar_starts(df, [i]),
                )
            )
    return out


def _unpack(row: pd.Series) -> tuple[float, float, float, float, float, float, float]:
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return o, h, l, c, body, upper, lower


def _bar_starts(df: pd.DataFrame, idxs: list[int]) -> list[str]:
    if "bar_start" not in df.columns:
        return [str(i) for i in idxs]
    return [str(df.iloc[i]["bar_start"]) for i in idxs]


def detection_to_dict(d: Detection) -> dict[str, Any]:
    return asdict(d)
