"""Candle-lab settings — isolated from LSE Pattern Lab."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# Named broker / tax profiles. Sources: candle-lab/COST_SOURCES.md
BROKER_PROFILES: dict[str, dict[str, Any]] = {
    # Older lab defaults (overstates commission vs T212/eToro Invest).
    "legacy_stress": {
        "label": "Legacy lab stack (5/10/5 bps + 0.5% SDRT, no PTM)",
        "commission_bps": 5.0,
        "spread_bps": 10.0,
        "slippage_bps": 5.0,
        "stamp_duty_rate": 0.005,
        "fx_bps": 0.0,
        "flat_commission_gbp": 0.0,
        "ptm_levy_gbp": 0.0,
        "ptm_threshold_gbp": 10_000.0,
    },
    # Trading 212 Invest / Stocks ISA / SIPP, GBP account, LSE GBP shares.
    "trading212": {
        "label": "Trading 212 Invest (GBP→LSE): £0 commission, 0.5% SDRT, PTM £1.50>$10k",
        "commission_bps": 0.0,
        "spread_bps": 5.0,  # market bid/ask assumption, not a T212 line item
        "slippage_bps": 2.0,
        "stamp_duty_rate": 0.005,
        "fx_bps": 0.0,  # no FX when account + instrument are GBP
        "flat_commission_gbp": 0.0,
        "ptm_levy_gbp": 1.50,
        "ptm_threshold_gbp": 10_000.0,
    },
    # eToro UK-resident GBP account, LSE cash equities (not CFD / Stock Margin).
    "etoro_uk_lse": {
        "label": "eToro UK LSE cash (assume £0 commission): 0.5% SDRT, PTM £1.50>$10k",
        "commission_bps": 0.0,
        "spread_bps": 5.0,  # market bid/ask; eToro states no markup
        "slippage_bps": 2.0,
        "stamp_duty_rate": 0.005,
        "fx_bps": 0.0,
        "flat_commission_gbp": 0.0,
        "ptm_levy_gbp": 1.50,
        "ptm_threshold_gbp": 10_000.0,
    },
    # eToro with explicit flat $2≈£1.55 each way (conservative if table applies).
    "etoro_flat_usd": {
        "label": "eToro flat ~$2/side + 0.5% SDRT + PTM (if exchange table applies)",
        "commission_bps": 0.0,
        "spread_bps": 5.0,
        "slippage_bps": 2.0,
        "stamp_duty_rate": 0.005,
        "fx_bps": 0.0,
        "flat_commission_gbp": 1.55,
        "ptm_levy_gbp": 1.50,
        "ptm_threshold_gbp": 10_000.0,
    },
}


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
    trade_rules_version: str = "trade-rules-v2.4"
    # Default paper costs track Trading 212 Invest (see COST_SOURCES.md).
    cost_profile: str = "trading212"

    # Trade rules (frozen per experiment)
    entry_buffer_frac: float = 0.0005
    stop_buffer_frac: float = 0.0005
    reward_risk: float = 2.0
    setup_expiry_bars: int = 3
    risk_frac: float = 0.005
    max_position_frac: float = 0.1
    starting_cash_gbp: float = 100_000.0

    commission_bps: float = 0.0
    spread_bps: float = 5.0
    slippage_bps: float = 2.0
    stamp_duty_rate: float = 0.005  # GOV.UK principal SDRT 0.5%
    fx_bps: float = 0.0
    flat_commission_gbp: float = 0.0
    ptm_levy_gbp: float = 1.50  # Takeover Panel from 2 Dec 2024
    ptm_threshold_gbp: float = 10_000.0

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


def apply_broker_profile(settings: Settings, profile: str) -> Settings:
    """Return a copy of settings with a named broker/tax cost profile applied."""
    if profile not in BROKER_PROFILES:
        raise ValueError(
            f"Unknown cost profile {profile!r}; choose from {sorted(BROKER_PROFILES)}"
        )
    data = settings.model_dump()
    data.update(deepcopy(BROKER_PROFILES[profile]))
    data["cost_profile"] = profile
    # Drop non-Settings keys from profile metadata
    data.pop("label", None)
    return Settings(**data)


@lru_cache
def get_settings() -> Settings:
    return Settings()

