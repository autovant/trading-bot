"""
Base class for Confluence Signal Engine scoring plugins.

Each plugin computes a score (0-25) for one evidence bucket.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.signal_engine.schemas import StrategyProfile


@dataclass
class PluginResult:
    """Result from a scoring plugin computation."""
    
    name: str
    score: int  # 0-25
    max_score: int = 25
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Clamp score to valid range
        self.score = max(0, min(self.max_score, self.score))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "max_score": self.max_score,
            "reasons": self.reasons,
            "metadata": self.metadata,
        }


class ScoringPlugin(ABC):
    """
    Abstract base class for confluence scoring plugins.
    
    Each plugin analyzes a specific aspect of market data:
    - Trend Regime (Bucket A)
    - Oscillator Confluence (Bucket B)  
    - VWAP + Mean Reversion (Bucket C)
    - Structure / Levels (Bucket D)
    
    Plugins compute a score from 0-25 based on their analysis.
    """
    
    name: str = "base"
    max_score: int = 25
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize plugin with optional configuration.
        
        Args:
            config: Plugin-specific configuration overrides
        """
        self.config = config or {}
    
    @abstractmethod
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """
        Compute plugin score from OHLCV data.
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
                Must have at least strategy.gates.min_candles rows.
            strategy: Strategy profile with weights and parameters
            
        Returns:
            PluginResult with score 0-25, reasons, and metadata
        """
        pass
    
    def validate_data(self, df: pd.DataFrame, min_periods: int = 200) -> bool:
        """
        Validate input data has required columns and sufficient periods.
        
        Args:
            df: Input DataFrame
            min_periods: Minimum required data points
            
        Returns:
            True if data is valid, False otherwise
        """
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            raise ValueError(f"Missing required columns: {missing}")
        
        if len(df) < min_periods:
            return False
        
        return True
    
    def safe_get(self, series: pd.Series, idx: int = -1, default: float = 0.0) -> float:
        """Safely get value from series at index."""
        try:
            val = series.iloc[idx]
            if pd.isna(val):
                return default
            return float(val)
        except (IndexError, KeyError):
            return default


class CompositePlugin(ScoringPlugin):
    """
    Composite plugin that combines multiple sub-plugins.
    
    Useful for testing or creating custom scoring combinations.
    """
    
    name: str = "composite"
    
    def __init__(
        self,
        plugins: List[ScoringPlugin],
        weights: Optional[List[float]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(config)
        self.plugins = plugins
        self.weights = weights or [1.0 / len(plugins)] * len(plugins)
        
        if len(self.weights) != len(self.plugins):
            raise ValueError("Weights must match number of plugins")
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """Compute weighted average of sub-plugin scores."""
        total_score = 0.0
        all_reasons = []
        all_metadata = {}
        
        for plugin, weight in zip(self.plugins, self.weights):
            result = plugin.compute(df, strategy)
            total_score += result.score * weight
            all_reasons.extend(result.reasons)
            all_metadata[plugin.name] = result.metadata
        
        return PluginResult(
            name=self.name,
            score=int(round(total_score)),
            max_score=self.max_score,
            reasons=all_reasons,
            metadata=all_metadata,
        )
