"""UK-aware trading cost model — assumptions are configurable and visible."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class CostAssumptions:
    """Visible cost parameters."""

    commission_bps: float
    spread_bps: float
    slippage_bps: float
    stamp_duty_rate: float

    def to_dict(self) -> dict:
        """Serialize assumptions."""
        return asdict(self)


def load_cost_assumptions(settings: Settings | None = None) -> CostAssumptions:
    """Load cost assumptions from settings."""
    cfg = settings or get_settings()
    return CostAssumptions(
        commission_bps=cfg.commission_bps,
        spread_bps=cfg.spread_bps,
        slippage_bps=cfg.slippage_bps,
        stamp_duty_rate=cfg.stamp_duty_rate,
    )


def estimate_round_trip_cost_fraction(
    assumptions: CostAssumptions,
    *,
    is_uk_share_purchase: bool = True,
) -> float:
    """Estimate proportional round-trip cost as fraction of notional.

    Includes one-way stamp duty on purchase of UK shares where applicable.
    """
    half_spread = assumptions.spread_bps / 10_000.0
    slip = assumptions.slippage_bps / 10_000.0
    commission = assumptions.commission_bps / 10_000.0
    # Round trip: entry + exit spread/slip/commission; stamp duty on buy only
    stamp = assumptions.stamp_duty_rate if is_uk_share_purchase else 0.0
    return 2 * (half_spread + slip + commission) + stamp


def apply_entry_price(
    mid: float,
    assumptions: CostAssumptions,
    *,
    side: str = "buy",
) -> float:
    """Adverse selection on entry mid."""
    adj = (assumptions.spread_bps + assumptions.slippage_bps) / 10_000.0
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
