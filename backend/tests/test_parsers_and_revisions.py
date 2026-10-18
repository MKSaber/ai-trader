"""CSV/XLSX parsing and bar revision lineage tests."""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db import models as m
from app.ports.market_data import BarRow
from app.services.ingestion.parsers import parse_market_rows, preview_columns
from app.services.ingestion.persist import (
    complete_batch,
    persist_daily_bars,
    start_batch,
)


def test_preview_and_parse_csv() -> None:
    """CSV headers map and parse into bars."""
    raw = (
        b"symbol,date,open,high,low,close,volume,currency\n"
        b"VOD.L,2024-01-02,100,101,99,100.5,1000,GBX\n"
    )
    preview = preview_columns(raw, "x.csv")
    assert preview["missing_required"] == []
    bars = parse_market_rows(raw, "x.csv")
    assert len(bars) == 1
    assert bars[0].symbol == "VOD.L"
    assert bars[0].close == 100.5


def test_parse_xlsx_roundtrip(tmp_path) -> None:
    """XLSX files parse via openpyxl."""
    from openpyxl import Workbook

    path = tmp_path / "mkt.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["symbol", "date", "open", "high", "low", "close", "volume"])
    ws.append(["BP.L", "2024-02-01", 500, 510, 490, 505, 2000])
    wb.save(path)
    bars = parse_market_rows(path.read_bytes(), "mkt.xlsx")
    assert len(bars) == 1
    assert bars[0].symbol == "BP.L"


def test_revision_keeps_history() -> None:
    """Corrected bar creates a new revision; old row remains non-current."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db: Session = SessionLocal()
    try:
        batch1 = start_batch(db, provider_key="test", session_date=date(2024, 1, 2))
        bars = [
            BarRow(
                symbol="VOD.L",
                bar_ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
                session_date=date(2024, 1, 2),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
                currency_hint="GBX",
            )
        ]
        assert persist_daily_bars(db, bars, batch1) == 1
        complete_batch(db, batch1)
        db.commit()

        batch2 = start_batch(db, provider_key="test", session_date=date(2024, 1, 2))
        bars[0] = BarRow(
            symbol="VOD.L",
            bar_ts=bars[0].bar_ts,
            session_date=date(2024, 1, 2),
            open=100,
            high=101,
            low=99,
            close=102,  # correction
            volume=1,
            currency_hint="GBX",
        )
        assert persist_daily_bars(db, bars, batch2, allow_revision=True) == 1
        complete_batch(db, batch2)
        db.commit()

        all_rows = db.scalars(select(m.MarketBarDaily)).all()
        assert len(all_rows) == 2
        current = [r for r in all_rows if r.is_current]
        retired = [r for r in all_rows if not r.is_current]
        assert len(current) == 1 and current[0].revision == 2
        assert len(retired) == 1 and retired[0].revision == 1
        assert current[0].close_raw == 102
    finally:
        db.close()
