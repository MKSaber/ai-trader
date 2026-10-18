"""Isolated SQLite/Postgres persistence for candle-lab."""

from __future__ import annotations

from datetime import datetime
from typing import Generator

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    detector_version: Mapped[str] = mapped_column(String(64))
    trade_rules_version: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionRun(Base):
    __tablename__ = "session_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(Integer)
    session_date: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="running")
    feed_label: Mapped[str] = mapped_column(String(64))
    feed_is_realtime: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class CandleBar(Base):
    __tablename__ = "candle_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "bar_start", "interval_minutes", name="uq_bar"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    closed: Mapped[bool] = mapped_column(Boolean, default=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PatternSignal(Base):
    __tablename__ = "pattern_signals"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "pattern", "confirm_bar_start", "detector_version",
            name="uq_signal",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_run_id: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(32))
    pattern: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16))
    confirm_bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detector_version: Mapped[str] = mapped_column(String(64))
    bars_json: Mapped[str] = mapped_column(Text)
    conditions_json: Mapped[str] = mapped_column(Text)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    visual_review: Mapped[str | None] = mapped_column(String(32))
    visual_note: Mapped[str | None] = mapped_column(Text)


class Setup(Base):
    __tablename__ = "setups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(Integer)
    session_run_id: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(16), default="long")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    entry_trigger: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    expiry_bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rules_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperFill(Base):
    __tablename__ = "paper_fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # entry|exit
    fill_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(64))
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)


class LedgerSnapshot(Base):
    __tablename__ = "ledger_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_run_id: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cash_gbp: Mapped[float] = mapped_column(Float)
    equity_gbp: Mapped[float] = mapped_column(Float)
    exposure_gbp: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


def _engine():
    s = get_settings()
    url = s.database_url_sqlite if s.use_sqlite else s.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
