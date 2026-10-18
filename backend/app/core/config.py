"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for LSE Pattern Lab."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://lse:lse_dev_password@localhost:5432/"
        "lse_pattern_lab"
    )
    redis_url: str = "redis://localhost:6379/0"

    object_storage_backend: str = "local"
    local_storage_root: str = "./storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "auto"

    market_data_provider: str = "yfinance"
    demo_mode: bool = False

    default_horizon: str = "next_session_open_to_close"
    intraday_interval_minutes: int = 5
    commission_bps: float = 5.0
    spread_bps: float = 10.0
    slippage_bps: float = 5.0
    stamp_duty_rate: float = 0.01
    initial_paper_cash_gbp: float = 100_000.0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    max_upload_mb: int = 25

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
