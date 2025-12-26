export interface BacktestRequest {
    symbol: string;
    start: string;
    end: string;
}

export interface BacktestJobResponse {
    job_id: string;
    status: string;
    symbol: string;
    start: string;
    end: string;
    submitted_at: string;
    started_at?: string;
    completed_at?: string;
    result?: Record<string, unknown>;
    error?: string;
}

export interface AccountSummaryResponse {
    equity: number;
    balance: number;
    used_margin: number;
    free_margin: number;
    unrealized_pnl: number;
    leverage: number;
    currency: string;
}

export interface StrategyRequest {
    name: string;
    config: Record<string, unknown>;
}

export interface StrategyResponse {
    id?: number;
    name: string;
    config: Record<string, unknown>;
    is_active: boolean;
    created_at?: string;
    updated_at?: string;
}

export interface ModeRequest {
    mode: string;
    shadow?: boolean;
}

export interface ModeResponse {
    mode: string;
    shadow: boolean;
}

export interface PaperConfigResponse {
    fee_bps: number;
    maker_rebate_bps: number;
    funding_enabled: boolean;
    slippage_bps: number;
    max_slippage_bps: number;
    spread_slippage_coeff: number;
    ofi_slippage_coeff: number;
    latency_ms: Record<string, number>;
    partial_fill: Record<string, unknown>;
    price_source: string;
}

export interface PnLDailyEntry {
    date: string;
    mode: string;
    realized_pnl: number;
    unrealized_pnl: number;
    fees: number;
    funding: number;
    commission: number;
    net_pnl: number;
    balance: number;
}

export interface PnLDailyResponse {
    mode: string;
    days: PnLDailyEntry[];
}

export interface PositionResponse {
    symbol: string;
    side: string;
    size: number;
    entry_price: number;
    mark_price: number;
    unrealized_pnl: number;
    percentage: number;
    mode: string;
    run_id: string;
    created_at?: string;
    updated_at?: string;
}

export interface TradeResponse {
    client_id: string;
    trade_id?: string;
    order_id?: string;
    symbol: string;
    side: string;
    quantity: number;
    price: number;
    commission: number;
    fees: number;
    funding: number;
    realized_pnl: number;
    mark_price: number;
    slippage_bps: number;
    achieved_vs_signal_bps: number;
    latency_ms: number;
    maker: boolean;
    mode: string;
    run_id: string;
    timestamp?: string;
    is_shadow: boolean;
}

export interface ConfigResponse {
    version?: string;
    config: Record<string, unknown>;
}

export interface ConfigVersionResponse {
    version: string;
    created_at?: string;
}

export interface RiskSnapshotResponse {
    crisis_mode: boolean;
    consecutive_losses: number;
    drawdown: number;
    volatility: number;
    position_size_factor: number;
    mode: string;
    run_id: string;
    created_at?: string;
    payload: Record<string, unknown>;
}

export interface LogEntry {
    timestamp: string;
    level: string;
    message: string;
    module: string;
}

export interface BotStatusResponse {
    enabled: boolean;
    status: string;
    symbol: string;
    mode: string;
}

// Additional types that might be useful
export interface OrderResponse {
    order_id: string;
    client_id: string;
    symbol: string;
    side: string; // 'buy' | 'sell'
    order_type: string; // 'market' | 'limit' | 'stop' | 'stop_market'
    quantity: number;
    price: number;
    status: string;
    mode: string;
    timestamp: string;
}

export interface MarketSnapshot {
    symbol: string;
    best_bid: number;
    best_ask: number;
    bid_size: number;
    ask_size: number;
    last_price: number;
    timestamp: string;
}
