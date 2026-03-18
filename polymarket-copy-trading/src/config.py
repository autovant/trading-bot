"""Configuration loading and validation for the copy trading bot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


class PolymarketConfig(BaseModel):
    """Polymarket API connection settings."""

    clob_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137
    private_key: str = ""


class CopyConfig(BaseModel):
    """Copy trading behaviour settings."""

    sizing_mode: str = Field(default="proportional", pattern="^(proportional|fixed)$")
    size_multiplier: float = Field(default=1.0, gt=0)
    fixed_size_usdc: float = Field(default=10.0, gt=0)
    copy_sells: bool = True
    min_trade_size_usdc: float = Field(default=1.0, ge=0)
    max_trade_age_seconds: int = Field(default=300, gt=0)


class RiskConfig(BaseModel):
    """Risk management parameters."""

    max_position_size_usdc: float = Field(default=100.0, gt=0)
    max_portfolio_exposure_usdc: float = Field(default=500.0, gt=0)
    max_open_positions: int = Field(default=20, gt=0)
    slippage_tolerance_pct: float = Field(default=2.0, ge=0)
    max_price: float = Field(default=0.95, gt=0, le=1.0)
    min_price: float = Field(default=0.05, ge=0, lt=1.0)
    daily_loss_limit_usdc: float = Field(default=50.0, gt=0)
    max_consecutive_losses: int = Field(default=5, gt=0)


class DatabaseConfig(BaseModel):
    """Database connection settings."""

    url: str = "sqlite:///data/trades.db"


class LoggingConfig(BaseModel):
    """Logging settings."""

    level: str = "INFO"
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class AppConfig(BaseModel):
    """Top-level application configuration."""

    model_config = {"protected_namespaces": ()}

    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    source_wallets: List[str] = Field(default_factory=list)
    poll_interval_seconds: int = Field(default=15, gt=0)
    copy: CopyConfig = Field(default_factory=CopyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    dry_run: bool = True
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def _apply_env_overrides(self) -> "AppConfig":
        """Apply environment variable overrides after loading YAML."""
        if pk := os.getenv("POLYMARKET_PRIVATE_KEY"):
            self.polymarket.private_key = pk
        if chain := os.getenv("POLYMARKET_CHAIN_ID"):
            self.polymarket.chain_id = int(chain)
        if clob := os.getenv("POLYMARKET_CLOB_URL"):
            self.polymarket.clob_url = clob
        if gamma := os.getenv("POLYMARKET_GAMMA_URL"):
            self.polymarket.gamma_url = gamma
        if wallets := os.getenv("SOURCE_WALLETS"):
            self.source_wallets = [w.strip() for w in wallets.split(",") if w.strip()]
        if db_url := os.getenv("DATABASE_URL"):
            self.database.url = db_url
        if log_level := os.getenv("LOG_LEVEL"):
            self.logging.level = log_level
        return self


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to YAML config file. Defaults to config/default.yaml
                     relative to the package root.

    Returns:
        Validated AppConfig instance.
    """
    load_dotenv()

    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / "config" / "default.yaml")

    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    return AppConfig(**raw)
