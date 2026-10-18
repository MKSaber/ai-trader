"""Reproducible feature engineering using only as-of information."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FEATURE_DEFINITIONS = {
    "ret_1d": {
        "definition": "Prior session close-to-close return",
        "lookback": 1,
        "required_inputs": ["close_gbp"],
        "availability_rule": "Needs at least 2 daily closes ending at as-of date",
    },
    "ret_5d": {
        "definition": "5-session cumulative return",
        "lookback": 5,
        "required_inputs": ["close_gbp"],
        "availability_rule": "Needs at least 6 daily closes",
    },
    "mom_20d": {
        "definition": "20-session momentum",
        "lookback": 20,
        "required_inputs": ["close_gbp"],
        "availability_rule": "Needs at least 21 daily closes",
    },
    "ma_gap_20": {
        "definition": "Close / SMA20 - 1",
        "lookback": 20,
        "required_inputs": ["close_gbp"],
        "availability_rule": "Needs 20 daily closes",
    },
    "rvol_20": {
        "definition": "20-session realised volatility (std of returns)",
        "lookback": 20,
        "required_inputs": ["close_gbp"],
        "availability_rule": "Needs 21 daily closes",
    },
    "atr_norm_14": {
        "definition": "14-session ATR / close",
        "lookback": 14,
        "required_inputs": ["high_gbp", "low_gbp", "close_gbp"],
        "availability_rule": "Needs 15 daily bars with HL",
    },
    "vol_change_5": {
        "definition": "Volume / SMA5(volume) - 1",
        "lookback": 5,
        "required_inputs": ["volume"],
        "availability_rule": "Needs 5 volume observations",
    },
    "overnight_gap": {
        "definition": "Open / prior close - 1",
        "lookback": 1,
        "required_inputs": ["open_gbp", "close_gbp"],
        "availability_rule": "Needs prior close and today open",
    },
}


@dataclass
class FeatureFrame:
    """Feature matrix with exclusion tracking."""

    frame: pd.DataFrame
    excluded: dict[str, str]


def build_daily_features(bars: pd.DataFrame) -> FeatureFrame:
    """Build cross-sectional daily features from OHLCV.

    Args:
        bars: DataFrame indexed by session_date with columns
            instrument_id, open_gbp, high_gbp, low_gbp, close_gbp, volume.
            Must be sorted ascending within each instrument.
    """
    if bars.empty:
        return FeatureFrame(frame=bars.copy(), excluded={})

    parts: list[pd.DataFrame] = []
    excluded: dict[str, str] = {}

    for inst_id, group in bars.groupby("instrument_id"):
        g = group.sort_index().copy()
        close = g["close_gbp"]
        ret = close.pct_change()
        feat = pd.DataFrame(index=g.index)
        feat["instrument_id"] = inst_id
        feat["ret_1d"] = ret
        feat["ret_5d"] = close.pct_change(5)
        feat["mom_20d"] = close.pct_change(20)
        sma20 = close.rolling(20).mean()
        feat["ma_gap_20"] = close / sma20 - 1.0
        feat["rvol_20"] = ret.rolling(20).std()
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (g["high_gbp"] - g["low_gbp"]),
                (g["high_gbp"] - prev_close).abs(),
                (g["low_gbp"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean()
        feat["atr_norm_14"] = atr / close
        vol_sma = g["volume"].rolling(5).mean()
        feat["vol_change_5"] = g["volume"] / vol_sma - 1.0
        feat["overnight_gap"] = g["open_gbp"] / prev_close - 1.0
        # Forward label: next session open-to-close (aligned carefully)
        next_open = g["open_gbp"].shift(-1)
        next_close = g["close_gbp"].shift(-1)
        feat["target_next_session_oc"] = next_close / next_open - 1.0
        feat["target_up"] = (feat["target_next_session_oc"] > 0).astype(float)
        parts.append(feat)

    frame = pd.concat(parts).sort_index()
    # Drop rows where core features unavailable — do not fabricate
    core = ["ret_1d", "ret_5d", "mom_20d", "ma_gap_20", "rvol_20"]
    for col in FEATURE_DEFINITIONS:
        if col in frame.columns and frame[col].isna().all():
            excluded[col] = FEATURE_DEFINITIONS[col]["availability_rule"]

    usable = frame.dropna(subset=core + ["target_next_session_oc"])
    return FeatureFrame(frame=usable, excluded=excluded)


def feature_matrix(frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Extract X matrix and column names available (non-all-null)."""
    cols = [
        c
        for c in FEATURE_DEFINITIONS
        if c in frame.columns and not frame[c].isna().all()
    ]
    x = frame[cols].to_numpy(dtype=float)
    # Replace remaining NaNs with column medians fitted by caller ideally;
    # here leave as nan for train pipeline to impute on train only.
    return x, cols
