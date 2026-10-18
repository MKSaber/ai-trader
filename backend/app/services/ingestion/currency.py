"""GBP / GBX normalisation helpers."""

from __future__ import annotations

GBX_TO_GBP = 0.01


def price_scale_for_currency(currency: str | None) -> float:
    """Return multiplier to convert quoted price to GBP."""
    if currency is None:
        return GBX_TO_GBP  # LSE equities commonly quoted in pence
    c = currency.upper()
    if c in {"GBX", "GBp", "PENCE"}:
        return GBX_TO_GBP
    if c == "GBP":
        return 1.0
    # Unknown — leave as-is but callers should record currency
    return 1.0


def to_gbp(price: float, currency: str | None) -> float:
    """Convert a raw quoted price to GBP."""
    return price * price_scale_for_currency(currency)


def detect_likely_gbx(prices: list[float]) -> bool:
    """Heuristic: typical LSE share prices in GBP are rarely > 500.

    Large medians suggest GBX quotation.
    """
    if not prices:
        return True
    mid = sorted(prices)[len(prices) // 2]
    return mid > 20.0
