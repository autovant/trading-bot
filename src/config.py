"""
Strict configuration management for the trading platform.

This module centralises configuration loading, validates every setting with
Pydantic, and honours environment overrides while failing closed on invalid
inputs.  The configuration loader enforces the presence of the three
canonical configuration files referenced throughout the platform:

* ``STRATEGY_CFG`` – primary application configuration (YAML).
* ``RISK_CFG`` – risk limits / policy (YAML).
* ``VENUES_CFG`` – venue/static metadata (YAML or JSON).

If any of those files are missing the process aborts with a clear exception.

Every service consumes the single ``APP_MODE`` environment variable which
must be one of ``live | paper | replay``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_MODE = Literal["live", "paper", "replay"]
PRICE_SOURCE = Literal["live", "bars", "replay"]


def _resolve_required_path(
    env_var: str, default: Optional[str], description: str
) -> Path:
    """
    Resolve an absolute Path from an environment variable or a default.

    A helpful ValueError is raised if neither is provided or the resulting file
    does not exist. This guarantees fail-closed behaviour for misconfigured
    deployments.
    """

    candidate = os.getenv(env_var, default)
    if not candidate:
        raise ValueError(
            f"{description} missing; set {env_var} or provide a default path."
        )

    path = Path(candidate).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"{description} not found at '{path}'. Please supply a valid path via {env_var}."
        )

    return path.resolve()


def _substitute_env_vars(data: Any) -> Any:
    """Recursively substitute ${ENV_VAR} tokens inside a YAML document."""

    if isinstance(data, dict):
        return {key: _substitute_env_vars(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    if isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_name = data[2:-1]
        return os.getenv(env_name, data)
    return data


class StrictModel(BaseModel):
    """Pydantic helper that rejects unknown keys and validates on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExchangeConfig(StrictModel):
    """Exchange connectivity configuration."""

    name: str = "bybit"
    api_key: Optional[str] = Field(default=None, description="API key for venue access")
    secret_key: Optional[str] = Field(
        default=None, description="Secret key / signing secret"
    )
    passphrase: Optional[str] = Field(default=None, description="API passphrase")
    testnet: bool = True
    base_url: str = "https://api-testnet.bybit.com"


