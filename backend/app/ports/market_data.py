"""Market data provider port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class BarRow:
    """Normalised OHLCV row from a provider (market data, not our trades)."""

    symbol: str
    bar_ts: datetime
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid: float | None = None
    ask: float | None = None
    currency_hint: str | None = None


@dataclass(frozen=True)
class CorporateActionRow:
    """Provider corporate action."""

    symbol: str
    action_date: date
    action_type: str
    value: float | None
    raw: dict | None = None


class MarketDataProvider(Protocol):
    """Fetch completed market bars — never paper/sim executions."""

    name: str

    def fetch_daily(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[BarRow]:
        """Fetch daily bars inclusive of start/end session dates."""

    def fetch_intraday(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval_minutes: int = 5,
    ) -> list[BarRow]:
        """Fetch intraday bars; may be limited by provider lookback."""

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[CorporateActionRow]:
        """Fetch available corporate actions if supported."""

    def healthcheck(self) -> tuple[bool, str]:
        """Return (ok, message) for provider availability."""
