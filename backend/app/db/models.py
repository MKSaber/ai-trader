"""SQLAlchemy ORM models for LSE Pattern Lab."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Instrument(Base):
    """Listed instrument with identifier history."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    yahoo_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(256))
    currency_quoted: Mapped[str] = mapped_column(String(8), default="GBX")
    price_scale_to_gbp: Mapped[float] = mapped_column(Float, default=0.01)
    sector: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Upload(Base):
    """Preserved source upload with hash and provenance."""

    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("sha256", name="uq_uploads_sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    report_date: Mapped[date | None] = mapped_column(Date)
    ingestion_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    row_count: Mapped[int | None] = mapped_column(Integer)
    warnings: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_label: Mapped[str] = mapped_column(String(32), default="validated")


class DataSource(Base):
    """Configured market-data source."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)


class IngestionBatch(Base):
    """One download or import batch with revision lineage."""

    __tablename__ = "ingestion_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id")
    )
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    batch_key: Mapped[str] = mapped_column(String(128), unique=True)
    session_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    revises_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_batches.id")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class IngestionWatermark(Base):
    """Persistent high-water mark per instrument/interval."""

    __tablename__ = "ingestion_watermarks"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "bar_kind",
            "interval_minutes",
            name="uq_watermark",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    bar_kind: Mapped[str] = mapped_column(String(16))  # daily | intraday
    interval_minutes: Mapped[int] = mapped_column(Integer, default=0)
    last_bar_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketBarDaily(Base):
    """Daily OHLCV with raw and normalised values."""

    __tablename__ = "market_bars_daily"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "session_date",
            "revision",
            name="uq_daily_bar_rev",
        ),
        Index("ix_daily_inst_date", "instrument_id", "session_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    session_date: Mapped[date] = mapped_column(Date)
    open_raw: Mapped[float] = mapped_column(Float)
    high_raw: Mapped[float] = mapped_column(Float)
    low_raw: Mapped[float] = mapped_column(Float)
    close_raw: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    open_gbp: Mapped[float] = mapped_column(Float)
    high_gbp: Mapped[float] = mapped_column(Float)
    low_gbp: Mapped[float] = mapped_column(Float)
    close_gbp: Mapped[float] = mapped_column(Float)
    source_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_batches.id")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketBarIntraday(Base):
    """Intraday OHLCV bars (e.g. 5-minute)."""

    __tablename__ = "market_bars_intraday"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "bar_ts",
            "interval_minutes",
            "revision",
            name="uq_intraday_bar_rev",
        ),
        Index("ix_intraday_inst_ts", "instrument_id", "bar_ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    bar_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_date: Mapped[date] = mapped_column(Date, index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=5)
    open_raw: Mapped[float] = mapped_column(Float)
    high_raw: Mapped[float] = mapped_column(Float)
    low_raw: Mapped[float] = mapped_column(Float)
    close_raw: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    open_gbp: Mapped[float] = mapped_column(Float)
    high_gbp: Mapped[float] = mapped_column(Float)
    low_gbp: Mapped[float] = mapped_column(Float)
    close_gbp: Mapped[float] = mapped_column(Float)
    source_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_batches.id")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class CorporateAction(Base):
    """Corporate action with revision support."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    action_date: Mapped[date] = mapped_column(Date)
    action_type: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ExecutedTrade(Base):
    """User/account executed trade — not market opportunity set."""

    __tablename__ = "trades_executed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id")
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price_raw: Mapped[float] = mapped_column(Float)
    price_gbp: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class NarrativeReport(Base):
    """Narrative commentary extract."""

    __tablename__ = "narrative_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"))
    report_date: Mapped[date | None] = mapped_column(Date)
    text_extract: Mapped[str] = mapped_column(Text)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    structured_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class FeatureDefinition(Base):
    """Feature registry entry."""

    __tablename__ = "feature_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    definition: Mapped[str] = mapped_column(Text)
    lookback: Mapped[int] = mapped_column(Integer)
    required_inputs: Mapped[list[Any] | None] = mapped_column(JSON)
    availability_rule: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32), default="v1")


