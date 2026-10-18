"""Broker / tax cost model — GOV.UK SDRT + PTM + T212/eToro profiles."""

from app.config import BROKER_PROFILES, Settings, apply_broker_profile
from app.paper import entry_costs, exit_costs


def test_trading212_profile_zero_commission_and_sdrt():
    s = apply_broker_profile(Settings(), "trading212")
    assert s.commission_bps == 0.0
    assert s.stamp_duty_rate == 0.005
    assert s.ptm_levy_gbp == 1.50
    entry = entry_costs(5_000.0, s)
    assert entry.commission == 0.0
    assert abs(entry.stamp - 25.0) < 1e-9  # 0.5% of 5000
    assert entry.ptm == 0.0  # below £10k threshold


def test_ptm_levy_both_sides_above_threshold():
    s = apply_broker_profile(Settings(), "trading212")
    entry = entry_costs(12_000.0, s)
    exit_ = exit_costs(12_000.0, s)
    assert entry.ptm == 1.50
    assert exit_.ptm == 1.50
    assert exit_.stamp == 0.0  # no SDRT on sale


def test_etoro_flat_adds_flat_commission():
    s = apply_broker_profile(Settings(), "etoro_flat_usd")
    entry = entry_costs(1_000.0, s)
    assert abs(entry.commission - 1.55) < 1e-9
    assert abs(entry.stamp - 5.0) < 1e-9


def test_all_broker_profiles_load():
    for name in BROKER_PROFILES:
        s = apply_broker_profile(Settings(), name)
        assert s.cost_profile == name
        assert s.stamp_duty_rate == 0.005
