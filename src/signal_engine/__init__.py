"""
Confluence Signal Engine - Multi-asset, multi-timeframe trading signal generation.

This module provides:
- 0-100 confluence scoring across 4 evidence buckets
- BUY/SELL/HOLD signals on candle close only (no repainting)
- WebSocket, Webhook, and optional Redis alert delivery
- Configuration-driven subscriptions for any symbol/timeframe
"""

from src.signal_engine.schemas import (
    CandleData,
    FeatureSet,
    SignalOutput,
    AlertPayload,
    SubscriptionConfig,
    StrategyProfile,
    GateResult,
)

__all__ = [
    "CandleData",
    "FeatureSet",
    "SignalOutput",
    "AlertPayload",
    "SubscriptionConfig",
    "StrategyProfile",
    "GateResult",
]

__version__ = "1.0.0"
