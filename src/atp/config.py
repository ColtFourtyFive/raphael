"""Process settings, read from the environment (and `.env` locally)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Mode safety
    allow_live_trading: bool = False

    # Alpaca
    alpaca_api_key_id: SecretStr = SecretStr("")
    alpaca_api_secret_key: SecretStr = SecretStr("")
    alpaca_paper: bool = True
    alpaca_data_feed: str = "iex"

    # AI gateway
    litellm_base_url: str = "http://localhost:4000"
    litellm_master_key: SecretStr = SecretStr("")
    ai_model: str = "claude-haiku-5-5"
    # Route every agent's AI filter to this gateway model instead (tests, keyless runs).
    ai_model_override: str = ""
    ai_timeout_s: float = 20.0
    # Fallback price when the gateway doesn't report cost (USD per million tokens).
    ai_input_usd_per_mtok: Decimal = Decimal("1.00")
    ai_output_usd_per_mtok: Decimal = Decimal("5.00")

    # Infrastructure
    database_url: str = "postgresql+psycopg://atp:atp@localhost:5432/atp"
    nats_url: str = "nats://localhost:4222"
    nats_replicas: int = 1

    # Control panel
    admin_token: SecretStr = SecretStr("")

    # Credentials encryption
    local_encryption_key: SecretStr = SecretStr("")
    aws_kms_key_arn: str = ""

    # Loop tuning
    worker_max_deliver: int = 5
    worker_ack_wait_s: float = 30.0
    reconcile_interval_s: float = 30.0
    paper_slippage_bps: Decimal = Decimal("5")
    paper_fee_per_order: Decimal = Decimal("0")
    paper_starting_cash: Decimal = Decimal("10000")
    indicator_lookback_bars: int = Field(default=250, ge=50)

    # Alerts / observability
    alert_webhook_url: str = ""
    sentry_dsn: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
