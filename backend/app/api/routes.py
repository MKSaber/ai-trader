"""FastAPI routers — thin; finance/ML logic stays in services."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.factory import get_market_data_provider, get_object_storage
from app.core.config import get_settings
from app.core.upload_security import (
    assert_allowed_extension,
    assert_size_ok,
    sanitize_filename,
    sha256_bytes,
)
from app.db import models as m
from app.db.session import get_db
from app.domain.enums import ModelStatus, SourceType, UploadStatus
from app.pipeline.orchestrator import run_daily_pipeline
from app.services.ingestion.persist import (
    complete_batch,
    persist_daily_bars,
    start_batch,
)
from app.services.research import (
    issue_predictions,
    resolve_predictions,
    train_and_register,
)
from app.ports.market_data import BarRow

router = APIRouter()


class StatusOut(BaseModel):
    """API health payload."""

    app: str = "LSE Pattern Lab"
    status: str = "ok"
    market_data_provider: str
    demo_mode: bool
    disclaimer: str


@router.get("/health", response_model=StatusOut)
def health() -> StatusOut:
    """Liveness and configuration summary."""
    s = get_settings()
    return StatusOut(
        market_data_provider=s.market_data_provider,
        demo_mode=s.demo_mode,
        disclaimer=(
            "Research system only. No broker execution. "
            "Insufficient evidence and no demonstrated edge are valid outputs."
        ),
    )


@router.get("/coverage")
def coverage(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Dataset coverage and missing-data warnings."""
    n_inst = db.scalar(select(func.count()).select_from(m.Instrument)) or 0
    n_daily = db.scalar(
        select(func.count()).select_from(m.MarketBarDaily).where(
            m.MarketBarDaily.is_current.is_(True)
        )
    ) or 0
    n_intra = db.scalar(
        select(func.count()).select_from(m.MarketBarIntraday).where(
            m.MarketBarIntraday.is_current.is_(True)
        )
    ) or 0
    warnings = []
    if n_daily == 0:
        warnings.append(
            "No daily OHLCV bars. Upload market data or run provider download. "
            "Predictions disabled until suitable price history exists."
        )
    if n_intra == 0:
        warnings.append(
            "No intraday bars. Intraday Lab predictions disabled. "
            "Daily reports alone cannot establish intraday price sequences."
        )
    return {
        "instruments": n_inst,
        "daily_bars": n_daily,
        "intraday_bars": n_intra,
        "warnings": warnings,
        "evidence_note": "Synthetic fixtures must be labelled synthetic.",
    }


