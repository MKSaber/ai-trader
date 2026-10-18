"""FastAPI routers — thin; finance/ML logic stays in services."""

from __future__ import annotations

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
from app.services.eval.backtest import (
    pattern_hypotheses,
    prediction_portfolio_summary,
)
from app.services.eval.drift import compute_drift_report
from app.services.findings.service import search_findings
from app.services.ingestion.parsers import parse_market_rows, preview_columns
from app.services.ingestion.persist import (
    complete_batch,
    persist_daily_bars,
    start_batch,
)
from app.services.research import (
    issue_predictions,
    resolve_predictions,
    run_holdout_eval,
    run_rolling_eval,
    train_and_register,
)
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
        (".csv", ".xlsx", ".xls")
    ):
        try:
            imported_rows = _import_market_file(db, data, filename, upload.id)
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


def _import_market_file(
    db: Session,
    data: bytes,
    filename: str,
    upload_id: int,
    *,
    allow_revision: bool = False,
    column_mapping: dict[str, str] | None = None,
) -> int:
    """Import OHLCV CSV/XLSX with flexible headers and optional revisions."""
    bars = parse_market_rows(data, filename, column_mapping=column_mapping)
    batch = start_batch(db, provider_key="upload", upload_id=upload_id)
    n = persist_daily_bars(db, bars, batch, allow_revision=allow_revision)
    complete_batch(db, batch)
    return n


@router.post("/uploads/preview")
async def preview_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Column-mapping preview before import."""
    filename = sanitize_filename(file.filename or "upload.bin")
    assert_allowed_extension(filename)
    data = await file.read()
    settings = get_settings()
    assert_size_ok(len(data), settings.max_upload_mb)
    if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "Preview supports CSV/XLSX only")
    return preview_columns(data, filename)


@router.post("/uploads/batch")
async def batch_upload(
    files: list[UploadFile] = File(...),
    source_type: str = Form(SourceType.MARKET_OHLCV),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Batch import multiple files."""
    results = []
    for file in files:
        # Reuse single-upload logic via nested call pattern
        single = await upload_file(
            file=file, source_type=source_type, report_date=None, db=db
        )
        results.append(single)
    return {"count": len(results), "results": results}


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
    try:
        return train_and_register(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Training failed: {exc}",
        ) from exc


def _yahoo_fetch_into_db(
    db: Session,
    *,
    symbols: list[str],
    lookback_days: int,
    offline: bool = False,
) -> dict[str, Any]:
    """Shared Yahoo/fixture fetch used by provider + research endpoints."""
    from datetime import timedelta

    from app.services.ingestion.persist import persist_intraday_bars

    provider = get_market_data_provider(force_offline=offline)
    end = date.today()
    # Cap at ~10y calendar; default path uses 5y (1825d)
    lookback = max(5, min(int(lookback_days), 3650))
    start = end - timedelta(days=lookback)
    daily = provider.fetch_daily(symbols, start, end)
    if not daily and provider.name == "yfinance" and not offline:
        raise HTTPException(
            502,
            "yfinance returned no data. Not substituting synthetic. "
            "Retry later or use offline=true for fixtures.",
        )
    batch = start_batch(db, provider_key=provider.name, session_date=end)
    n_d = persist_daily_bars(db, daily, batch)
    start_dt = datetime.now(timezone.utc) - timedelta(days=5)
    end_dt = datetime.now(timezone.utc)
    intra = provider.fetch_intraday(
        symbols, start_dt, end_dt, interval_minutes=5
    )
    n_i = persist_intraday_bars(db, intra, batch, interval_minutes=5)
    complete_batch(db, batch)
    db.commit()
    return {
        "provider": provider.name,
        "symbols": symbols,
        "lookback_days": lookback,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "daily_stored": n_d,
        "intraday_stored": n_i,
        "daily_fetched": len(daily),
        "note": (
            "Daily history can span years; yfinance intraday is still "
            "~60 days max."
        ),
    }


@router.post("/research/holdout")
def holdout(
    train_sessions: int = 85,
    test_sessions: int = 5,
    fetch: bool = True,
    lookback_days: int = 1825,
    symbols: str = "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Single holdout: train prior N sessions, test last M."""
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    fetch_info = None
    if fetch:
        fetch_info = _yahoo_fetch_into_db(
            db, symbols=syms, lookback_days=lookback_days
        )
    try:
        result = run_holdout_eval(
            db,
            train_sessions=max(20, train_sessions),
            test_sessions=max(1, test_sessions),
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Holdout eval failed: {exc}",
        ) from exc
    if result.get("status") == "insufficient_data":
        raise HTTPException(400, detail=result)
    result["fetch"] = fetch_info
    return result


@router.post("/research/rolling")
def rolling(
    train_sessions: int = 85,
    test_sessions: int = 5,
    step_sessions: int = 5,
    max_folds: int | None = None,
    min_prob: float = 0.55,
    fetch: bool = True,
    lookback_days: int = 1825,
    symbols: str = "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rolling walk-forward: 85 train / 5 test, slide across history.

    Also scores ATR stop/take-profit paper trades and returns recommendations.
    """
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    fetch_info = None
    if fetch:
        fetch_info = _yahoo_fetch_into_db(
            db, symbols=syms, lookback_days=lookback_days
        )
    try:
        result = run_rolling_eval(
            db,
            train_sessions=max(20, train_sessions),
            test_sessions=max(1, test_sessions),
            step_sessions=max(1, step_sessions),
            max_folds=max_folds,
            min_prob=min_prob,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Rolling walk-forward failed: {exc}",
        ) from exc
    if result.get("status") == "insufficient_data":
        raise HTTPException(400, detail=result)
    result["fetch"] = fetch_info
    return result


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
    return search_findings(db, q=q)


class RollbackBody(BaseModel):
    """Roll champion back to a previously retired/candidate model."""

    model_id: int


@router.post("/models/rollback")
def rollback_model(body: RollbackBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Restore a prior model as champion; retire current champion."""
    target = db.get(m.ModelRecord, body.model_id)
    if not target:
        raise HTTPException(404, "Model not found")
    for old in db.scalars(
        select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
    ):
        old.status = ModelStatus.RETIRED
    target.status = ModelStatus.CHAMPION
    target.promoted_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": "champion",
        "version": target.version,
        "note": "Rollback recorded. Historical predictions remain immutable.",
    }


@router.get("/drift")
def drift(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Feature / forecast drift monitoring."""
    return compute_drift_report(db)


@router.get("/patterns")
def patterns(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Pattern explorer: hypotheses with sample sizes and labels."""
    return {
        "patterns": pattern_hypotheses(db),
        "note": "Separate exploratory patterns from validated findings visually.",
    }


@router.get("/backtests")
def backtests(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Cost-aware prediction portfolio summary."""
    return prediction_portfolio_summary(db)


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
    symbols: str = "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
    lookback_days: int = 1825,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Fetch daily history (default ~5 years) + best-effort recent intraday."""
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    return _yahoo_fetch_into_db(
        db,
        symbols=syms,
        lookback_days=lookback_days,
        offline=offline,
    )


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
