"""Versioned paper trade rules for candle-lab.

trade-rules-v1: original 5m long breakout (often uneconomic vs 0.5% SDRT).
trade-rules-v2 / v2.1: cost-aware 60m rules.
trade-rules-v2.2: stay green on top-10 / 60d (hour-15 filter + cooloff/sizing).
trade-rules-v2.3: broad-book fix — blocklist drag names, max 1 stop, smaller size.
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
        "trade_hours_london": None,
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
        "risk_frac": 0.01,
        "max_position_frac": 0.25,
    },
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
        "risk_frac": 0.01,
        "max_position_frac": 0.25,
    },
    # Root-cause fixes for 60d top-10 drawdown (v2.1 was −£314 / 60d):
    # - H1 losses clustered on hours 11/12/14; hour 15 alone stayed dual-+ve
    # - stop-outs re-entered (cooloff + max 2 stops/symbol)
    # - sizing: risk 1.5% / max pos 35% so 5R clears SDRT without overtrading
    # Rejected levers: min_stop 1.5% (0 trades with hours 11/15), trail BE (hurt 60d)
    "trade-rules-v2.2": {
        "label": (
            "60m stay-green: engulfing-only, RR=5, pad 1R, hour 15 only, "
            "cooloff after stop, max 2 stops/symbol, risk 1.5%/pos 35%"
        ),
        "interval": "60m",
        "reward_risk": 5.0,
        "setup_expiry_bars": 5,
        "min_stop_pct": 0.003,
        "stop_pad_ranges": 1.0,
        "require_downtrend": True,
        "trade_hours_london": (15,),
        "max_trades_per_day": 1,
        "exit_on_bearish": False,
        "session_flat": False,
        "cost_gate": True,
        "bullish_patterns": ("bullish_engulfing",),
        "cooloff_after_stop": True,
        "trail_breakeven_r": None,
        "max_stops_per_symbol": 2,
        "risk_frac": 0.015,
        "max_position_frac": 0.35,
    },
    # Root-cause fixes for top-50 / £100k drawdown under v2.2:
    # - rest_30 + banks/defence/volatile-fin were ~80% of 60d loss
    # - max_stops=2 still left dozens of double-stop names on 90/120d
    # - 1.5%/35% sizing at £100k made single stops −£1k+ (III −£1.46k)
    # Keep hour-15 / cooloff / engulfing / RR=5 (still green on top-10).
    "trade-rules-v2.3": {
        "label": (
            "60m broad-book: engulfing-only, RR=5, hour 15, cooloff, "
            "max 1 stop/symbol, blocklist drag names, cash-aware size"
        ),
        "interval": "60m",
        "reward_risk": 5.0,
        "setup_expiry_bars": 5,
        "min_stop_pct": 0.003,
        "stop_pad_ranges": 1.0,
        "require_downtrend": True,
        "trade_hours_london": (15,),
        "max_trades_per_day": 1,
        "exit_on_bearish": False,
        "session_flat": False,
        "cost_gate": True,
        "bullish_patterns": ("bullish_engulfing",),
        "cooloff_after_stop": True,
        "trail_breakeven_r": None,
        # Default = top-10 (£20k) knobs; tighten on large books (see large_book_*).
        "max_stops_per_symbol": 2,
        "risk_frac": 0.015,
        "max_position_frac": 0.35,
        "large_book_cash_gbp": 50_000.0,
        "large_book_risk_frac": 0.008,
        "large_book_max_position_frac": 0.15,
        "large_book_max_stops_per_symbol": 1,
        # Preserve top-10 megacaps; block root-cause drag cohorts.
        "symbol_blocklist": (
            # banks (HSBA kept — top-10)
            "LLOY.L",
            "BARC.L",
            "NWG.L",
            "STAN.L",
            # defence
            "BA.L",
            "RR.L",
            # volatile / chronic-stop fin & services
            "III.L",
            "ADM.L",
            "AAF.L",
            "SMT.L",
            "EXPN.L",
            "IHG.L",
            # chronic rest_30 stops
            "EDV.L",
            "SN.L",
            "SVT.L",
            "SGRO.L",
            "HLN.L",
            "DGE.L",
            "SSE.L",
            "UU.L",
            "BHP.L",
            "ANTO.L",
            "CCH.L",
            "ABF.L",
            "INF.L",
            "PRU.L",
            "LGEN.L",
        ),
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
    cooloff_after_stop: bool = False
    trail_breakeven_r: float | None = None
    max_stops_per_symbol: int | None = None
    risk_frac: float = 0.01
    max_position_frac: float = 0.25
    symbol_blocklist: tuple[str, ...] = ()
    large_book_cash_gbp: float | None = None
    large_book_risk_frac: float | None = None
    large_book_max_position_frac: float | None = None
    large_book_max_stops_per_symbol: int | None = None

    @property
    def bullish_set(self) -> set[str]:
        return set(self.bullish_patterns)

    @property
    def blocklist_set(self) -> set[str]:
        return set(self.symbol_blocklist)

    def is_large_book(self, cash: float) -> bool:
        return (
            self.large_book_cash_gbp is not None and cash >= self.large_book_cash_gbp
        )

    def sizing_for_cash(self, cash: float) -> tuple[float, float]:
        """Return (risk_frac, max_position_frac), scaling down on large books."""
        if (
            self.is_large_book(cash)
            and self.large_book_risk_frac is not None
            and self.large_book_max_position_frac is not None
        ):
            return self.large_book_risk_frac, self.large_book_max_position_frac
        return self.risk_frac, self.max_position_frac

    def max_stops_for_cash(self, cash: float) -> int | None:
        if self.is_large_book(cash) and self.large_book_max_stops_per_symbol is not None:
            return self.large_book_max_stops_per_symbol
        return self.max_stops_per_symbol


def load_trade_rules(version: str = "trade-rules-v2.3") -> TradeRules:
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
        cooloff_after_stop=bool(raw.get("cooloff_after_stop", False)),
        trail_breakeven_r=(
            float(raw["trail_breakeven_r"])
            if raw.get("trail_breakeven_r") is not None
            else None
        ),
        max_stops_per_symbol=raw.get("max_stops_per_symbol"),
        risk_frac=float(raw.get("risk_frac", 0.01)),
        max_position_frac=float(raw.get("max_position_frac", 0.25)),
        symbol_blocklist=tuple(raw.get("symbol_blocklist") or ()),
        large_book_cash_gbp=(
            float(raw["large_book_cash_gbp"])
            if raw.get("large_book_cash_gbp") is not None
            else None
        ),
        large_book_risk_frac=(
            float(raw["large_book_risk_frac"])
            if raw.get("large_book_risk_frac") is not None
            else None
        ),
        large_book_max_position_frac=(
            float(raw["large_book_max_position_frac"])
            if raw.get("large_book_max_position_frac") is not None
            else None
        ),
        large_book_max_stops_per_symbol=raw.get("large_book_max_stops_per_symbol"),
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