@router.post("/uploads")
async def upload_file(
    file: UploadFile = File(...),
    source_type: str = Form(SourceType.MARKET_OHLCV),
    report_date: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Drag-drop friendly upload with hash dedupe and validation."""
    settings = get_settings()
    filename = sanitize_filename(file.filename or "upload.bin")
    try:
        assert_allowed_extension(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    data = await file.read()
    try:
        assert_size_ok(len(data), settings.max_upload_mb)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    digest = sha256_bytes(data)
    existing = db.scalar(select(m.Upload).where(m.Upload.sha256 == digest))
    if existing:
        return {
            "status": UploadStatus.DUPLICATE,
            "upload_id": existing.id,
            "message": "Duplicate content hash — import skipped",
        }

    store = get_object_storage()
    key = f"uploads/{digest[:16]}_{filename}"
    stored = store.put_bytes(key, data, content_type=file.content_type or "")

    # Scanned PDF heuristic: empty text extract
    status = UploadStatus.PENDING
    confidence = 1.0
    warnings: list[str] = []
    if filename.lower().endswith(".pdf"):
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if len(text.strip()) < 40:
                status = UploadStatus.NEEDS_OCR
                confidence = 0.0
                warnings.append(
                    "PDF appears scanned or empty — OCR required. "
                    "Extraction did not succeed."
                )
            else:
                status = UploadStatus.VALIDATED
                db.add(
                    m.NarrativeReport(
                        upload_id=0,  # fixed below
                        report_date=date.fromisoformat(report_date)
                        if report_date
                        else None,
                        text_extract=text[:50_000],
                        needs_ocr=False,
                        extraction_confidence=0.8,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"PDF parse issue: {exc}")
            status = UploadStatus.FAILED

    upload = m.Upload(
        filename=filename,
        stored_path=stored,
        sha256=digest,
        source_type=source_type,
        report_date=date.fromisoformat(report_date) if report_date else None,
        extraction_confidence=confidence,
        status=status if status != UploadStatus.PENDING else UploadStatus.VALIDATED,
        warnings=warnings,
        evidence_label="validated",
    )
    db.add(upload)
    db.flush()

    # Link narrative if created with upload_id 0 — fix
    narr = db.scalars(
        select(m.NarrativeReport).where(m.NarrativeReport.upload_id == 0)
    ).first()
    if narr:
        narr.upload_id = upload.id

    imported_rows = 0
    if source_type == SourceType.MARKET_OHLCV and filename.lower().endswith(
        (".csv", ".xlsx")
    ):
        try:
            imported_rows = _import_market_csv(db, data, filename, upload.id)
            upload.status = UploadStatus.IMPORTED
            upload.row_count = imported_rows
        except Exception as exc:  # noqa: BLE001
            upload.status = UploadStatus.FAILED
            warnings.append(str(exc))
            upload.warnings = warnings

    if source_type == SourceType.NARRATIVE and filename.lower().endswith(".txt"):
        text = data.decode("utf-8", errors="replace")
        db.add(
            m.NarrativeReport(
                upload_id=upload.id,
                report_date=upload.report_date,
                text_extract=text[:50_000],
                needs_ocr=False,
                extraction_confidence=1.0,
            )
        )
        upload.status = UploadStatus.IMPORTED

    db.commit()
    return {
        "upload_id": upload.id,
        "status": upload.status,
        "sha256": digest,
        "rows_imported": imported_rows,
        "warnings": warnings,
    }


def _import_market_csv(
    db: Session, data: bytes, filename: str, upload_id: int
) -> int:
    """Import OHLCV CSV with flexible headers."""
    text = data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    fields = {f.lower(): f for f in reader.fieldnames}

    def col(*names: str) -> str:
        for n in names:
            if n in fields:
                return fields[n]
        raise ValueError(f"Missing columns; need one of {names}. Got {list(fields)}")

    sym_c = col("symbol", "ticker", "yahoo_symbol")
    date_c = col("session_date", "date", "timestamp")
    o_c = col("open", "open_raw")
    h_c = col("high", "high_raw")
    l_c = col("low", "low_raw")
    c_c = col("close", "close_raw")
    v_c = fields.get("volume", None)

    batch = start_batch(db, provider_key="upload", upload_id=upload_id)
    bars: list[BarRow] = []
    for row in reader:
        raw_date = row[date_c]
        if "T" in raw_date:
            ts = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            session = ts.date()
        else:
            session = date.fromisoformat(raw_date[:10])
            ts = datetime(session.year, session.month, session.day, tzinfo=timezone.utc)
        sym = row[sym_c]
        if not sym.endswith(".L") and "." not in sym:
            sym = f"{sym}.L"
        currency = row.get("currency") or row.get("Currency") or "GBX"
        bars.append(
            BarRow(
                symbol=sym,
                bar_ts=ts,
                session_date=session,
                open=float(row[o_c]),
                high=float(row[h_c]),
                low=float(row[l_c]),
                close=float(row[c_c]),
                volume=float(row[v_c]) if v_c and row.get(v_c) else 0.0,
                currency_hint=currency,
            )
        )
    # Detect intraday vs daily by unique timestamps per day
    n = persist_daily_bars(db, bars, batch)
    complete_batch(db, batch)
    del filename
    return n


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Import history."""
    rows = db.scalars(select(m.Upload).order_by(m.Upload.id.desc()).limit(100)).all()
    return [
        {
            "id": u.id,
            "filename": u.filename,
            "source_type": u.source_type,
            "status": u.status,
            "sha256": u.sha256,
            "row_count": u.row_count,
            "warnings": u.warnings,
            "ingestion_time": u.ingestion_time.isoformat() if u.ingestion_time else None,
        }
        for u in rows
    ]


@router.post("/research/train")
def train(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Train baselines and challengers."""
    return train_and_register(db)


@router.post("/research/predict")
def predict(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Issue immutable predictions from champion."""
    return issue_predictions(db)


@router.post("/research/resolve")
def resolve(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Resolve matured predictions."""
    return resolve_predictions(db)


@router.get("/predictions")
def predictions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Daily forecast table data."""
    rows = db.scalars(
        select(m.Prediction).order_by(m.Prediction.id.desc()).limit(500)
    ).all()
    out = []
    for p in rows:
        model = db.get(m.ModelRecord, p.model_id)
        inst = db.get(m.Instrument, p.instrument_id)
        out.append(
            {
                "id": p.id,
                "symbol": inst.yahoo_symbol if inst else p.instrument_id,
                "issued_at": p.issued_at.isoformat(),
                "session_date": p.session_date.isoformat(),
                "horizon": p.horizon,
                "expected_return": p.expected_return,
                "probability_up": p.probability_up,
                "uncertainty": p.uncertainty,
                "model_version": model.version if model else None,
                "realised_return": p.realised_return,
                "outcome_correct": p.outcome_correct,
            }
        )
    return out


@router.get("/models")
def models(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Model registry."""
    rows = db.scalars(select(m.ModelRecord).order_by(m.ModelRecord.id.desc())).all()
    return [
        {
            "id": r.id,
            "version": r.version,
            "model_type": r.model_type,
            "status": r.status,
            "horizon": r.horizon,
            "formula": r.formula,
            "feature_importance": r.feature_importance,
            "metrics": r.metrics,
            "train_start": r.train_start.isoformat() if r.train_start else None,
            "train_end": r.train_end.isoformat() if r.train_end else None,
        }
        for r in rows
    ]


class PromoteBody(BaseModel):
    """Manual champion promotion."""

    model_id: int
    approve: bool = True


@router.post("/models/promote")
def promote(body: PromoteBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manually approve champion promotion."""
    model = db.get(m.ModelRecord, body.model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if not body.approve:
        model.status = ModelStatus.REJECTED
        db.commit()
        return {"status": "rejected", "version": model.version}
    # Retire old champions
    for old in db.scalars(
        select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
    ):
        old.status = ModelStatus.RETIRED
    model.status = ModelStatus.CHAMPION
    model.promoted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "champion", "version": model.version}


@router.get("/findings")
def findings(q: str | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Indexed research findings with optional search."""
    stmt = select(m.ResearchFinding).order_by(m.ResearchFinding.id.desc()).limit(200)
    rows = db.scalars(stmt).all()
    out = []
    for f in rows:
        if q and q.lower() not in (f.claim or "").lower() and q.lower() not in (f.search_vector or "").lower():
            continue
        out.append(
            {
                "id": f.id,
                "claim": f.claim,
                "status": f.status,
                "horizon": f.horizon,
                "discovery_date": f.discovery_date.isoformat(),
                "data_cutoff": f.data_cutoff.isoformat(),
                "sample_size": f.sample_size,
                "effect_size": f.effect_size,
                "topic": f.topic,
                "note": "A stored finding is not established truth.",
            }
        )
    return out


@router.get("/intraday/setups")
def intraday_setups(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Pending/active setups for Intraday Lab."""
    n_intra = db.scalar(
        select(func.count()).select_from(m.MarketBarIntraday)
    ) or 0
    if n_intra == 0:
        return {
            "disabled": True,
            "reason": (
                "Intraday predictions disabled: no timestamped intraday OHLCV bars. "
                "Daily reports cannot establish the sequence of intraday prices. "
                "Upload 5-minute bars or run yfinance download."
            ),
            "setups": [],
        }
    rows = db.scalars(
        select(m.IntradaySetup).order_by(m.IntradaySetup.id.desc()).limit(200)
    ).all()
    return {
        "disabled": False,
        "setups": [
            {
                "id": s.id,
                "instrument_id": s.instrument_id,
                "signal_ts": s.signal_ts.isoformat(),
                "model_version": s.model_version,
                "entry_low": s.entry_low,
                "entry_high": s.entry_high,
                "stop_loss": s.stop_loss,
                "take_profit": s.take_profit,
                "entry_expiry": s.entry_expiry.isoformat() if s.entry_expiry else None,
                "expected_net_return": s.expected_net_return,
                "uncertainty": s.uncertainty,
                "estimated_costs": s.estimated_costs,
                "reason": s.reason,
                "no_trade": s.no_trade,
                "outcome": s.outcome,
                "exit_reason": s.exit_reason,
                "ambiguity_flag": s.ambiguity_flag,
            }
            for s in rows
        ],
    }


@router.get("/intraday/ledger")
def ledger(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Paper-trading ledger snapshots."""
    rows = db.scalars(
        select(m.PaperLedger).order_by(m.PaperLedger.id.desc()).limit(50)
    ).all()
    return [
        {
            "as_of": r.as_of.isoformat(),
            "cash_gbp": r.cash_gbp,
            "exposure_gbp": r.exposure_gbp,
            "equity_gbp": r.equity_gbp,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.get("/pipeline/runs")
def pipeline_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Recent pipeline runs."""
    rows = db.scalars(
        select(m.PipelineRun).order_by(m.PipelineRun.id.desc()).limit(50)
    ).all()
    return [
        {
            "id": r.id,
            "run_key": r.run_key,
            "session_date": r.session_date.isoformat() if r.session_date else None,
            "status": r.status,
            "dry_run": r.dry_run,
            "offline": r.offline,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "error_summary": r.error_summary,
            "manifest": r.manifest,
        }
        for r in rows
    ]


class PipelineBody(BaseModel):
    """Manual pipeline trigger from API."""

    session_date: date | None = None
    offline: bool = False
    dry_run: bool = False
    symbols: list[str] = Field(default_factory=lambda: ["VOD.L", "BP.L"])


@router.post("/pipeline/run")
def pipeline_run(body: PipelineBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run daily pipeline (also available via CLI / GitHub Actions)."""
    return run_daily_pipeline(
        db,
        session_date=body.session_date,
        dry_run=body.dry_run,
        offline=body.offline,
        symbols=body.symbols,
    )


@router.post("/provider/fetch")
def provider_fetch(
    offline: bool = False,
    symbols: str = "VOD.L,BP.L,HSBA.L",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Fetch recent daily (+ best-effort intraday) from configured provider."""
    from datetime import timedelta

    from app.services.ingestion.persist import persist_intraday_bars

    provider = get_market_data_provider(force_offline=offline)
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    end = date.today()
    start = end - timedelta(days=40)
    daily = provider.fetch_daily(syms, start, end)
    if not daily and provider.name == "yfinance" and not offline:
        raise HTTPException(
            502,
            "yfinance returned no data. Not substituting synthetic. "
            "Retry later or use offline=true for fixtures.",
        )
    batch = start_batch(db, provider_key=provider.name, session_date=end)
    n_d = persist_daily_bars(db, daily, batch)
    # Intraday last 5 days
    start_dt = datetime.now(timezone.utc) - timedelta(days=5)
    end_dt = datetime.now(timezone.utc)
    intra = provider.fetch_intraday(syms, start_dt, end_dt, interval_minutes=5)
    n_i = persist_intraday_bars(db, intra, batch, interval_minutes=5)
    complete_batch(db, batch)
    db.commit()
    return {
        "provider": provider.name,
        "daily_stored": n_d,
        "intraday_stored": n_i,
        "note": (
            "Downloaded market bars are not paper executions. "
            "yfinance intraday lookback is typically ~60 days."
        ),
    }


@router.get("/settings")
def settings_view() -> dict[str, Any]:
    """Visible research settings and cost assumptions."""
    s = get_settings()
    return {
        "default_horizon": s.default_horizon,
        "intraday_interval_minutes": s.intraday_interval_minutes,
        "commission_bps": s.commission_bps,
        "spread_bps": s.spread_bps,
        "slippage_bps": s.slippage_bps,
        "stamp_duty_rate": s.stamp_duty_rate,
        "market_data_provider": s.market_data_provider,
        "demo_mode": s.demo_mode,
        "benchmark": "benchmark comparison unavailable until a matching GBP total-return series is uploaded",
    }


@router.get("/instruments")
def instruments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Stock explorer list."""
    rows = db.scalars(select(m.Instrument).order_by(m.Instrument.symbol)).all()
    return [
        {
            "id": i.id,
            "symbol": i.symbol,
            "yahoo_symbol": i.yahoo_symbol,
            "currency_quoted": i.currency_quoted,
            "sector": i.sector,
        }
        for i in rows
    ]


@router.get("/instruments/{instrument_id}/bars")
def instrument_bars(
    instrument_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Daily bars for charts."""
    rows = db.scalars(
        select(m.MarketBarDaily)
        .where(
            m.MarketBarDaily.instrument_id == instrument_id,
            m.MarketBarDaily.is_current.is_(True),
        )
        .order_by(m.MarketBarDaily.session_date)
    ).all()
    return {
        "daily": [
            {
                "date": r.session_date.isoformat(),
                "open": r.open_gbp,
                "high": r.high_gbp,
                "low": r.low_gbp,
                "close": r.close_gbp,
                "volume": r.volume,
            }
            for r in rows
        ]
    }
