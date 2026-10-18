"""Persist provider bars into Postgres with watermarks and revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.ports.market_data import BarRow
from app.services.ingestion.currency import to_gbp


def get_or_create_instrument(
    db: Session, symbol: str, currency_hint: str | None = "GBX"
) -> m.Instrument:
    """Find instrument by yahoo symbol or create it."""
    inst = db.scalar(
        select(m.Instrument).where(m.Instrument.yahoo_symbol == symbol)
    )
    if inst:
        return inst
    bare = symbol.replace(".L", "")
    inst = m.Instrument(
        symbol=bare,
        yahoo_symbol=symbol,
        name=bare,
        currency_quoted=currency_hint or "GBX",
        price_scale_to_gbp=0.01 if (currency_hint or "GBX").upper() in {"GBX", "GBp"} else 1.0,
    )
    db.add(inst)
    db.flush()
    return inst


def start_batch(
    db: Session,
    *,
    provider_key: str,
    session_date=None,
    upload_id: int | None = None,
) -> m.IngestionBatch:
    """Create ingestion batch row."""
    src = db.scalar(
        select(m.DataSource).where(m.DataSource.provider_key == provider_key)
    )
    if not src:
        src = m.DataSource(name=provider_key, provider_key=provider_key)
        db.add(src)
        db.flush()
    batch = m.IngestionBatch(
        data_source_id=src.id,
        upload_id=upload_id,
        batch_key=f"{provider_key}-{uuid4().hex[:12]}",
        session_date=session_date,
        status="running",
    )
    db.add(batch)
    db.flush()
    return batch


def persist_daily_bars(
    db: Session,
    bars: list[BarRow],
    batch: m.IngestionBatch,
    *,
    allow_revision: bool = False,
) -> int:
    """Insert daily bars idempotently.

    Identical current rows are skipped. When allow_revision=True and values
    differ, the prior current row is retired and a new revision is inserted
    (predictions are never rewritten).
    """
    n = 0
    for bar in bars:
        inst = get_or_create_instrument(db, bar.symbol, bar.currency_hint)
        existing = db.scalar(
            select(m.MarketBarDaily).where(
                m.MarketBarDaily.instrument_id == inst.id,
                m.MarketBarDaily.session_date == bar.session_date,
                m.MarketBarDaily.is_current.is_(True),
            )
        )
        cur = bar.currency_hint or inst.currency_quoted
        open_gbp = to_gbp(bar.open, cur)
        high_gbp = to_gbp(bar.high, cur)
        low_gbp = to_gbp(bar.low, cur)
        close_gbp = to_gbp(bar.close, cur)
        revision = 1
        if existing:
            same = (
                abs(existing.close_raw - bar.close) < 1e-9
                and abs(existing.open_raw - bar.open) < 1e-9
                and abs(existing.volume - bar.volume) < 1e-9
            )
            if same or not allow_revision:
                continue
            existing.is_current = False
            revision = int(existing.revision) + 1
            batch.revises_batch_id = existing.source_batch_id
        db.add(
            m.MarketBarDaily(
                instrument_id=inst.id,
                session_date=bar.session_date,
                open_raw=bar.open,
                high_raw=bar.high,
                low_raw=bar.low,
                close_raw=bar.close,
                volume=bar.volume,
                open_gbp=open_gbp,
                high_gbp=high_gbp,
                low_gbp=low_gbp,
                close_gbp=close_gbp,
                source_batch_id=batch.id,
                revision=revision,
                is_current=True,
            )
        )
        n += 1
        _touch_watermark(db, inst.id, "daily", 0, bar.bar_ts)
    db.flush()
    return n


def persist_intraday_bars(
    db: Session,
    bars: list[BarRow],
    batch: m.IngestionBatch,
    interval_minutes: int = 5,
) -> int:
    """Insert intraday bars idempotently."""
    n = 0
    for bar in bars:
        inst = get_or_create_instrument(db, bar.symbol, bar.currency_hint)
        existing = db.scalar(
            select(m.MarketBarIntraday).where(
                m.MarketBarIntraday.instrument_id == inst.id,
                m.MarketBarIntraday.bar_ts == bar.bar_ts,
                m.MarketBarIntraday.interval_minutes == interval_minutes,
                m.MarketBarIntraday.is_current.is_(True),
            )
        )
        if existing:
            continue
        cur = bar.currency_hint or inst.currency_quoted
        db.add(
            m.MarketBarIntraday(
                instrument_id=inst.id,
                bar_ts=bar.bar_ts,
                session_date=bar.session_date,
                interval_minutes=interval_minutes,
                open_raw=bar.open,
                high_raw=bar.high,
                low_raw=bar.low,
                close_raw=bar.close,
                volume=bar.volume,
                bid=bar.bid,
                ask=bar.ask,
                open_gbp=to_gbp(bar.open, cur),
                high_gbp=to_gbp(bar.high, cur),
                low_gbp=to_gbp(bar.low, cur),
                close_gbp=to_gbp(bar.close, cur),
                source_batch_id=batch.id,
                revision=1,
                is_current=True,
            )
        )
        n += 1
        _touch_watermark(db, inst.id, "intraday", interval_minutes, bar.bar_ts)
    db.flush()
    return n


def _touch_watermark(
    db: Session,
    instrument_id: int,
    bar_kind: str,
    interval_minutes: int,
    bar_ts: datetime,
) -> None:
    """Update high-water mark; safe under Session(autoflush=False)."""
    # Prefer pending session objects first (autoflush is disabled).
    for obj in db.new:
        if (
            isinstance(obj, m.IngestionWatermark)
            and obj.instrument_id == instrument_id
            and obj.bar_kind == bar_kind
            and obj.interval_minutes == interval_minutes
        ):
            if _ts_key(bar_ts) > _ts_key(obj.last_bar_ts):
                obj.last_bar_ts = bar_ts
            return

    wm = db.scalar(
        select(m.IngestionWatermark).where(
            m.IngestionWatermark.instrument_id == instrument_id,
            m.IngestionWatermark.bar_kind == bar_kind,
            m.IngestionWatermark.interval_minutes == interval_minutes,
        )
    )
    if wm is None:
        db.add(
            m.IngestionWatermark(
                instrument_id=instrument_id,
                bar_kind=bar_kind,
                interval_minutes=interval_minutes,
                last_bar_ts=bar_ts,
            )
        )
    elif _ts_key(bar_ts) > _ts_key(wm.last_bar_ts):
        wm.last_bar_ts = bar_ts
        wm.updated_at = datetime.now(timezone.utc)


def _ts_key(ts: datetime) -> datetime:
    """Normalize datetimes for comparison (SQLite may drop tzinfo)."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def complete_batch(db: Session, batch: m.IngestionBatch, status: str = "success") -> None:
    """Mark batch complete."""
    batch.status = status
    batch.completed_at = datetime.now(timezone.utc)
    db.flush()
