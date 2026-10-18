"""UK-aware trading cost model — assumptions are configurable and visible.

SDRT note (GOV.UK): the principal SDRT rate on UK share purchases is generally
0.5% of consideration. This codebase historically used stamp_duty_rate=0.01
(1%) as a stress assumption. Named scenarios preserve that baseline and offer
an explicit sdrt_0_5pct alternative. See docs/RESEARCH_CONFIG.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from app.core.config import Settings, get_settings

# Named stamp scenarios — do not silently change the default stress rate.
STAMP_SCENARIOS: dict[str, float] = {
    "stress_1pct": 0.01,  # historical / stress default in Settings
    "sdrt_0_5pct": 0.005,  # principal SDRT rate (GOV.UK)
}


@dataclass(frozen=True)
class CostAssumptions:
    """Visible cost parameters."""

    commission_bps: float
    spread_bps: float
    slippage_bps: float
    stamp_duty_rate: float
    stamp_scenario: str = "stress_1pct"

    def to_dict(self) -> dict:
        """Serialize assumptions."""
        return asdict(self)


def load_cost_assumptions(
    settings: Settings | None = None,
    *,
    stamp_scenario: str | None = None,
) -> CostAssumptions:
    """Load cost assumptions from settings, optionally overriding stamp scenario."""
    cfg = settings or get_settings()
    scenario = stamp_scenario or "stress_1pct"
    if scenario not in STAMP_SCENARIOS:
        raise ValueError(
            f"Unknown stamp_scenario={scenario!r}; "
            f"choose from {sorted(STAMP_SCENARIOS)}"
        )
    # Preserve Settings.stamp_duty_rate when using stress_1pct so env overrides
    # still apply to the historical baseline.
    if scenario == "stress_1pct":
        stamp = cfg.stamp_duty_rate
    else:
        stamp = STAMP_SCENARIOS[scenario]
    return CostAssumptions(
        commission_bps=cfg.commission_bps,
        spread_bps=cfg.spread_bps,
        slippage_bps=cfg.slippage_bps,
        stamp_duty_rate=stamp,
        stamp_scenario=scenario,
    )


def with_stamp_scenario(
    assumptions: CostAssumptions, scenario: str
) -> CostAssumptions:
    """Return a copy with a named stamp scenario applied."""
    if scenario not in STAMP_SCENARIOS:
        raise ValueError(f"Unknown stamp_scenario={scenario!r}")
    if scenario == "stress_1pct":
        # Keep whatever rate is already on the object (env override friendly)
        return replace(assumptions, stamp_scenario=scenario)
    return replace(
        assumptions,
        stamp_duty_rate=STAMP_SCENARIOS[scenario],
        stamp_scenario=scenario,
    )


def estimate_round_trip_cost_fraction(
    assumptions: CostAssumptions,
    *,
    side: str = "long",
    is_uk_share_purchase: bool | None = None,
) -> float:
    """Estimate proportional round-trip cost as fraction of notional.

    Spread is modelled as half the quoted spread each side (entry + exit).
    Stamp duty applies only on UK share *purchases* (long entries), not on
    short sales. Pass side='short' or is_uk_share_purchase=False to exclude it.

    With defaults (5/10/5 bps + 1% stamp long):
      2*(0.001 + 0.0005 + 0.0005) + 0.01 = 0.014 (1.4%).
    Short with same bps and no stamp: 0.004 (0.4%).
    """
    half_spread = assumptions.spread_bps / 10_000.0
    slip = assumptions.slippage_bps / 10_000.0
    commission = assumptions.commission_bps / 10_000.0
    if is_uk_share_purchase is None:
        is_uk_share_purchase = side == "long"
    stamp = assumptions.stamp_duty_rate if is_uk_share_purchase else 0.0
    return 2 * (half_spread + slip + commission) + stamp


def apply_entry_price(
    mid: float,
    assumptions: CostAssumptions,
    *,
    side: str = "buy",
) -> float:
    """Adverse selection on entry mid (one-way half-spread + slippage)."""
    adj = (assumptions.spread_bps / 2.0 + assumptions.slippage_bps) / 10_000.0
    if side == "buy":
        return mid * (1.0 + adj)
    return mid * (1.0 - adj)


def purchase_costs(notional_gbp: float, assumptions: CostAssumptions) -> float:
    """Absolute GBP costs on a long entry (commission + stamp duty share)."""
    commission = notional_gbp * assumptions.commission_bps / 10_000.0
    stamp = notional_gbp * assumptions.stamp_duty_rate
    return commission + stamp


def sale_costs(notional_gbp: float, assumptions: CostAssumptions) -> float:
    """Absolute GBP costs on exit (commission only; no stamp duty)."""
    return notional_gbp * assumptions.commission_bps / 10_000.0
