"""Paper execution for long-only candle pattern setups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings, get_settings


@dataclass
class CostBreakdown:
    spread: float
    slippage: float
    commission: float
    stamp: float
    fx: float = 0.0
    ptm: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.spread
            + self.slippage
            + self.commission
            + self.stamp
            + self.fx
            + self.ptm
        )


def _ptm_levy(notional: float, settings: Settings) -> float:
    """Takeover Panel PTM levy: flat fee when consideration exceeds threshold."""
    if settings.ptm_levy_gbp <= 0:
        return 0.0
    if notional > settings.ptm_threshold_gbp:
        return float(settings.ptm_levy_gbp)
    return 0.0


def entry_costs(notional: float, settings: Settings | None = None) -> CostBreakdown:
    s = settings or get_settings()
    half_spread = notional * (s.spread_bps / 2.0) / 10_000.0
    slip = notional * s.slippage_bps / 10_000.0
    commission = (
        notional * s.commission_bps / 10_000.0 + float(s.flat_commission_gbp)
    )
    stamp = notional * s.stamp_duty_rate
    fx = notional * s.fx_bps / 10_000.0
    ptm = _ptm_levy(notional, s)
    return CostBreakdown(half_spread, slip, commission, stamp, fx, ptm)


def exit_costs(notional: float, settings: Settings | None = None) -> CostBreakdown:
    s = settings or get_settings()
    half_spread = notional * (s.spread_bps / 2.0) / 10_000.0
    slip = notional * s.slippage_bps / 10_000.0
    commission = (
        notional * s.commission_bps / 10_000.0 + float(s.flat_commission_gbp)
    )
    fx = notional * s.fx_bps / 10_000.0
    ptm = _ptm_levy(notional, s)
    # No SDRT on sales (GOV.UK)
    return CostBreakdown(half_spread, slip, commission, 0.0, fx, ptm)


def adverse_entry_price(mid: float, settings: Settings | None = None) -> float:
    s = settings or get_settings()
    adj = (s.spread_bps / 2.0 + s.slippage_bps) / 10_000.0
    return mid * (1.0 + adj)


def adverse_exit_price(mid: float, settings: Settings | None = None) -> float:
    s = settings or get_settings()
    adj = (s.spread_bps / 2.0 + s.slippage_bps) / 10_000.0
    return mid * (1.0 - adj)


@dataclass
class ExitSim:
    reason: str
    exit_mid: float
    ambiguous: bool
    conservative_reason: str
    optimistic_reason: str


def simulate_long_bar(
    entry: float,
    stop: float,
    target: float,
    high: float,
    low: float,
    close: float,
) -> ExitSim | None:
    """Return exit if stop/target/close rules fire on this bar; else None (hold)."""
    hit_stop = low <= stop
    hit_tp = high >= target
    if hit_stop and hit_tp:
        return ExitSim(
            reason="stop_loss_ambiguous",
            exit_mid=stop,
            ambiguous=True,
            conservative_reason="stop_first",
            optimistic_reason="target_first",
        )
    if hit_stop:
        return ExitSim("stop_loss", stop, False, "stop_loss", "stop_loss")
    if hit_tp:
        return ExitSim("take_profit", target, False, "take_profit", "take_profit")
    return None


def size_shares(
    cash: float,
    entry: float,
    stop: float,
    settings: Settings | None = None,
) -> float:
    """Fixed risk budget, capped by cash and max position fraction."""
    s = settings or get_settings()
    risk_per_share = max(entry - stop, entry * 1e-4)
    risk_budget = cash * s.risk_frac
    by_risk = risk_budget / risk_per_share
    by_cash = (cash * 0.95) / entry
    by_cap = (cash * s.max_position_frac) / entry
    qty = max(0.0, min(by_risk, by_cash, by_cap))
    return float(qty)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
