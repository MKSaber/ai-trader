"""Versioned paper trade rules for candle-lab.

trade-rules-v1: original 5m long breakout (often uneconomic vs 0.5% SDRT).
trade-rules-v2: cost-aware 60m rules that cleared +P&L on a 10d T212 scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Frozen profiles — bump version string when changing numbers.
TRADE_RULE_PROFILES: dict[str, dict[str, Any]] = {
    "trade-rules-v1": {
        "label": "Original 5m long breakout (legacy)",
        "interval": "5m",
        "reward_risk": 2.0,
        "setup_expiry_bars": 3,
        "min_stop_pct": 0.0,
        "stop_pad_ranges": 0.0,
        "require_downtrend": False,
        "trade_hours_london": None,  # any session hour
        "max_trades_per_day": None,
        "exit_on_bearish": True,
        "session_flat": True,
        "cost_gate": False,
        "bullish_patterns": ("bullish_engulfing", "hammer"),
    },
    "trade-rules-v2": {
        "label": (
            "60m cost-aware: RR=4, stop pad 1R, downtrend, hours 10-15, "
            "1 trade/day, skip uneconomic vs SDRT"
        ),
        "interval": "60m",
        "reward_risk": 4.0,
        "setup_expiry_bars": 5,
        "min_stop_pct": 0.003,
        "stop_pad_ranges": 1.0,
        "require_downtrend": True,
        "trade_hours_london": (10, 11, 12, 13, 14, 15),
        "max_trades_per_day": 1,
        "exit_on_bearish": False,
        "session_flat": False,
        "cost_gate": True,
        "bullish_patterns": ("bullish_engulfing", "hammer"),
    },
    # Profit lift on top-10 / 30d £20k book: drop hammers (net loser),
    # skip weak London hours 10 & 13, raise RR to 5.
    "trade-rules-v2.1": {
        "label": (
            "60m profit-tuned: engulfing-only, RR=5, stop pad 1R, downtrend, "
            "hours 11/12/14/15, 1 trade/day, cost gate"
        ),
        "interval": "60m",
        "reward_risk": 5.0,
        "setup_expiry_bars": 5,
        "min_stop_pct": 0.003,
        "stop_pad_ranges": 1.0,
        "require_downtrend": True,
        "trade_hours_london": (11, 12, 14, 15),
        "max_trades_per_day": 1,
        "exit_on_bearish": False,
        "session_flat": False,
        "cost_gate": True,
        "bullish_patterns": ("bullish_engulfing",),
    },
}


@dataclass(frozen=True)
class TradeRules:
    version: str
    label: str
    interval: str
    reward_risk: float
    setup_expiry_bars: int
    min_stop_pct: float
    stop_pad_ranges: float
    require_downtrend: bool
    trade_hours_london: tuple[int, ...] | None
    max_trades_per_day: int | None
    exit_on_bearish: bool
    session_flat: bool
    cost_gate: bool
    bullish_patterns: tuple[str, ...]

    @property
    def bullish_set(self) -> set[str]:
        return set(self.bullish_patterns)


def load_trade_rules(version: str = "trade-rules-v2") -> TradeRules:
    if version not in TRADE_RULE_PROFILES:
        raise ValueError(
            f"Unknown trade rules {version!r}; choose from {sorted(TRADE_RULE_PROFILES)}"
        )
    raw = TRADE_RULE_PROFILES[version]
    hours = raw["trade_hours_london"]
    return TradeRules(
        version=version,
        label=raw["label"],
        interval=raw["interval"],
        reward_risk=float(raw["reward_risk"]),
        setup_expiry_bars=int(raw["setup_expiry_bars"]),
        min_stop_pct=float(raw["min_stop_pct"]),
        stop_pad_ranges=float(raw["stop_pad_ranges"]),
        require_downtrend=bool(raw["require_downtrend"]),
        trade_hours_london=tuple(hours) if hours is not None else None,
        max_trades_per_day=raw["max_trades_per_day"],
        exit_on_bearish=bool(raw["exit_on_bearish"]),
        session_flat=bool(raw["session_flat"]),
        cost_gate=bool(raw["cost_gate"]),
        bullish_patterns=tuple(raw["bullish_patterns"]),
    )


def setup_levels(
    high: float,
    low: float,
    *,
    entry_buffer_frac: float,
    stop_buffer_frac: float,
    reward_risk: float,
    stop_pad_ranges: float,
) -> tuple[float, float, float]:
    """Return (entry_trigger, stop, target)."""
    rng = max(high - low, high * 1e-4)
    entry = high * (1.0 + entry_buffer_frac)
    stop_raw = low - stop_pad_ranges * rng
    stop = stop_raw * (1.0 - stop_buffer_frac)
    risk = max(entry - stop, entry * 1e-4)
    target = entry + reward_risk * risk
    return entry, stop, target


def expected_net_at_target(
    qty: float,
    entry: float,
    stop: float,
    target: float,
    reward_risk: float,
    entry_cost_total: float,
    exit_cost_total: float,
) -> float:
    """Gross reward at planned target minus round-trip costs."""
    risk_ps = max(entry - stop, entry * 1e-4)
    gross = qty * reward_risk * risk_ps
    return gross - entry_cost_total - exit_cost_total
