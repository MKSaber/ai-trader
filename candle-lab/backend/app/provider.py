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

_YF_INTERVAL = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "60m", 90: "90m"}


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


def fetch_intraday(
    symbol: str,
    period: str = "5d",
    *,
    interval_minutes: int | None = None,
) -> tuple[pd.DataFrame, FeedStatus]:
    """Fetch intraday bars at the configured (or overridden) interval."""
    settings = get_settings()
    mins = interval_minutes if interval_minutes is not None else settings.interval_minutes
    yf_interval = _YF_INTERVAL.get(mins, "60m")
    arrival = datetime.now(timezone.utc)
    ticker = yf.Ticker(symbol, session=_session())
    frame = ticker.history(
        period=period,
        interval=yf_interval,
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
            message=f"yfinance returned empty {yf_interval} history for {symbol}",
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
    interval_sec = mins * 60
    age = (arrival - last_event).total_seconds()
    df["closed"] = True
    if age < interval_sec:
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
            f"Interval {yf_interval}; last bar event age ≈ {delay:.0f}s."
        ),
    )
    return df, status


def fetch_intraday_5m(symbol: str, period: str = "5d") -> tuple[pd.DataFrame, FeedStatus]:
    """Back-compat alias — prefers settings.interval_minutes (v2.6 → 60m)."""
    return fetch_intraday(symbol, period=period)


def london_today():
    return datetime.now(LONDON).date()
