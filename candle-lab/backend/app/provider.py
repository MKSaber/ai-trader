"""Market data adapter for candle-lab.

Uses yfinance + curl_cffi. Yahoo intraday is typically delayed and unofficial.
This feed is labelled DELAYED — never presented as real-time broker data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from app.config import get_settings

LONDON = ZoneInfo("Europe/London")


@dataclass
class FeedStatus:
    label: str
    is_realtime: bool
    last_bar_event_ts: datetime | None
    last_arrival_ts: datetime | None
    delay_seconds: float | None
    healthy: bool
    message: str


def _session():
    return curl_requests.Session(impersonate="chrome")


def fetch_intraday_5m(symbol: str, period: str = "5d") -> tuple[pd.DataFrame, FeedStatus]:
    """Fetch 5-minute bars. Returns closed+forming rows; caller marks closed."""
    settings = get_settings()
    arrival = datetime.now(timezone.utc)
    ticker = yf.Ticker(symbol, session=_session())
    frame = ticker.history(
        period=period,
        interval="5m",
        auto_adjust=False,
        prepost=False,
        actions=False,
    )
    if frame is None or frame.empty:
        status = FeedStatus(
            label=settings.feed_label,
            is_realtime=False,
            last_bar_event_ts=None,
            last_arrival_ts=arrival,
            delay_seconds=None,
            healthy=False,
            message=f"yfinance returned empty 5m history for {symbol}",
        )
        return pd.DataFrame(), status

    df = frame.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(
        columns={
            ts_col: "bar_start",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["bar_start"] = pd.to_datetime(df["bar_start"], utc=True)
    df = df[["bar_start", "open", "high", "low", "close", "volume"]].dropna()
    last_event = df["bar_start"].iloc[-1].to_pydatetime()
    if last_event.tzinfo is None:
        last_event = last_event.replace(tzinfo=timezone.utc)
    delay = (arrival - last_event).total_seconds()
    # Forming bar: if last bar started less than interval ago, mark incomplete
    interval = settings.interval_minutes * 60
    age = (arrival - last_event).total_seconds()
    df["closed"] = True
    if age < interval:
        df.loc[df.index[-1], "closed"] = False

    status = FeedStatus(
        label=settings.feed_label,
        is_realtime=False,
        last_bar_event_ts=last_event,
        last_arrival_ts=arrival,
        delay_seconds=delay,
        healthy=True,
        message=(
            "DELAYED Yahoo Finance via yfinance — not a real-time broker feed. "
            "Unsuitable to prove timely live execution. "
            f"Last bar event age ≈ {delay:.0f}s."
        ),
    )
    return df, status


def london_today():
    return datetime.now(LONDON).date()
