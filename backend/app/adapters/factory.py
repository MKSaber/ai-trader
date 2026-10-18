"""Adapter factories — select implementations from settings."""

from __future__ import annotations

from pathlib import Path

from app.adapters.calendar.lse_calendar import LseSessionCalendar
from app.adapters.market_data.fixture import FixtureMarketDataProvider
from app.adapters.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.adapters.storage.local_fs import LocalFilesystemStorage
from app.adapters.storage.s3 import S3CompatibleStorage
from app.core.config import Settings, get_settings
from app.ports.market_data import MarketDataProvider
from app.ports.storage import ObjectStorage


def get_market_data_provider(
    settings: Settings | None = None,
    *,
    force_offline: bool = False,
) -> MarketDataProvider:
    """Return configured market-data provider.

    Fixture is used only when demo/offline is explicit.
    """
    cfg = settings or get_settings()
    if force_offline or cfg.demo_mode or cfg.market_data_provider == "fixture":
        return FixtureMarketDataProvider()
    if cfg.market_data_provider == "yfinance":
        return YFinanceMarketDataProvider()
    raise ValueError(
        f"Unknown MARKET_DATA_PROVIDER={cfg.market_data_provider!r}. "
        "Supported: yfinance, fixture"
    )


def get_object_storage(settings: Settings | None = None) -> ObjectStorage:
    """Return configured object storage backend."""
    cfg = settings or get_settings()
    if cfg.object_storage_backend == "local":
        root = Path(cfg.local_storage_root)
        return LocalFilesystemStorage(str(root))
    if cfg.object_storage_backend == "s3":
        return S3CompatibleStorage(
            bucket=cfg.s3_bucket or "",
            endpoint_url=cfg.s3_endpoint_url,
            access_key=cfg.s3_access_key_id,
            secret_key=cfg.s3_secret_access_key,
            region=cfg.s3_region,
        )
    raise ValueError(
        f"Unknown OBJECT_STORAGE_BACKEND={cfg.object_storage_backend!r}"
    )


def get_calendar() -> LseSessionCalendar:
    """Return LSE session calendar."""
    return LseSessionCalendar()
