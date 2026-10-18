"""Intraday signal generation and paper execution (no real orders)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.domain.enums import ExitReason, TradeOutcome
from app.services.eval.costs import (
    CostAssumptions,
    apply_entry_price,
    purchase_costs,
    sale_costs,
)


@dataclass
class SetupSpec:
    """Frozen actionable setup or no-trade."""

    signal_ts: datetime
    model_version: str
    symbol: str
    no_trade: bool
    reason: str
    entry_low: float | None = None
    entry_high: float | None = None
    entry_expiry: datetime | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    max_hold_minutes: int = 120
    expected_net_return: float | None = None
    uncertainty: float | None = None
    estimated_costs: float | None = None


@dataclass
class SimResult:
    """Simulation outcome for one setup."""

    outcome: str
    exit_reason: str
    entry_ts: datetime | None
    exit_ts: datetime | None
    entry_price: float | None
    exit_price: float | None
    gross_pnl: float | None
    costs: float | None
    net_pnl: float | None
    ambiguity_flag: bool
    notes: str


def generate_long_setup(
    bars: pd.DataFrame,
    signal_idx: int,
    model_version: str,
    assumptions: CostAssumptions,
    *,
    momentum_lookback: int = 6,
) -> SetupSpec:
    """Generate a long-only setup from completed bars only.

    Uses information available at signal bar close; entry not before next bar.
    """
    if signal_idx < momentum_lookback or signal_idx >= len(bars) - 1:
        return SetupSpec(
            signal_ts=bars.iloc[min(signal_idx, len(bars) - 1)]["bar_ts"],
            model_version=model_version,
            symbol=str(bars.iloc[0]["symbol"]),
            no_trade=True,
            reason="Insufficient evidence: not enough completed bars",
        )

    window = bars.iloc[signal_idx - momentum_lookback : signal_idx + 1]
    ret = window["close_gbp"].pct_change().dropna()
    mom = float(ret.sum())
    vol = float(ret.std()) if len(ret) > 1 else 0.0
    last = bars.iloc[signal_idx]
    signal_ts = last["bar_ts"]
    mid = float(last["close_gbp"])

    # Do not assume any R:R is profitable — require mild positive momentum
    if mom <= 0 or vol <= 0:
        return SetupSpec(
            signal_ts=signal_ts,
            model_version=model_version,
            symbol=str(last["symbol"]),
            no_trade=True,
            reason="No trade: momentum/volatility evidence insufficient",
        )

    stop = mid * (1.0 - max(2 * vol, 0.002))
    target = mid * (1.0 + max(2 * vol, 0.002))
    entry_low = mid * 0.999
    entry_high = mid * 1.001
    # Rough expected net after costs
    from app.services.eval.costs import estimate_round_trip_cost_fraction

    costs_frac = estimate_round_trip_cost_fraction(assumptions)
    expected_gross = (target / mid) - 1.0
    expected_net = expected_gross - costs_frac

    return SetupSpec(
        signal_ts=signal_ts,
        model_version=model_version,
        symbol=str(last["symbol"]),
        no_trade=False,
        reason=(
            f"Long setup from {momentum_lookback}-bar momentum={mom:.4f}; "
            "parameters selected from training conventions, not guaranteed edge"
        ),
        entry_low=entry_low,
        entry_high=entry_high,
        entry_expiry=signal_ts + timedelta(minutes=30),
        stop_loss=stop,
        take_profit=target,
        max_hold_minutes=120,
        expected_net_return=expected_net,
        uncertainty=vol,
        estimated_costs=costs_frac,
    )


def simulate_setup(
    setup: SetupSpec,
    bars: pd.DataFrame,
    assumptions: CostAssumptions,
    *,
    notional_gbp: float = 5_000.0,
) -> SimResult:
    """Event-by-event simulation; entry no earlier than next bar after signal."""
    if setup.no_trade:
        return SimResult(
            outcome=TradeOutcome.NOT_TRIGGERED,
            exit_reason=ExitReason.NOT_APPLICABLE,
            entry_ts=None,
            exit_ts=None,
            entry_price=None,
            exit_price=None,
            gross_pnl=None,
            costs=None,
            net_pnl=None,
            ambiguity_flag=False,
            notes="No trade issued",
        )

    # Bars strictly after signal
    future = bars[bars["bar_ts"] > setup.signal_ts].sort_values("bar_ts")
    if future.empty:
        return SimResult(
            outcome=TradeOutcome.NOT_TRIGGERED,
            exit_reason=ExitReason.NOT_APPLICABLE,
            entry_ts=None,
            exit_ts=None,
            entry_price=None,
            exit_price=None,
            gross_pnl=None,
            costs=None,
            net_pnl=None,
            ambiguity_flag=False,
            notes="No subsequent bars to execute",
        )

    entry_ts = None
    entry_px = None
    for _, bar in future.iterrows():
        if setup.entry_expiry and bar["bar_ts"] > setup.entry_expiry:
            break
        # Limit zone: require tradeable overlap; touch ≠ fill — use close inside zone
        lo, hi = setup.entry_low, setup.entry_high
        if lo is None or hi is None:
            break
        if bar["low_gbp"] <= hi and bar["high_gbp"] >= lo:
            # Conservative fill at adverse side of zone mid
            mid = (lo + hi) / 2.0
            entry_px = apply_entry_price(mid, assumptions, side="buy")
            entry_ts = bar["bar_ts"]
            break

    if entry_ts is None or entry_px is None:
        return SimResult(
            outcome=TradeOutcome.EXPIRED,
            exit_reason=ExitReason.NOT_APPLICABLE,
            entry_ts=None,
            exit_ts=None,
            entry_price=None,
            exit_price=None,
            gross_pnl=None,
            costs=None,
            net_pnl=None,
            ambiguity_flag=False,
            notes="Limit not filled before expiry (touch does not guarantee fill)",
        )

    after_entry = future[future["bar_ts"] > entry_ts]
    qty = notional_gbp / entry_px
    entry_costs = purchase_costs(notional_gbp, assumptions)
    max_exit = entry_ts + timedelta(minutes=setup.max_hold_minutes)
    session_end = future.iloc[-1]["bar_ts"]

    ambiguity = False
    exit_ts = None
    exit_px = None
    exit_reason = ExitReason.END_OF_SESSION

    for _, bar in after_entry.iterrows():
        hit_stop = setup.stop_loss is not None and bar["low_gbp"] <= setup.stop_loss
        hit_target = (
            setup.take_profit is not None and bar["high_gbp"] >= setup.take_profit
        )
        if hit_stop and hit_target:
            # Same bar ambiguity — do not assume favourable sequence
            ambiguity = True
            # Conservative: assume stop first
            exit_px = setup.stop_loss
            exit_ts = bar["bar_ts"]
            exit_reason = ExitReason.STOP
            break
        if hit_stop:
            exit_px = setup.stop_loss
            exit_ts = bar["bar_ts"]
            exit_reason = ExitReason.STOP
            break
        if hit_target:
            exit_px = setup.take_profit
            exit_ts = bar["bar_ts"]
            exit_reason = ExitReason.TARGET
            break
        if bar["bar_ts"] >= max_exit:
            exit_px = float(bar["close_gbp"])
            exit_ts = bar["bar_ts"]
            exit_reason = ExitReason.TIME_LIMIT
            break

    if exit_ts is None:
        exit_ts = session_end
        exit_px = float(after_entry.iloc[-1]["close_gbp"]) if len(after_entry) else entry_px
        exit_reason = ExitReason.END_OF_SESSION

    exit_notional = qty * float(exit_px)
    exit_costs = sale_costs(exit_notional, assumptions)
    costs = entry_costs + exit_costs
    gross = (float(exit_px) - entry_px) * qty
    net = gross - costs

    if ambiguity:
        outcome = TradeOutcome.AMBIGUOUS
    elif abs(net) < 1e-9:
        outcome = TradeOutcome.BREAKEVEN
    elif net > 0:
        outcome = TradeOutcome.CLOSED_POSITIVE
    else:
        outcome = TradeOutcome.CLOSED_NEGATIVE

    notes = ""
    if ambiguity:
        notes = (
            "Stop and target both printable in same OHLC bar; "
            "conservative path assumes stop first. Sensitivity: "
            f"favourable target net would differ."
        )

    return SimResult(
        outcome=outcome,
        exit_reason=exit_reason,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=entry_px,
        exit_price=float(exit_px),
        gross_pnl=gross,
        costs=costs,
        net_pnl=net,
        ambiguity_flag=ambiguity,
        notes=notes,
    )


def portfolio_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate paper-trade metrics with sample size."""
    closed = [t for t in trades if t.get("net_pnl") is not None]
    if not closed:
        return {
            "n": 0,
            "note": "Insufficient closed trades for metrics",
        }
    nets = [float(t["net_pnl"]) for t in closed]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    gross_wins = sum(wins) if wins else 0.0
    gross_losses = abs(sum(losses)) if losses else 0.0
    return {
        "n": len(closed),
        "win_rate": len(wins) / len(closed),
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "expectancy": sum(nets) / len(closed),
        "profit_factor": (gross_wins / gross_losses) if gross_losses else None,
        "net_total": sum(nets),
        "gross_total": sum(float(t.get("gross_pnl") or 0) for t in closed),
        "costs_total": sum(float(t.get("costs") or 0) for t in closed),
    }
