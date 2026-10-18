"""Fixture provider and duplicate-bar persistence smoke tests."""

from datetime import date, datetime, timezone

from app.adapters.market_data.fixture import FixtureMarketDataProvider
from app.services.intraday.engine import portfolio_metrics


def test_fixture_daily_nonempty() -> None:
    """Synthetic daily CSV loads for VOD.L."""
    p = FixtureMarketDataProvider()
    rows = p.fetch_daily(
        ["VOD.L"], date(2024, 1, 1), date(2024, 6, 1)
    )
    assert len(rows) > 20
    assert all(r.symbol == "VOD.L" for r in rows)


def test_fixture_health() -> None:
    """Fixture healthcheck is always ok and labelled synthetic."""
    ok, msg = FixtureMarketDataProvider().healthcheck()
    assert ok
    assert "synthetic" in msg.lower() or "fixture" in msg.lower()


def test_portfolio_metrics_empty() -> None:
    """Empty trade list reports insufficient sample."""
    m = portfolio_metrics([])
    assert m["n"] == 0


def test_portfolio_metrics_basic() -> None:
    """Expectancy uses net PnL."""
    m = portfolio_metrics(
        [
            {"net_pnl": 10.0, "gross_pnl": 12.0, "costs": 2.0},
            {"net_pnl": -5.0, "gross_pnl": -3.0, "costs": 2.0},
        ]
    )
    assert m["n"] == 2
    assert m["win_rate"] == 0.5
    assert m["expectancy"] == 2.5
