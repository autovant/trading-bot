"""
Scoring plugins for the Confluence Signal Engine.

Each plugin computes a score (0-25) for one of the four evidence buckets:
- Bucket A: Trend Regime
- Bucket B: Oscillator Confluence  
- Bucket C: VWAP + Mean Reversion
- Bucket D: Structure / Levels
"""

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.plugins.oscillator_confluence import OscillatorConfluencePlugin
from src.signal_engine.plugins.structure_levels import StructureLevelsPlugin
from src.signal_engine.plugins.trend_regime import TrendRegimePlugin
from src.signal_engine.plugins.vwap_mean_reversion import VwapMeanReversionPlugin

__all__ = [
    "ScoringPlugin",
    "PluginResult",
    "TrendRegimePlugin",
    "OscillatorConfluencePlugin",
    "VwapMeanReversionPlugin",
    "StructureLevelsPlugin",
]
