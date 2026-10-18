"""trade-rules-v2 cost-aware helpers."""

from app.trade_rules import (
    expected_net_at_target,
    load_trade_rules,
    setup_levels,
)


def test_v2_profile_defaults():
    r = load_trade_rules("trade-rules-v2")
    assert r.interval == "60m"
    assert r.reward_risk == 4.0
    assert r.stop_pad_ranges == 1.0
    assert r.require_downtrend is True
    assert r.cost_gate is True
    assert r.exit_on_bearish is False
    assert r.trade_hours_london == (10, 11, 12, 13, 14, 15)


def test_v21_profit_tuned_defaults():
    r = load_trade_rules("trade-rules-v2.1")
    assert r.reward_risk == 5.0
    assert r.bullish_patterns == ("bullish_engulfing",)
    assert r.trade_hours_london == (11, 12, 14, 15)
    assert "hammer" not in r.bullish_set


def test_stop_pad_widens_stop():
    entry, stop, target = setup_levels(
        high=110,
        low=100,
        entry_buffer_frac=0.0,
        stop_buffer_frac=0.0,
        reward_risk=4.0,
        stop_pad_ranges=1.0,
    )
    assert entry == 110
    # pad 1.0 * range(10) → stop at 100-10=90
    assert stop == 90
    assert target == 110 + 4 * (110 - 90)


def test_cost_gate_rejects_uneconomic():
    # Small reward vs large costs
    net = expected_net_at_target(
        qty=10,
        entry=100,
        stop=99.8,
        target=100.8,
        reward_risk=4.0,
        entry_cost_total=50.0,
        exit_cost_total=5.0,
    )
    assert net < 0
