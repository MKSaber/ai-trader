"""Trading costs and same-bar ambiguity tests."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.domain.enums import TradeOutcome
from app.services.eval.costs import (
    CostAssumptions,
    estimate_round_trip_cost_fraction,
    purchase_costs,
)
from app.services.intraday.engine import SetupSpec, generate_long_setup, simulate_setup


def test_stamp_duty_on_purchase() -> None:
    """UK purchase includes stamp duty."""
    a = CostAssumptions(5, 10, 5, 0.01)
    costs = purchase_costs(10_000, a)
    assert costs >= 100  # 1% stamp
    frac = estimate_round_trip_cost_fraction(a)
    assert frac > 0.01


def test_same_bar_stop_target_ambiguous() -> None:
    """When stop and target both hit in one bar, flag ambiguity and be conservative."""
    assumptions = CostAssumptions(0, 0, 0, 0)
    signal = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    bars = pd.DataFrame(
        [
            {
                "symbol": "VOD.L",
                "bar_ts": signal,
                "open_gbp": 1.0,
                "high_gbp": 1.01,
                "low_gbp": 0.99,
                "close_gbp": 1.0,
                "volume": 1,
            },
            {
                "symbol": "VOD.L",
                "bar_ts": signal + timedelta(minutes=5),
                "open_gbp": 1.0,
                "high_gbp": 1.001,
                "low_gbp": 0.999,
                "close_gbp": 1.0,
                "volume": 1,
            },
            {
                "symbol": "VOD.L",
                "bar_ts": signal + timedelta(minutes=10),
                "open_gbp": 1.0,
                "high_gbp": 1.05,
                "low_gbp": 0.95,
                "close_gbp": 1.0,
                "volume": 1,
            },
        ]
    )
    setup = SetupSpec(
        signal_ts=signal,
        model_version="test",
        symbol="VOD.L",
        no_trade=False,
        reason="unit test",
        entry_low=0.99,
        entry_high=1.01,
        entry_expiry=signal + timedelta(hours=1),
        stop_loss=0.96,
        take_profit=1.04,
        max_hold_minutes=120,
        expected_net_return=0.01,
        uncertainty=0.01,
        estimated_costs=0.0,
    )
    sim = simulate_setup(setup, bars, assumptions, notional_gbp=1000)
    assert sim.ambiguity_flag is True
    assert sim.outcome == TradeOutcome.AMBIGUOUS
    assert sim.exit_reason == "stop"


def test_no_trade_insufficient() -> None:
    """Few bars yield no-trade setup."""
    bars = pd.DataFrame(
        [
            {
                "symbol": "VOD.L",
                "bar_ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "open_gbp": 1,
                "high_gbp": 1,
                "low_gbp": 1,
                "close_gbp": 1,
                "volume": 1,
            }
        ]
    )
    spec = generate_long_setup(
        bars, 0, "v1", CostAssumptions(5, 10, 5, 0.01)
    )
    assert spec.no_trade is True
