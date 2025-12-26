from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Shared Enums/Types can go here or be imported if they are complex
# For now, we keep it simple effectively mirroring api_server.py models

class BacktestRequest(BaseModel):
    symbol: str
    start: str
    end: str

class BacktestJobResponse(BaseModel):
    job_id: str
    status: str
    symbol: str
    start: str
    end: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class AccountSummaryResponse(BaseModel):
    equity: float
    balance: float
    used_margin: float
    free_margin: float
    unrealized_pnl: float
    leverage: float
    currency: str = "USD"

class StrategyRequest(BaseModel):
    name: str
    config: Dict[str, Any]

class StrategyResponse(BaseModel):
    id: Optional[int] = None
    name: str
    config: Dict[str, Any]
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ModeRequest(BaseModel):
    mode: str
    shadow: bool = False

class ModeResponse(BaseModel):
    mode: str
    shadow: bool

class PaperConfigResponse(BaseModel):
    fee_bps: float
    maker_rebate_bps: float
    funding_enabled: bool
    slippage_bps: float
    max_slippage_bps: float
    spread_slippage_coeff: float
    ofi_slippage_coeff: float
    latency_ms: Dict[str, float]
    partial_fill: Dict[str, Any]
    price_source: str

class PnLDailyEntry(BaseModel):
    date: str
    mode: str
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    funding: float
    commission: float
    net_pnl: float
    balance: float

class PnLDailyResponse(BaseModel):
    mode: str
    days: List[PnLDailyEntry]

class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    mode: str
    run_id: str
    created_at: Optional[str]
    updated_at: Optional[str]

class TradeResponse(BaseModel):
    client_id: str
    trade_id: Optional[str]
    order_id: Optional[str]
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    fees: float
    funding: float
    realized_pnl: float
    mark_price: float
    slippage_bps: float
    achieved_vs_signal_bps: float
    latency_ms: float
    maker: bool
    mode: str
    run_id: str
    timestamp: Optional[str]
    is_shadow: bool

class ConfigResponse(BaseModel):
    version: Optional[str]
    config: Dict[str, Any]

class ConfigVersionResponse(BaseModel):
    version: str
    created_at: Optional[str]

class RiskSnapshotResponse(BaseModel):
    crisis_mode: bool
    consecutive_losses: int
    drawdown: float
    volatility: float
    position_size_factor: float
    mode: str
    run_id: str
    created_at: Optional[str]
    payload: Dict[str, Any]

class ConfigStageRequest(BaseModel):
    risk_per_trade: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    soft_atr_multiplier: Optional[float] = Field(default=None, ge=0.0)
    spread_budget_bps: Optional[float] = Field(default=None, ge=0.0)

class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    module: str

class BotStatusResponse(BaseModel):
    enabled: bool
    status: str
    symbol: str
    mode: str


class OrderResponse(BaseModel):
    order_id: str
    client_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float
    status: str
    mode: str
    timestamp: str
