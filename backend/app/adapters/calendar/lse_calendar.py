"""Europe/London LSE session calendar helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

LONDON = ZoneInfo("Europe/London")


class LseSessionCalendar:
    """LSE trading calendar with DST-aware session bounds."""

    def __init__(self) -> None:
        self._cal = xcals.get_calendar("XLON")

    def is_trading_day(self, d: date) -> bool:
        """Return True if LSE is open for equities session."""
        return bool(self._cal.is_session(pd_timestamp(d)))

    def session_open_close(self, d: date) -> tuple[datetime, datetime] | None:
        """Return (open, close) in Europe/London, or None if holiday."""
        if not self.is_trading_day(d):
            return None
        # Standard LSE continuous session; early closes noted in docs
        open_dt = datetime.combine(d, time(8, 0), tzinfo=LONDON)
        close_dt = datetime.combine(d, time(16, 30), tzinfo=LONDON)
        return open_dt, close_dt

    def previous_session(self, d: date) -> date:
        """Most recent session on or before d."""
        cur = d
        for _ in range(15):
            if self.is_trading_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise RuntimeError(f"No LSE session found near {d}")

    def sessions_between(self, start: date, end: date) -> list[date]:
        """Inclusive list of sessions."""
        out: list[date] = []
        cur = start
        while cur <= end:
            if self.is_trading_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out

    def expected_intraday_bars(
        self, d: date, interval_minutes: int = 5
    ) -> int:
        """Approximate regular-session bar count (ignores auctions)."""
        bounds = self.session_open_close(d)
        if not bounds:
            return 0
        open_dt, close_dt = bounds
        minutes = int((close_dt - open_dt).total_seconds() // 60)
        return minutes // interval_minutes


def pd_timestamp(d: date):
    """Convert date to pandas Timestamp for exchange_calendars."""
    import pandas as pd

    return pd.Timestamp(d)
