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


def test_v22_stay_green_defaults():
    r = load_trade_rules("trade-rules-v2.2")
    assert r.interval == "60m"
    assert r.reward_risk == 5.0
    assert r.bullish_patterns == ("bullish_engulfing",)
    assert r.trade_hours_london == (15,)
    assert r.cooloff_after_stop is True
    assert r.max_stops_per_symbol == 2
    assert r.trail_breakeven_r is None
    assert r.min_stop_pct == 0.003
    assert r.risk_frac == 0.015
    assert r.max_position_frac == 0.35


def test_v23_broad_book_defaults():
    r = load_trade_rules("trade-rules-v2.3")
    assert r.trade_hours_london == (15,)
    assert r.cooloff_after_stop is True
    assert "III.L" in r.blocklist_set


def test_v24_golden_unified_defaults():
    r = load_trade_rules("trade-rules-v2.4")
    assert r.reward_risk == 6.0
    assert r.trade_hours_london == (15,)


def test_v25_fullday_golden_defaults():
    r = load_trade_rules("trade-rules-v2.5")
    assert r.reward_risk == 7.0
    assert r.trade_hours_london == (10, 11, 12, 13, 14, 15)
    assert r.min_downtrend_pct == 0.02
    assert r.cooloff_after_stop is True
    assert r.max_stops_per_symbol == 2
    assert r.risk_frac == 0.015
    assert r.max_position_frac == 0.35
    assert r.large_book_cash_gbp is None
    assert r.sizing_for_cash(20_000) == r.sizing_for_cash(100_000)
    # patterns-v2 confirms stay off for frozen v2.5
    assert r.min_volume_ratio == 0.0
    assert r.require_next_open_confirm is False
    assert r.require_close_in_upper_half is False
    assert "III.L" in r.blocklist_set
    for sym in (
        "HSBA.L",
        "AZN.L",
        "SHEL.L",
        "RIO.L",
        "BATS.L",
        "ULVR.L",
        "BP.L",
        "GSK.L",
        "NG.L",
        "REL.L",
    ):
        assert sym not in r.blocklist_set


def test_v26_patterns_harami_golden():
    r = load_trade_rules("trade-rules-v2.6")
    assert r.reward_risk == 7.0
    assert r.trade_hours_london == (10, 11, 12, 13, 14, 15)
    assert r.min_downtrend_pct == 0.02
    assert r.bullish_patterns == ("bullish_engulfing", "bullish_harami")
    assert r.min_volume_ratio == 0.0
    assert r.require_next_open_confirm is False
    assert r.require_close_in_upper_half is False
    assert r.sizing_for_cash(20_000) == r.sizing_for_cash(100_000)
    assert "III.L" in r.blocklist_set


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
