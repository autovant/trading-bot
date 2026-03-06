"""
Pydantic schemas for the Confluence Signal Engine.

Defines all data models for:
- Candles and features
- Signal outputs and alerts
- Subscriptions and strategy profiles
- Gate results and scoring
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalSide(str, Enum):
    """Signal direction."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalStrength(str, Enum):
    """Signal strength classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RegimeLabel(str, Enum):
    """Market regime classification."""
    BULL = "bull"
    BEAR = "bear"
    CHOP = "chop"


class OscillatorState(str, Enum):
    """Oscillator state classification."""
    OVERBOUGHT = "overbought"
    OVERSOLD = "oversold"
    NEUTRAL = "neutral"


class VwapBias(str, Enum):
    """VWAP bias classification."""
    ABOVE = "above"
    BELOW = "below"
    AT = "at"


# =============================================================================
# Core Data Models
# =============================================================================

class CandleData(BaseModel):
    """OHLCV candle data."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float = Field(..., alias="o", ge=0)
    high: float = Field(..., alias="h", ge=0)
    low: float = Field(..., alias="l", ge=0)
    close: float = Field(..., alias="c", ge=0)
    volume: float = Field(..., alias="v", ge=0)
    is_closed: bool = True
    
    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info) -> float:
        if "low" in info.data and v < info.data["low"]:
            raise ValueError("high must be >= low")
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with short keys for API output."""
        return {
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
        }


class FeatureSet(BaseModel):
    """Computed indicator features for a candle."""
    model_config = ConfigDict(extra="allow")
    
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    
    # Trend features (Bucket A)
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    ema_trend: Optional[str] = None  # "bullish" | "bearish" | "neutral"
    adx: Optional[float] = None
    adx_plus_di: Optional[float] = None
    adx_minus_di: Optional[float] = None
    price_roc: Optional[float] = None
    
    # Oscillator features (Bucket B)
    rsi: Optional[float] = None
    stoch_rsi_k: Optional[float] = None
    stoch_rsi_d: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_histogram_slope: Optional[float] = None
    mfi: Optional[float] = None
    
    # VWAP features (Bucket C)
    vwap: Optional[float] = None
    vwap_upper: Optional[float] = None
    vwap_lower: Optional[float] = None
    vwap_distance_pct: Optional[float] = None
    volume_zscore: Optional[float] = None
    
    # Structure features (Bucket D)
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    distance_to_sr_pct: Optional[float] = None
    pivot_high: Optional[float] = None
    pivot_low: Optional[float] = None
    
    # ATR for volatility
    atr: Optional[float] = None
    atr_pct: Optional[float] = None


class GateResult(BaseModel):
    """Result of a single gate check."""
    model_config = ConfigDict(extra="forbid")
    
    name: str
    passed: bool
    detail: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "pass": self.passed, "detail": self.detail}


class BucketScore(BaseModel):
    """Score from a single scoring bucket."""
    model_config = ConfigDict(extra="forbid")
    
    name: str
    score: int = Field(..., ge=0, le=25)
    max_score: int = 25
    reasons: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SignalOutput(BaseModel):
    """Complete signal output with scoring details."""
    model_config = ConfigDict(extra="forbid")
    
    exchange: str
    symbol: str
    timeframe: str = Field(..., alias="tf")
    timestamp: datetime = Field(..., alias="ts")
    candle: Dict[str, float]
    score: int = Field(..., ge=0, le=100)
    side: SignalSide
    strength: SignalStrength
    reasons: List[str]
    gates: List[Dict[str, Any]]
    features: Dict[str, Any]
    bucket_scores: Optional[Dict[str, int]] = None
    penalties_applied: Optional[List[str]] = None
    strategy_id: Optional[str] = None
    idempotency_key: str
    
    @classmethod
    def compute_idempotency_key(
        cls,
        exchange: str,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        side: SignalSide,
        score: int,
    ) -> str:
        """Generate unique idempotency key for this signal."""
        data = f"{exchange}:{symbol}:{timeframe}:{timestamp.isoformat()}:{side.value}:{score}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    @classmethod
    def classify_strength(cls, score: int) -> SignalStrength:
        """Classify signal strength based on score."""
        if score >= 75:
            return SignalStrength.HIGH
        elif score >= 55:
            return SignalStrength.MEDIUM
        return SignalStrength.LOW


class AlertPayload(BaseModel):
    """Payload for alert delivery (WebSocket/Webhook)."""
    model_config = ConfigDict(extra="forbid")
    
    exchange: str
    symbol: str
    tf: str
    ts: int  # Unix timestamp in milliseconds
    candle: Dict[str, float]
    score: int
    side: str
    strength: str
    reasons: List[str]
    gates: List[Dict[str, Any]]
    features: Dict[str, Any]
    idempotency_key: str
    
    @classmethod
    def from_signal(cls, signal: SignalOutput) -> "AlertPayload":
        """Create AlertPayload from SignalOutput."""
        return cls(
            exchange=signal.exchange,
            symbol=signal.symbol,
            tf=signal.timeframe,
            ts=int(signal.timestamp.timestamp() * 1000),
            candle=signal.candle,
            score=signal.score,
            side=signal.side.value,
            strength=signal.strength.value,
            reasons=signal.reasons,
            gates=signal.gates,
            features=signal.features,
            idempotency_key=signal.idempotency_key,
        )


# =============================================================================
# Configuration Models
# =============================================================================

class SubscriptionConfig(BaseModel):
    """Configuration for a market data subscription."""
    model_config = ConfigDict(extra="forbid")
    
    id: Optional[int] = None
    exchange: str
    symbol: str
    timeframe: str
    strategy: str = "default"
    enabled: bool = True
    last_candle_ts: Optional[datetime] = None
    
    @field_validator("exchange", "symbol", "timeframe")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("cannot be empty")
        return v.strip()


class BucketWeights(BaseModel):
    """Weights for each scoring bucket."""
    model_config = ConfigDict(extra="forbid")
    
    trend: float = Field(0.25, ge=0, le=1)
    oscillator: float = Field(0.25, ge=0, le=1)
    vwap: float = Field(0.25, ge=0, le=1)
    structure: float = Field(0.25, ge=0, le=1)
    
    @field_validator("structure")
    @classmethod
    def weights_sum_to_one(cls, v: float, info) -> float:
        total = (
            info.data.get("trend", 0.25) +
            info.data.get("oscillator", 0.25) +
            info.data.get("vwap", 0.25) +
            v
        )
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"bucket weights must sum to 1.0, got {total}")
        return v


class GateConfig(BaseModel):
    """Configuration for safety gates."""
    model_config = ConfigDict(extra="forbid")
    
    min_candles: int = Field(200, ge=50)
    cooldown_candles: int = Field(3, ge=0)
    atr_pct_max: float = Field(0.05, ge=0)
    volume_zscore_min: float = Field(-2.0)
    risk_off: bool = False


class StrategyProfile(BaseModel):
    """Complete strategy configuration profile."""
    model_config = ConfigDict(extra="forbid")
    
    name: str
    description: Optional[str] = None
    timeframe: Optional[str] = None
    weights: BucketWeights = Field(default_factory=BucketWeights)
    buy_threshold: int = Field(60, ge=0, le=100)
    sell_threshold: int = Field(40, ge=0, le=100)
    min_trend_score: int = Field(10, ge=0, le=25)
    gates: GateConfig = Field(default_factory=GateConfig)
    htf_confirm: Optional[str] = None  # Higher timeframe for confirmation
    symbol_allowlist: Optional[List[str]] = None
    symbol_denylist: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @field_validator("name")
    @classmethod
    def valid_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("strategy name cannot be empty")
        return v.strip()
    
    def is_symbol_allowed(self, symbol: str) -> bool:
        """Check if symbol is allowed by this strategy."""
        if self.symbol_denylist and symbol in self.symbol_denylist:
            return False
        if self.symbol_allowlist:
            return symbol in self.symbol_allowlist
        return True


class WebhookDestination(BaseModel):
    """Webhook destination configuration."""
    model_config = ConfigDict(extra="forbid")
    
    url: str
    secret: Optional[str] = None
    enabled: bool = True
    retry_count: int = Field(3, ge=0, le=10)
    timeout_seconds: float = Field(10.0, ge=1, le=60)


class AlertConfig(BaseModel):
    """Alert routing configuration."""
    model_config = ConfigDict(extra="forbid")
    
    websocket_enabled: bool = True
    webhooks: List[WebhookDestination] = Field(default_factory=list)


class SignalEngineConfig(BaseModel):
    """Complete signal engine configuration."""
    model_config = ConfigDict(extra="forbid")
    
    subscriptions: List[SubscriptionConfig] = Field(default_factory=list)
    strategies: Dict[str, StrategyProfile] = Field(default_factory=dict)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    max_concurrent_subscriptions: int = Field(10, ge=1, le=100)
    poll_interval_multiplier: float = Field(0.9, ge=0.5, le=1.0)


# =============================================================================
# Database Models (for persistence)
# =============================================================================

class CandleRecord(BaseModel):
    """Database record for stored candles."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: Optional[int] = None
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class FeatureRecord(BaseModel):
    """Database record for computed features."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: Optional[int] = None
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    features: Dict[str, Any]  # JSON blob


class SignalRecord(BaseModel):
    """Database record for emitted signals."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: Optional[int] = None
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    side: str
    strength: str
    score: int
    reasons: List[str]
    gates: List[Dict[str, Any]]
    strategy_id: str
    idempotency_key: str
    created_at: Optional[datetime] = None


class SubscriptionRecord(BaseModel):
    """Database record for subscriptions."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: Optional[int] = None
    exchange: str
    symbol: str
    timeframe: str
    strategy: str = "default"
    enabled: bool = True
    last_candle_ts: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AuditLogRecord(BaseModel):
    """Database record for audit logging."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: Optional[int] = None
    timestamp: datetime
    event_type: str
    payload_hash: str
    status: str
    details: Optional[str] = None
