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

APP_MODE = Literal["live", "paper", "replay", "backtest"]
PRICE_SOURCE = Literal["live", "bars", "replay"]
APP_MODE = Literal["live", "paper", "replay", "backtest"]
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
        return os.getenv(env_name, None)
    return data


def _assert_no_literal_secrets(raw_data: Dict[str, Any]) -> None:
    exchange_cfg = raw_data.get("exchange") or {}
    for key in ("api_key", "secret_key", "passphrase"):
        value = exchange_cfg.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            if stripped.startswith("${") and stripped.endswith("}"):
                continue
        raise ValueError(
            f"Secrets must not be stored in config files (exchange.{key}). "
            "Use environment variables instead."
        )


class StrictModel(BaseModel):
    """Pydantic helper that rejects unknown keys and validates on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExchangeConfig(StrictModel):
    provider: Literal["bybit", "zoomex"] = "bybit"
    name: str = "bybit"
    api_key: Optional[str] = Field(default=None, description="API key for venue access")
    secret_key: Optional[str] = Field(
        default=None, description="Secret key / signing secret"
    )
    passphrase: Optional[str] = Field(default=None, description="API passphrase")
    testnet: bool = True
    base_url: Optional[str] = None


class PerpsConfig(StrictModel):
    enabled: bool = False
    exchange: Literal["zoomex"] = "zoomex"
    symbol: str = "SOLUSDT"
    interval: str = "5"
    leverage: int = Field(default=1, ge=1)
    mode: Literal["oneway", "hedge"] = "oneway"
    positionIdx: int = Field(default=0, ge=0, le=2)
    riskPct: float = Field(default=0.005, ge=0, le=1)
    stopLossPct: float = Field(default=0.01, ge=0, le=1)
    takeProfitPct: float = Field(default=0.03, ge=0, le=1)
    cashDeployCap: float = Field(default=0.20, ge=0, le=1)
    triggerBy: Literal["LastPrice", "MarkPrice", "IndexPrice"] = "LastPrice"
    useMultiTfAtrStrategy: bool = True
    htfInterval: str = "60"
    atrPeriod: int = Field(default=14, ge=1)
    atrStopMultiple: float = Field(default=1.5, ge=0)
    hardStopMinPct: float = Field(default=0.0075, ge=0)
    tp1Multiple: float = Field(default=1.0, ge=0)
    tp2Multiple: float = Field(default=2.5, ge=0)
    maxBarsInTrade: int = Field(default=100, ge=1)
    minAtrPct: float = Field(default=0.002, ge=0)
    minAtrUsd: Optional[float] = Field(default=None, ge=0)
    useRsiFilter: bool = True
    rsiPeriod: int = Field(default=14, ge=1)
    rsiMin: int = Field(default=40, ge=0, le=100)
    rsiMax: int = Field(default=70, ge=0, le=100)
    useVolumeFilter: bool = False
    volumeLookback: int = Field(default=20, ge=1)
    volumeSpikeMultiplier: float = Field(default=1.25, ge=0)
    exitOnTrendFlip: bool = True
    maxEmaDistanceAtr: float = Field(default=0.75, ge=0)
    wickAtrBuffer: float = Field(default=0.35, ge=0)
    atrRiskScaling: bool = True
    atrRiskScalingThreshold: float = Field(default=0.02, ge=0)
    atrRiskScalingFactor: float = Field(default=0.5, ge=0, le=1)
    breakevenAfterTp1: bool = True
    earlyExitOnCross: bool = False
    useTestnet: bool = True
    consecutiveLossLimit: Optional[int] = Field(default=None, ge=1)
    maxMarginRatio: float = Field(default=0.8, ge=0, le=1)
    maxRequestsPerSecond: int = Field(default=5, ge=1)
    maxRequestsPerMinute: int = Field(default=60, ge=1)
    stateFile: Optional[str] = "data/perps_state.json"
    sessionMaxTrades: Optional[int] = Field(default=None, ge=1)
    sessionMaxRuntimeMinutes: Optional[int] = Field(default=None, ge=1)
    maxDataStalenessSeconds: int = Field(default=120, ge=1)
    maxDataGapMultiplier: float = Field(default=2.5, ge=1.0)
    timeSyncIntervalSeconds: int = Field(default=60, ge=1)
    timeSyncMaxSkewMs: int = Field(default=1000, ge=0)

    @model_validator(mode="after")
    def _validate_mode(self) -> "PerpsConfig":
        mode = self.mode
        idx = self.positionIdx
        if mode == "oneway" and idx != 0:
            raise ValueError("positionIdx must be 0 in oneway mode")
        if mode == "hedge" and idx not in (1, 2):
            raise ValueError("positionIdx must be 1 or 2 in hedge mode")
        if self.tp2Multiple < self.tp1Multiple:
            raise ValueError("tp2Multiple must be >= tp1Multiple")
        if self.rsiMin >= self.rsiMax:
            raise ValueError("rsiMin must be less than rsiMax")
        return self


class TradingConfig(StrictModel):
    initial_capital: float = Field(default=10000.0, ge=0)
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDT"])
    risk_per_trade: float = Field(default=0.006, ge=0, le=1)
    max_positions: int = Field(default=3, ge=1)
    max_daily_risk: float = Field(default=0.05, ge=0, le=1)
    max_sector_exposure: float = Field(default=0.20, ge=0, le=1)

    @field_validator("symbols")
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
    weight: float = Field(default=0.3, ge=0, le=1)
    # Optional fields that might not be in yaml but are in code logic
    crisis_threshold: int = Field(default=80, ge=0, le=100)
    penalties: Dict[str, int] = Field(
        default_factory=lambda: {
            "high_volatility": -3,
            "low_volume": -3,
            "conflicting_timeframes": -4,
        }
    )


class VWAPConfig(StrictModel):
    enabled: bool = False
    mode: Literal["session", "rolling"] = "session"
    rolling_window: int = Field(default=20, ge=1)
    require_price_above_vwap_for_longs: bool = True
    require_price_below_vwap_for_shorts: bool = True


class OrderBookConfig(StrictModel):
    enabled: bool = False
    depth: int = Field(default=5, ge=1)
    imbalance_threshold: float = Field(default=0.2, ge=0, le=1)
    wall_multiplier: float = Field(default=3.0, ge=1)
    use_for_entry: bool = True
    use_for_exit: bool = False


class OrderBookRiskConfig(StrictModel):
    enabled: bool = False
    widen_sl_on_adverse_imbalance: bool = False
    sl_widen_factor: float = Field(default=1.5, ge=1)
    reduce_size_on_high_spread: bool = False
    spread_threshold_bps: float = Field(default=5.0, ge=0)
    size_reduction_factor: float = Field(default=0.5, ge=0, le=1)


class ConfidenceConfig(StrictModel):
    min_threshold: float = Field(default=70.0, ge=0, le=100)
    crisis_threshold: float = Field(default=80.0, ge=0, le=100)
    full_size_threshold: float = Field(default=70.0, ge=0, le=100)
    regime_weight: float = Field(default=0.3, ge=0, le=1)
    setup_weight: float = Field(default=0.3, ge=0, le=1)
    signal_weight: float = Field(default=0.4, ge=0, le=1)
    penalties: Dict[str, int] = Field(default_factory=dict)


class SignalsConfig(StrictModel):
    pullback_enabled: bool = True
    breakout_enabled: bool = True
    divergence_enabled: bool = False
    # Fields from yaml
    divergence_lookback: int = Field(default=3, ge=1)
    donchian_period: int = Field(default=20, ge=1)
    bollinger_period: int = Field(default=20, ge=1)
    bollinger_std_dev: float = Field(default=2.0, ge=0)
    rsi_overbought: int = Field(default=60, ge=0, le=100)
    rsi_oversold: int = Field(default=40, ge=0, le=100)
    rsi_period: int = Field(default=14, ge=1)
    weight: float = Field(default=0.35, ge=0, le=1)


class StrategyConfig(StrictModel):
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    setup: SetupConfig = Field(default_factory=SetupConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    vwap: VWAPConfig = Field(default_factory=VWAPConfig)
    orderbook: OrderBookConfig = Field(default_factory=OrderBookConfig)
    orderbook_risk: OrderBookRiskConfig = Field(default_factory=OrderBookRiskConfig)
    active_strategies: List[str] = Field(default_factory=list)

    @classmethod
    def from_db_row(cls, row: Any) -> Optional["StrategyConfig"]:
        """
        Parses a database strategy row (SQLAlchemy model) into a StrategyConfig object.
        """
        if not row:
            return None

        # Helper to safely parse JSON or return dict
        def parse_json(field: Any) -> Dict[str, Any]:
            if isinstance(field, str):
                import json

                try:
                    return json.loads(field)
                except json.JSONDecodeError:
                    return {}
            elif isinstance(field, dict):
                return field
            return {}

        try:
            # Extract JSON fields from the DB model
            regime_dict = parse_json(row.regime_config)
            setup_dict = parse_json(row.setup_config)
            signals_dict = parse_json(row.signals_config)
            confidence_dict = parse_json(row.confidence_config)
            vwap_dict = parse_json(row.vwap_config)
            ob_dict = parse_json(row.orderbook_config)
            ob_risk_dict = parse_json(row.orderbook_risk_config)

            # Construct config object using Pydantic validation
            # Any missing fields will fallback to defaults defined in sub-models
            return cls(
                regime=RegimeConfig(**regime_dict),
                setup=SetupConfig(**setup_dict),
                signals=SignalsConfig(**signals_dict),
                confidence=ConfidenceConfig(**confidence_dict),
                vwap=VWAPConfig(**vwap_dict),
                orderbook=OrderBookConfig(**ob_dict),
                orderbook_risk=OrderBookRiskConfig(**ob_risk_dict),
                # If DB has a name field or similar, we might want to track it, but StrategyConfig
                # strictly defines parameters. Strategy ID/Name is usually meta-data.
            )
        except Exception:
            # logging.error(f"Failed to parse strategy config from DB row: {e}")
            return None


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
    url: str = Field(
        default="sqlite:///data/trades.db"
    )
    min_pool_size: int = Field(default=5, ge=1)
    max_pool_size: int = Field(default=20, ge=1)
    backup_interval: int = Field(default=3600, ge=0)


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
    max_leverage: float = Field(default=5.0, ge=1.0)
    initial_margin_pct: float = Field(default=0.1, ge=0, le=1)
    maintenance_margin_pct: float = Field(default=0.005, ge=0, le=1)
    seed: int = Field(default=1337, ge=0)

    @model_validator(mode="after")
    def _validate_slippage(self) -> "PaperConfig":
        if self.max_slippage_bps < self.slippage_bps:
            raise ValueError("max_slippage_bps must be >= slippage_bps")
        if self.initial_margin_pct < self.maintenance_margin_pct:
            raise ValueError(
                "initial_margin_pct must be greater than or equal to maintenance_margin_pct"
            )
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
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    app_mode: APP_MODE = "paper"
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
    perps: PerpsConfig = Field(default_factory=PerpsConfig)
    shadow_paper: bool = False
    config_paths: ConfigPaths

    # Local overrides used by the Windows deploy script (extra fields expected in .env).
    nats_url: Optional[str] = None
    db_url: Optional[str] = None
    api_port: Optional[int] = None
    ui_port: Optional[int] = None
    ops_api_url: Optional[str] = None
    exec_port: Optional[int] = None
    feed_port: Optional[int] = None
    risk_port: Optional[int] = None
    reporter_port: Optional[int] = None
    replay_port: Optional[int] = None
    ops_port: Optional[int] = None
    log_level: Optional[str] = None

    @model_validator(mode="after")
    def _validate_live_credentials(self) -> "TradingBotConfig":
        """Require API credentials only when running in live mode."""

        if self.app_mode == "live":
            if not self.exchange.api_key or not self.exchange.secret_key:
                raise ValueError(
                    "API key and secret key are required when APP_MODE=live."
                )
            if self.exchange.testnet:
                raise ValueError("Live mode cannot use testnet exchange endpoints.")
            if self.perps.useTestnet:
                raise ValueError("Live mode cannot use testnet perps endpoints.")
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

    _assert_no_literal_secrets(raw_data)

    config_data = _substitute_env_vars(raw_data)

    config_data["config_paths"] = {
        "strategy": str(strategy_path),
        "risk": str(risk_path),
        "venues": str(venues_path),
    }

    app_mode_override = os.getenv("APP_MODE")
    if app_mode_override:
        config_data["app_mode"] = app_mode_override

    # Remove legacy manual environment manipulation.
    # Pydantic BaseSettings handles environment variables automatically.
    # We still check APP_MODE manually to force override on the dictionary if needed,
    # or we could rely on APP_MODE env var if config_data doesn't have it.
    
    app_mode_override = os.getenv("APP_MODE")
    if app_mode_override:
        config_data["app_mode"] = app_mode_override

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
