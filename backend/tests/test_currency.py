"""GBX / GBP conversion tests."""

from app.services.ingestion.currency import detect_likely_gbx, price_scale_for_currency, to_gbp


def test_gbx_scale() -> None:
    """GBX prices convert by 0.01."""
    assert price_scale_for_currency("GBX") == 0.01
    assert to_gbp(250.0, "GBX") == 2.5


def test_gbp_unchanged() -> None:
    """GBP prices stay as-is."""
    assert to_gbp(12.5, "GBP") == 12.5


def test_detect_gbx_heuristic() -> None:
    """Large medians suggest pence quotation."""
    assert detect_likely_gbx([75.0, 80.0, 90.0]) is True
    assert detect_likely_gbx([1.2, 1.5, 1.1]) is False
