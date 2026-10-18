"""Candle-lab settings — isolated from LSE Pattern Lab."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config for Live Candle Pattern Test only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="CANDLE_",
    )

    database_url: str = (
        "postgresql+psycopg://candle:candle_dev@localhost:5433/candle_lab"
    )
    # Fallback SQLite for local tests without Postgres
    database_url_sqlite: str = "sqlite:///./candle_lab.db"
    # Default SQLite so this app never touches the Pattern Lab Postgres.
    use_sqlite: bool = True

    symbols: str = "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L"
    timezone: str = "Europe/London"
    interval_minutes: int = 5
    poll_seconds: int = 30
    warmup_bars: int = 80

    detector_version: str = "patterns-v1"
    trade_rules_version: str = "trade-rules-v1"

    # Trade rules (frozen per experiment)
    entry_buffer_frac: float = 0.0005
    stop_buffer_frac: float = 0.0005
    reward_risk: float = 2.0
    setup_expiry_bars: int = 3
    risk_frac: float = 0.005
    max_position_frac: float = 0.1
    starting_cash_gbp: float = 100_000.0

    commission_bps: float = 5.0
    spread_bps: float = 10.0
    slippage_bps: float = 5.0
    stamp_duty_rate: float = 0.005  # SDRT principal 0.5%

    # Feed
    feed_label: str = "yfinance_delayed"
    feed_is_realtime: bool = False
    stale_after_seconds: int = 600

    api_host: str = "0.0.0.0"
    api_port: int = 8100
    cors_origins: str = "http://localhost:3100,http://localhost:5173,http://localhost:3000"

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
