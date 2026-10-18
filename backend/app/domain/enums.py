"""Shared enumerations for research and paper-trading state."""

from enum import StrEnum


class SourceType(StrEnum):
    """Incoming report / data source classification."""

    MARKET_OHLCV = "market_ohlcv"
    EXECUTED_TRADES = "executed_trades"
    NARRATIVE = "narrative"
    PROVIDER_DOWNLOAD = "provider_download"


class UploadStatus(StrEnum):
    """Ingestion lifecycle for an uploaded file."""

    PENDING = "pending"
    VALIDATED = "validated"
    IMPORTED = "imported"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class ModelStatus(StrEnum):
    """Model registry status."""

    CANDIDATE = "candidate"
    CHAMPION = "champion"
    RETIRED = "retired"
    REJECTED = "rejected"


class FindingStatus(StrEnum):
    """Research finding lifecycle — not established truth."""

    EXPLORATORY = "exploratory"
    VALIDATED = "validated"
    CONTRADICTED = "contradicted"
    RETIRED = "retired"


class PipelineRunStatus(StrEnum):
    """Daily pipeline run status."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class StageStatus(StrEnum):
    """Individual pipeline stage status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TradeOutcome(StrEnum):
    """Paper-trade outcome labels."""

    NOT_TRIGGERED = "not_triggered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    OPEN = "open"
    CLOSED_POSITIVE = "closed_positive"
    CLOSED_NEGATIVE = "closed_negative"
    BREAKEVEN = "breakeven"
    AMBIGUOUS = "ambiguous"


class ExitReason(StrEnum):
    """Why a paper position closed."""

    TARGET = "target"
    STOP = "stop"
    TIME_LIMIT = "time_limit"
    END_OF_SESSION = "end_of_session"
    OTHER = "other"
    NOT_APPLICABLE = "not_applicable"


class EvidenceLabel(StrEnum):
    """UI / report evidence classification."""

    EXPLORATORY = "exploratory"
    VALIDATED = "validated"
    SYNTHETIC = "synthetic"