class DatasetVersion(Base):
    """Versioned dataset snapshot metadata."""

    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    instrument_count: Mapped[int] = mapped_column(Integer)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Experiment(Base):
    """Record of every training / tuning attempt."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)


class ModelRecord(Base):
    """Trained model artifact registry."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    model_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    artifact_path: Mapped[str | None] = mapped_column(String(1024))
    formula: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    train_start: Mapped[date | None] = mapped_column(Date)
    train_end: Mapped[date | None] = mapped_column(Date)
    horizon: Mapped[str] = mapped_column(String(64))
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prediction(Base):
    """Immutable issued forecast; outcomes appended later only."""

    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_pred_inst_issued", "instrument_id", "issued_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_date: Mapped[date] = mapped_column(Date)
    horizon: Mapped[str] = mapped_column(String(64))
    expected_return: Mapped[float | None] = mapped_column(Float)
    probability_up: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    features_used: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    features_excluded: Mapped[list[Any] | None] = mapped_column(JSON)
    # Outcome fields — appended after horizon elapses; never rewrite forecast
    realised_return: Mapped[float | None] = mapped_column(Float)
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromotionReport(Base):
    """Champion vs challenger comparison."""

    __tablename__ = "promotion_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    champion_model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    challenger_model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    comparison: Mapped[dict[str, Any]] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IntradaySetup(Base):
    """Frozen intraday trade setup — never retrospectively rewritten."""

    __tablename__ = "intraday_setups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    signal_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8), default="long")
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    entry_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    max_hold_minutes: Mapped[int] = mapped_column(Integer, default=120)
    expected_net_return: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    estimated_costs: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    no_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str | None] = mapped_column(String(32))
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    ambiguity_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaperOrder(Base):
    """Simulated order from a frozen setup."""

    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint("setup_id", "order_kind", name="uq_paper_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    setup_id: Mapped[int] = mapped_column(ForeignKey("intraday_setups.id"))
    order_kind: Mapped[str] = mapped_column(String(32))
    limit_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaperFill(Base):
    """Simulated fill — touch does not guarantee fill."""

    __tablename__ = "paper_fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"))
    fill_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    costs: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class PaperPosition(Base):
    """Open or closed paper position."""

    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    setup_id: Mapped[int] = mapped_column(ForeignKey("intraday_setups.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gross_pnl: Mapped[float | None] = mapped_column(Float)
    costs: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    ambiguity_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class PaperLedger(Base):
    """Portfolio cash / exposure snapshot."""

    __tablename__ = "paper_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cash_gbp: Mapped[float] = mapped_column(Float)
    exposure_gbp: Mapped[float] = mapped_column(Float, default=0)
    equity_gbp: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


class PipelineRun(Base):
    """Daily research pipeline run record."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(128), unique=True)
    session_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="running")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(Text)

    stages: Mapped[list[PipelineStageStatus]] = relationship(back_populates="run")


class PipelineStageStatus(Base):
    """Per-stage status for resumability."""

    __tablename__ = "pipeline_stage_statuses"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_name", name="uq_run_stage"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"))
    stage_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[PipelineRun] = relationship(back_populates="stages")


class ResearchFinding(Base):
    """Indexed research claim with evidence — not established truth."""

    __tablename__ = "research_findings"
    __table_args__ = (
        Index("ix_findings_status", "status"),
        Index("ix_findings_fts", "claim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim: Mapped[str] = mapped_column(Text)
    universe: Mapped[str | None] = mapped_column(String(256))
    horizon: Mapped[str | None] = mapped_column(String(64))
    conditions: Mapped[str | None] = mapped_column(Text)
    discovery_date: Mapped[date] = mapped_column(Date)
    data_cutoff: Mapped[date] = mapped_column(Date)
    feature_version: Mapped[str | None] = mapped_column(String(64))
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id")
    )
    model_version: Mapped[str | None] = mapped_column(String(64))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    evaluation_window: Mapped[str | None] = mapped_column(String(128))
    effect_size: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    costs_applied: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    experiment_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="exploratory")
    last_review_date: Mapped[date | None] = mapped_column(Date)
    superseding_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_findings.id")
    )
    topic: Mapped[str | None] = mapped_column(String(128), index=True)
    search_vector: Mapped[str | None] = mapped_column(Text)


class FindingNote(Base):
    """Human notes — separate from machine conclusions."""

    __tablename__ = "finding_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("research_findings.id"))
    author: Mapped[str] = mapped_column(String(128), default="operator")
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BackgroundJob(Base):
    """Persistent background job status."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Resolve forward refs for relationship typing
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    pass
