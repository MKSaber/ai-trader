"""Yahoo Finance prototype provider via yfinance.

Unofficial integration intended for personal research/education.
Intraday history cannot extend beyond the last ~60 days per yfinance docs.
Never silently substitute synthetic data on failure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from app.ports.market_data import BarRow, CorporateActionRow


class YFinanceMarketDataProvider:
    """Fetch LSE bars using Yahoo symbols (e.g. VOD.L)."""

    name = "yfinance"
    MAX_INTRADAY_LOOKBACK_DAYS = 60

    def fetch_daily(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[BarRow]:
        """Download daily OHLCV."""
        rows: list[BarRow] = []
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                prepost=False,
            )
            rows.extend(self._frame_to_bars(symbol, frame, interval_daily=True))
        return rows

    def fetch_intraday(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval_minutes: int = 5,
    ) -> list[BarRow]:
        """Download intraday bars within Yahoo lookback limits."""
        if interval_minutes not in {1, 2, 5, 15, 30, 60, 90}:
            raise ValueError(f"Unsupported interval minutes: {interval_minutes}")
        earliest = datetime.now(timezone.utc) - timedelta(
            days=self.MAX_INTRADAY_LOOKBACK_DAYS
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start < earliest:
            start = earliest

        interval = f"{interval_minutes}m"
        rows: list[BarRow] = []
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            # period-based fetch is more reliable for recent intraday
            period = "60d" if interval_minutes >= 5 else "7d"
            frame = ticker.history(
                period=period,
                interval=interval,
                auto_adjust=False,
                actions=False,
                prepost=False,
            )
            if frame.empty:
                continue
            # Filter to requested window
            idx = frame.index
            if idx.tz is None:
                frame.index = idx.tz_localize("UTC")
            mask = (frame.index >= start) & (frame.index <= end)
            frame = frame.loc[mask]
            rows.extend(
                self._frame_to_bars(symbol, frame, interval_daily=False)
            )
        return rows

    def fetch_corporate_actions(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[CorporateActionRow]:
        """Best-effort dividends/splits from yfinance."""
        out: list[CorporateActionRow] = []
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            try:
                actions = ticker.actions
            except Exception:
                continue
            if actions is None or actions.empty:
                continue
            for ts, row in actions.iterrows():
                d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
                if d < start or d > end:
                    continue
                if float(row.get("Dividends", 0) or 0) != 0:
                    out.append(
                        CorporateActionRow(
                            symbol=symbol,
                            action_date=d,
                            action_type="dividend",
                            value=float(row["Dividends"]),
                            raw=row.to_dict(),
                        )
                    )
                if float(row.get("Stock Splits", 0) or 0) != 0:
                    out.append(
                        CorporateActionRow(
                            symbol=symbol,
                            action_date=d,
                            action_type="split",
                            value=float(row["Stock Splits"]),
                            raw=row.to_dict(),
                        )
                    )
        return out

    def healthcheck(self) -> tuple[bool, str]:
        """Probe a liquid LSE symbol."""
        try:
            frame = yf.Ticker("VOD.L").history(period="5d", interval="1d")
            if frame.empty:
                return False, "yfinance returned empty daily data for VOD.L"
            return True, "yfinance reachable (prototype feed)"
        except Exception as exc:  # noqa: BLE001
            return False, f"yfinance healthcheck failed: {exc}"

    def _frame_to_bars(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        interval_daily: bool,
    ) -> list[BarRow]:
        """Convert a Yahoo history frame to BarRow list."""
        if frame is None or frame.empty:
            return []
        rows: list[BarRow] = []
        for ts, row in frame.iterrows():
            if hasattr(ts, "to_pydatetime"):
                bar_ts = ts.to_pydatetime()
            else:
                bar_ts = pd.Timestamp(ts).to_pydatetime()
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=timezone.utc)
            session = bar_ts.astimezone(
                __import__("zoneinfo").ZoneInfo("Europe/London")
            ).date()
            rows.append(
                BarRow(
                    symbol=symbol,
                    bar_ts=bar_ts if not interval_daily else datetime(
                        session.year,
                        session.month,
                        session.day,
                        tzinfo=__import__("zoneinfo").ZoneInfo("Europe/London"),
                    ),
                    session_date=session,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume", 0) or 0),
                    currency_hint="GBX",
                )
            )
        return rows
