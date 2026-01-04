"""
Configuration loader for the Confluence Signal Engine.

Handles loading and validation of:
- Subscriptions (exchange, symbol, timeframe)
- Strategy profiles with weights and thresholds
- Alert routing destinations
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.signal_engine.schemas import (
    AlertConfig,
    SignalEngineConfig,
    StrategyProfile,
    SubscriptionConfig,
    BucketWeights,
    GateConfig,
)

logger = logging.getLogger(__name__)

# Default configuration paths
DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
SIGNAL_ENGINE_CONFIG = "signal_engine.yaml"
STRATEGIES_DIR = "strategies"


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file and return dict."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file and return dict."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_strategy_profile(path: Path) -> StrategyProfile:
    """Load a strategy profile from JSON or YAML file."""
    if path.suffix == ".json":
        data = load_json(path)
    elif path.suffix in (".yaml", ".yml"):
        data = load_yaml(path)
    else:
        raise ValueError(f"Unsupported strategy file format: {path.suffix}")
    
    # Parse nested configs
    if "weights" in data and isinstance(data["weights"], dict):
        data["weights"] = BucketWeights(**data["weights"])
    if "gates" in data and isinstance(data["gates"], dict):
        data["gates"] = GateConfig(**data["gates"])
    
    return StrategyProfile(**data)


def load_strategies_from_dir(directory: Path) -> Dict[str, StrategyProfile]:
    """Load all strategy profiles from a directory."""
    strategies = {}
    
    if not directory.exists():
        logger.warning(f"Strategies directory not found: {directory}")
        return strategies
    
    for path in directory.glob("*.json"):
        try:
            profile = load_strategy_profile(path)
            strategies[profile.name] = profile
            logger.info(f"Loaded strategy: {profile.name} from {path.name}")
        except Exception as e:
            logger.error(f"Failed to load strategy from {path}: {e}")
    
    for path in directory.glob("*.yaml"):
        try:
            profile = load_strategy_profile(path)
            strategies[profile.name] = profile
            logger.info(f"Loaded strategy: {profile.name} from {path.name}")
        except Exception as e:
            logger.error(f"Failed to load strategy from {path}: {e}")
    
    return strategies


def load_signal_engine_config(
    config_path: Optional[Path] = None,
    strategies_dir: Optional[Path] = None,
) -> SignalEngineConfig:
    """
    Load complete signal engine configuration.
    
    Args:
        config_path: Path to main config YAML. Defaults to config/signal_engine.yaml
        strategies_dir: Path to strategies directory. Defaults to config/strategies
        
    Returns:
        Validated SignalEngineConfig instance
    """
    config_path = config_path or DEFAULT_CONFIG_DIR / SIGNAL_ENGINE_CONFIG
    strategies_dir = strategies_dir or DEFAULT_CONFIG_DIR / STRATEGIES_DIR
    
    # Load main config
    if config_path.exists():
        raw_config = load_yaml(config_path)
    else:
        logger.warning(f"Signal engine config not found at {config_path}, using defaults")
        raw_config = {}
    
    # Load strategies from directory
    strategies = load_strategies_from_dir(strategies_dir)
    
    # Also load inline strategies from config if present
    if "strategies" in raw_config:
        for name, strategy_data in raw_config["strategies"].items():
            if name not in strategies:
                try:
                    if "weights" in strategy_data and isinstance(strategy_data["weights"], dict):
                        strategy_data["weights"] = BucketWeights(**strategy_data["weights"])
                    if "gates" in strategy_data and isinstance(strategy_data["gates"], dict):
                        strategy_data["gates"] = GateConfig(**strategy_data["gates"])
                    strategy_data["name"] = name
                    strategies[name] = StrategyProfile(**strategy_data)
                except Exception as e:
                    logger.error(f"Failed to parse inline strategy '{name}': {e}")
    
    # Build subscriptions
    subscriptions = []
    if "subscriptions" in raw_config:
        for sub_data in raw_config["subscriptions"]:
            try:
                subscriptions.append(SubscriptionConfig(**sub_data))
            except Exception as e:
                logger.error(f"Failed to parse subscription: {sub_data}, error: {e}")
    
    # Build alerts config
    alerts = AlertConfig()
    if "alerts" in raw_config:
        alerts_data = raw_config["alerts"]
        if "websocket" in alerts_data:
            alerts.websocket_enabled = alerts_data["websocket"].get("enabled", True)
        if "webhooks" in alerts_data:
            alerts.webhooks = alerts_data["webhooks"]
        if "redis" in alerts_data:
            alerts.redis_enabled = alerts_data["redis"].get("enabled", False)
            alerts.redis_url = alerts_data["redis"].get("url")
            alerts.redis_channel = alerts_data["redis"].get("channel", "signals")
    
    # Build final config
    max_concurrent = raw_config.get("max_concurrent_subscriptions", 10)
    poll_multiplier = raw_config.get("poll_interval_multiplier", 0.9)
    
    config = SignalEngineConfig(
        subscriptions=subscriptions,
        strategies=strategies,
        alerts=alerts,
        max_concurrent_subscriptions=max_concurrent,
        poll_interval_multiplier=poll_multiplier,
    )
    
    logger.info(
        f"Loaded signal engine config: {len(subscriptions)} subscriptions, "
        f"{len(strategies)} strategies"
    )
    
    return config


def get_default_strategy() -> StrategyProfile:
    """Get default strategy profile."""
    return StrategyProfile(
        name="default",
        description="Default balanced strategy",
        weights=BucketWeights(trend=0.25, oscillator=0.25, vwap=0.25, structure=0.25),
        buy_threshold=60,
        sell_threshold=40,
        min_trend_score=10,
        gates=GateConfig(
            min_candles=200,
            cooldown_candles=3,
            atr_pct_max=0.05,
            volume_zscore_min=-2.0,
            risk_off=False,
        ),
    )


# =============================================================================
# Timeframe Utilities
# =============================================================================

TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
    "1M": 2592000,  # ~30 days
}


def timeframe_to_seconds(tf: str) -> int:
    """Convert CCXT timeframe string to seconds."""
    if tf in TIMEFRAME_SECONDS:
        return TIMEFRAME_SECONDS[tf]
    
    # Parse custom formats like "2h", "45m"
    import re
    match = re.match(r"(\d+)([mhdwM])", tf)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}
        return value * multipliers.get(unit, 60)
    
    raise ValueError(f"Unknown timeframe format: {tf}")


def get_htf_timeframe(tf: str, multiplier: int = 4) -> str:
    """Get higher timeframe (approximately 4x larger by default)."""
    tf_order = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w"]
    
    if tf not in tf_order:
        return "1d"  # Default fallback
    
    idx = tf_order.index(tf)
    # Jump approximately 4x (2-3 positions in the list)
    htf_idx = min(idx + 3, len(tf_order) - 1)
    return tf_order[htf_idx]


class ConfigManager:
    """Runtime configuration manager for the signal engine."""
    
    def __init__(self, config: Optional[SignalEngineConfig] = None):
        self._config = config or load_signal_engine_config()
        self._strategies: Dict[str, StrategyProfile] = {}
        self._load_strategies()
    
    def _load_strategies(self) -> None:
        """Load strategies from config."""
        self._strategies = dict(self._config.strategies)
        if "default" not in self._strategies:
            self._strategies["default"] = get_default_strategy()
    
    @property
    def config(self) -> SignalEngineConfig:
        return self._config
    
    @property
    def subscriptions(self) -> List[SubscriptionConfig]:
        return self._config.subscriptions
    
    @property
    def alerts(self) -> AlertConfig:
        return self._config.alerts
    
    def get_strategy(self, name: str) -> StrategyProfile:
        """Get strategy by name, falling back to default."""
        return self._strategies.get(name, self._strategies["default"])
    
    def add_strategy(self, strategy: StrategyProfile) -> None:
        """Add or update a strategy."""
        self._strategies[strategy.name] = strategy
    
    def remove_strategy(self, name: str) -> bool:
        """Remove a strategy by name."""
        if name in self._strategies and name != "default":
            del self._strategies[name]
            return True
        return False
    
    def list_strategies(self) -> List[str]:
        """List all strategy names."""
        return list(self._strategies.keys())
    
    def add_subscription(self, sub: SubscriptionConfig) -> None:
        """Add a subscription."""
        self._config.subscriptions.append(sub)
    
    def remove_subscription(self, sub_id: int) -> bool:
        """Remove subscription by ID."""
        for i, sub in enumerate(self._config.subscriptions):
            if sub.id == sub_id:
                self._config.subscriptions.pop(i)
                return True
        return False
    
    def get_subscription(self, exchange: str, symbol: str, tf: str) -> Optional[SubscriptionConfig]:
        """Find subscription by key fields."""
        for sub in self._config.subscriptions:
            if sub.exchange == exchange and sub.symbol == symbol and sub.timeframe == tf:
                return sub
        return None
