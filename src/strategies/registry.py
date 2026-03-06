import logging
from typing import Any, Dict, List, Optional

from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Singleton registry for all available strategy presets."""

    _strategies: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, key: str, strategy_class: type, metadata: Dict[str, Any]) -> None:
        """Register a strategy with metadata."""
        cls._strategies[key] = {
            "key": key,
            "class": strategy_class,
            **metadata,
        }
        logger.debug("Registered strategy preset: %s", key)

    @classmethod
    def list_presets(cls) -> List[Dict[str, Any]]:
        """Return list of all registered strategy presets with metadata."""
        if not cls._strategies:
            cls._auto_register()
        return [
            {k: v for k, v in entry.items() if k != "class"}
            for entry in cls._strategies.values()
        ]

    @classmethod
    def get_preset(cls, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific preset by name/key."""
        if not cls._strategies:
            cls._auto_register()
        entry = cls._strategies.get(name)
        if entry is None:
            return None
        return {k: v for k, v in entry.items() if k != "class"}

    @classmethod
    def instantiate(cls, name: str, symbol: str, params: Optional[Dict[str, Any]] = None) -> IStrategy:
        """Create a strategy instance with given params (or defaults)."""
        if not cls._strategies:
            cls._auto_register()
        entry = cls._strategies.get(name)
        if entry is None:
            raise ValueError(f"Unknown strategy preset: {name}")

        strategy_class = entry["class"]
        merged_params = {**entry.get("default_params", {})}
        if params:
            merged_params.update(params)

        return strategy_class(symbol=symbol, **merged_params)

    @classmethod
    def _auto_register(cls) -> None:
        """Auto-discover and register all preset strategies."""
        from src.strategies.presets import (
            AdaptiveRSIStrategy,
            BollingerMeanReversionStrategy,
            BreakoutVolumeStrategy,
            DualMACrossoverStrategy,
            MACDDivergenceStrategy,
            MomentumMeanReversionStrategy,
            MTFTrendVWAPStrategy,
            RSIMomentumStrategy,
            VWAPScalpingStrategy,
        )

        presets = [
            ("bollinger-mean-reversion", BollingerMeanReversionStrategy),
            ("rsi-momentum", RSIMomentumStrategy),
            ("dual-ma-crossover", DualMACrossoverStrategy),
            ("vwap-scalping", VWAPScalpingStrategy),
            ("breakout-volume", BreakoutVolumeStrategy),
            ("macd-divergence", MACDDivergenceStrategy),
            ("momentum-mean-reversion", MomentumMeanReversionStrategy),
            ("adaptive-rsi", AdaptiveRSIStrategy),
            ("mtf-trend-vwap", MTFTrendVWAPStrategy),
        ]

        for key, strategy_cls in presets:
            if key not in cls._strategies:
                cls.register(key, strategy_cls, strategy_cls.METADATA)