class TradingConfig(StrictModel):
    """Core trading parameters."""

    initial_capital: float = Field(default=1000.0, ge=0)
    risk_per_trade: float = Field(default=0.006, ge=0, le=1)
    max_positions: int = Field(default=3, ge=0)
    max_daily_risk: float = Field(default=0.05, ge=0, le=1)
    max_sector_exposure: float = Field(default=0.20, ge=0, le=1)
    symbols: List[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    )

    @field_validator("symbols")
    @classmethod
    def _ensure_symbols(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("At least one trading symbol must be configured.")
        return value


class RegimeConfig(StrictModel):
    ema_period: int = Field(default=200, ge=1)
    macd_fast: int = Field(default=12, ge=1)
    macd_slow: int = Field(default=26, ge=1)
    macd_signal: int = Field(default=9, ge=1)
    weight: float = Field(default=0.25, ge=0, le=1)


class SetupConfig(StrictModel):
    ema_fast: int = Field(default=8, ge=1)
    ema_medium: int = Field(default=21, ge=1)
    ema_slow: int = Field(default=55, ge=1)
    adx_period: int = Field(default=14, ge=1)
    adx_threshold: float = Field(default=25.0, ge=0)
    atr_period: int = Field(default=14, ge=1)
    atr_multiplier: float = Field(default=2.0, ge=0)
    weight: float = Field(default=0.30, ge=0, le=1)


class SignalsConfig(StrictModel):
    rsi_period: int = Field(default=14, ge=1)
    rsi_oversold: float = Field(default=40.0, ge=0, le=100)
    rsi_overbought: float = Field(default=60.0, ge=0, le=100)
    donchian_period: int = Field(default=20, ge=1)
    divergence_lookback: int = Field(default=3, ge=1)
    weight: float = Field(default=0.35, ge=0, le=1)


class ConfidenceConfig(StrictModel):
    min_threshold: int = Field(default=50, ge=0, le=100)
    full_size_threshold: int = Field(default=70, ge=0, le=100)
    crisis_threshold: int = Field(default=80, ge=0, le=100)
    penalties: Dict[str, int] = Field(
        default_factory=lambda: {
            "high_volatility": -3,
            "low_volume": -3,
            "conflicting_timeframes": -4,
        }
    )


class StrategyConfig(StrictModel):
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    setup: SetupConfig = Field(default_factory=SetupConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)


class LadderConfig(StrictModel):
    weights: List[float] = Field(default_factory=lambda: [0.25, 0.35, 0.40])
    confirmation_bars: int = Field(default=2, ge=0)
    momentum_bars: int = Field(default=4, ge=0)

    @field_validator("weights")
    @classmethod
    def _weights_sum_to_one(cls, value: List[float]) -> List[float]:
        total = sum(value)
        if abs(total - 1.0) > 0.01:
            raise ValueError("Ladder weights must sum to 1.0")
        return value


class StopsConfig(StrictModel):
    soft_atr_multiplier: float = Field(default=1.5, ge=0)
    hard_risk_percent: float = Field(default=0.02, ge=0, le=1)
    time_based_hours: int = Field(default=48, ge=0)
    trail_atr_multiplier: float = Field(default=1.0, ge=0)


class CrisisModeConfig(StrictModel):
    drawdown_threshold: float = Field(default=0.10, ge=0, le=1)
    consecutive_losses: int = Field(default=3, ge=0)
    volatility_multiplier: float = Field(default=3.0, ge=0)
    position_size_reduction: float = Field(default=0.50, ge=0, le=1)


class RiskManagementConfig(StrictModel):
    ladder_entries: LadderConfig = Field(default_factory=LadderConfig)
    stops: StopsConfig = Field(default_factory=StopsConfig)
    crisis_mode: CrisisModeConfig = Field(default_factory=CrisisModeConfig)


class TimeframesConfig(StrictModel):
    signal: str = "1h"
    setup: str = "4h"
    regime: str = "1d"


class LookbackConfig(StrictModel):
    signal: int = Field(default=200, ge=1)
    setup: int = Field(default=100, ge=1)
    regime: int = Field(default=50, ge=1)


class DataConfig(StrictModel):
    timeframes: TimeframesConfig = Field(default_factory=TimeframesConfig)
    lookback_periods: LookbackConfig = Field(default_factory=LookbackConfig)


class LoggingConfig(StrictModel):
    level: str = "INFO"
    file: str = "logs/trading.log"
    max_size: str = "10MB"
    backup_count: int = Field(default=5, ge=0)


class DatabaseConfig(StrictModel):
    path: Path = Field(default=Path("data/trading.db"))
    backup_interval: int = Field(default=3600, ge=0)

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_path(cls, value: Any) -> Path:
        return Path(value).expanduser()


class BacktestingConfig(StrictModel):
    slippage: float = Field(default=0.0005, ge=0)
    commission: float = Field(default=0.001, ge=0)
    initial_balance: float = Field(default=1000.0, ge=0)


class DashboardConfig(StrictModel):
    enabled: bool = True
    port: int = Field(default=8501, ge=1)
    host: str = "0.0.0.0"
    refresh_interval: int = Field(default=5, ge=1)
    chart_periods: int = Field(default=100, ge=0)
    max_trades_display: int = Field(default=50, ge=0)


class MessagingConfig(StrictModel):
    servers: List[str] = Field(default_factory=lambda: ["nats://localhost:4222"])
    subjects: Dict[str, str] = Field(
        default_factory=lambda: {
            "market_data": "market.data",
            "orders": "trading.orders",
            "positions": "trading.positions",
            "executions": "trading.executions",
            "executions_shadow": "trading.executions.shadow",
            "risk": "risk.management",
            "performance": "performance.metrics",
            "config_reload": "config.reload",
            "replay_control": "replay.control",
            "reports": "reports.performance",
        }
    )

    @field_validator("servers")
    @classmethod
    def _ensure_servers(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("At least one NATS server must be configured.")
        return value


class LatencyConfig(StrictModel):
    mean: float = Field(default=120.0, ge=0)
    p95: float = Field(default=300.0, ge=0)
    jitter: float = Field(default=25.0, ge=0)

    @model_validator(mode="after")
    def _validate_percentiles(self) -> "LatencyConfig":
        if self.p95 < self.mean:
            raise ValueError("latency p95 must be greater than or equal to the mean")
        return self


class PartialFillConfig(StrictModel):
    enabled: bool = True
    min_slice_pct: float = Field(default=0.15, ge=0, le=1)
    max_slices: int = Field(default=4, ge=1)
    randomize: bool = True

    @model_validator(mode="after")
    def _validate_bounds(self) -> "PartialFillConfig":
        if self.enabled and self.min_slice_pct <= 0:
            raise ValueError("min_slice_pct must be > 0 when partial fills are enabled")
        return self


class PaperConfig(StrictModel):
    fee_bps: float = Field(default=7.0, ge=-1000, le=1000)
    maker_rebate_bps: float = Field(default=-1.0, ge=-1000, le=1000)
    funding_enabled: bool = True
    slippage_bps: float = Field(default=3.0, ge=0)
    max_slippage_bps: float = Field(default=10.0, ge=0)
    spread_slippage_coeff: float = Field(default=0.5, ge=0)
    ofi_slippage_coeff: float = Field(default=0.3, ge=0)
    latency_ms: LatencyConfig = Field(default_factory=LatencyConfig)
    partial_fill: PartialFillConfig = Field(default_factory=PartialFillConfig)
    price_source: PRICE_SOURCE = "live"
    seed: int = Field(default=1337, ge=0)

    @model_validator(mode="after")
    def _validate_slippage(self) -> "PaperConfig":
        if self.max_slippage_bps < self.slippage_bps:
            raise ValueError("max_slippage_bps must be >= slippage_bps")
        return self


class ReplayConfig(StrictModel):
    source: str = "parquet://bars/"
    speed: str = "10x"
    start: str = "2023-01-01"
    end: str = "2024-12-31"
    seed: int = Field(default=1337, ge=0)

    @field_validator("speed")
    @classmethod
    def _validate_speed(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.endswith("x"):
            raise ValueError("Replay speed must be in the form '<int>x', e.g. '10x'")
        multiplier = value[:-1]
        if not multiplier.isdigit() or int(multiplier) <= 0:
            raise ValueError("Replay speed multiplier must be a positive integer.")
        return value


class ConfigPaths(StrictModel):
    strategy: Path
    risk: Path
    venues: Path

    @field_validator("strategy", "risk", "venues", mode="before")
    @classmethod
    def _coerce_path(cls, value: Any) -> Path:
        if isinstance(value, Path):
            path = value
        else:
            path = Path(str(value))
        path = path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        return path.resolve()


class TradingBotConfig(BaseSettings):
    """Top level application configuration (strict)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="forbid",
        validate_assignment=True,
    )

    app_mode: APP_MODE = Field(default="paper")
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk_management: RiskManagementConfig = Field(default_factory=RiskManagementConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    backtesting: BacktestingConfig = Field(default_factory=BacktestingConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    messaging: MessagingConfig = Field(default_factory=MessagingConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    replay: ReplayConfig = Field(default_factory=ReplayConfig)
    shadow_paper: bool = False
    config_paths: ConfigPaths

    @model_validator(mode="after")
    def _validate_live_credentials(self) -> "TradingBotConfig":
        """Require API credentials only when running in live mode."""

        if self.app_mode == "live":
            if not self.exchange.api_key or not self.exchange.secret_key:
                raise ValueError(
                    "API key and secret key are required when APP_MODE=live."
                )
        return self


_CONFIG: Optional[TradingBotConfig] = None


def load_config(config_path: Optional[str] = None) -> TradingBotConfig:
    """
    Load configuration from YAML with environment overrides.

    The default strategy config path is ``config/strategy.yaml`` but can be
    overridden via STRATEGY_CFG. RISK_CFG and VENUES_CFG must also be present.
    """

    strategy_path = _resolve_required_path(
        "STRATEGY_CFG", config_path or "config/strategy.yaml", "Strategy configuration"
    )

    # Validate auxiliary config paths upfront (fail fast).
    risk_path = _resolve_required_path(
        "RISK_CFG", "config/risk.yaml", "Risk configuration"
    )
    venues_path = _resolve_required_path(
        "VENUES_CFG", "config/venues.yaml", "Venues configuration"
    )

    with strategy_path.open("r", encoding="utf-8") as handle:
        raw_data = yaml.safe_load(handle) or {}

    config_data = _substitute_env_vars(raw_data)

    # Override app_mode from environment if supplied.
    app_mode_override = os.getenv("APP_MODE")
    if app_mode_override:
        config_data["app_mode"] = app_mode_override

    config_data["config_paths"] = {
        "strategy": str(strategy_path),
        "risk": str(risk_path),
        "venues": str(venues_path),
    }

    return TradingBotConfig(**config_data)


def get_config() -> TradingBotConfig:
    """Return the cached configuration, reloading lazily on first access."""

    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


def reload_config() -> TradingBotConfig:
    """Force reload of configuration (hot reload support)."""

    global _CONFIG
    _CONFIG = load_config()
    return _CONFIG
