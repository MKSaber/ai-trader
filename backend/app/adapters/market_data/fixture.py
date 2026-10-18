"""Fixture / synthetic market-data provider for explicit offline demos."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.ports.market_data import BarRow, CorporateActionRow


class FixtureMarketDataProvider:
    """Load labelled synthetic bars from sample_data or generate demos.

    Must only be used when DEMO_MODE / --offline is explicit.
    """

    name = "fixture"

    def __init__(self, sample_dir: str | Path | None = None) -> None:
        self._sample_dir = Path(sample_dir or Path(__file__).resolve().parents[3] / "sample_data")

    def fetch_daily(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[BarRow]:
        """Read synthetic daily CSV or generate a deterministic series."""
        path = self._sample_dir / "synthetic_daily_ohlcv.csv"
        if path.exists():
            return self._read_csv(path, symbols, start, end, daily=True)
        return self._generate(symbols, start, end, daily=True)

    def fetch_intraday(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval_minutes: int = 5,
    ) -> list[BarRow]:
        """Read synthetic intraday CSV or generate bars."""
        del interval_minutes
        path = self._sample_dir / "synthetic_intraday_5m.csv"
        start_d = start.date()
        end_d = end.date()
        if path.exists():
            return self._read_csv(path, symbols, start_d, end_d, daily=False)
        return self._generate(symbols, start_d, end_d, daily=False)

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[CorporateActionRow]:
        """No corporate actions in fixture by default."""
        del symbols, start, end
        return []

    def healthcheck(self) -> tuple[bool, str]:
        """Fixture is always available."""
        return True, "fixture provider (synthetic — not live market data)"

    def _read_csv(
        self,
        path: Path,
        symbols: list[str],
        start: date,
        end: date,
        *,
        daily: bool,
    ) -> list[BarRow]:
        rows: list[BarRow] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                sym = raw["symbol"]
                if symbols and sym not in symbols:
                    continue
                ts = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
                session = date.fromisoformat(raw["session_date"])
                if session < start or session > end:
                    continue
                rows.append(
                    BarRow(
                        symbol=sym,
                        bar_ts=ts,
                        session_date=session,
                        open=float(raw["open"]),
                        high=float(raw["high"]),
                        low=float(raw["low"]),
                        close=float(raw["close"]),
                        volume=float(raw.get("volume", 0) or 0),
                        currency_hint=raw.get("currency", "GBX"),
                    )
                )
        del daily
        return rows

    def _generate(
        self,
        symbols: list[str],
        start: date,
        end: date,
        *,
        daily: bool,
    ) -> list[BarRow]:
        """Deterministic synthetic walk labelled as synthetic."""
        rows: list[BarRow] = []
        for symbol in symbols:
            price = 100.0 + (sum(ord(c) for c in symbol) % 50)
            d = start
            while d <= end:
                if d.weekday() < 5:
                    if daily:
                        o, c = price, price * 1.001
                        rows.append(
                            BarRow(
                                symbol=symbol,
                                bar_ts=datetime(
                                    d.year, d.month, d.day, 16, 30, tzinfo=timezone.utc
                                ),
                                session_date=d,
                                open=o,
                                high=max(o, c) * 1.002,
                                low=min(o, c) * 0.998,
                                close=c,
                                volume=1_000_000,
                                currency_hint="GBX",
                            )
                        )
                        price = c
                    else:
                        t = datetime(d.year, d.month, d.day, 8, 0, tzinfo=timezone.utc)
                        end_t = datetime(
                            d.year, d.month, d.day, 16, 30, tzinfo=timezone.utc
                        )
                        while t < end_t:
                            o, c = price, price * (1.0 + ((hash((symbol, t)) % 7) - 3) * 0.0005)
                            rows.append(
                                BarRow(
                                    symbol=symbol,
                                    bar_ts=t,
                                    session_date=d,
                                    open=o,
                                    high=max(o, c) * 1.001,
                                    low=min(o, c) * 0.999,
                                    close=c,
                                    volume=10_000,
                                    currency_hint="GBX",
                                )
                            )
                            price = c
                            t += timedelta(minutes=5)
                d += timedelta(days=1)
        return rows
