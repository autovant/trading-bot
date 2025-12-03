export interface OrderBookData {
    symbol: string;
    best_bid: number;
    best_ask: number;
    bid_size: number;
    ask_size: number;
    last_price: number;
    timestamp: string;
}

export interface ExecutionReport {
    symbol: string;
    side: 'buy' | 'sell' | 'long' | 'short';
    quantity: number;
    price: number;
    order_id: string;
    executed: boolean;
    timestamp: string;
    client_id?: string;
    status?: string;
}

export interface Position {
    symbol: string;
    side: 'long' | 'short';
    size: number;
    entry_price: number;
    mark_price: number;
    unrealized_pnl: number;
    percentage: number;
    liq_price?: number;
    mode: string;
}

export interface Order {
    order_id: string;
    symbol: string;
    side: 'buy' | 'sell';
    type: 'market' | 'limit';
    quantity: number;
    price?: number;
    status: 'new' | 'filled' | 'canceled' | 'rejected';
    timestamp: string;
    filled_qty?: number;
}

export interface AccountSummary {
    equity: number;
    balance: number;
    unrealized_pnl: number;
    margin_used: number;
    free_margin: number;
    leverage: number;
}

export interface SystemStatus {
    status: 'ok' | 'warning' | 'error';
    message?: string;
    latency_ms: number;
    last_updated: string;
    connected: boolean;
}

export interface MarketDataState {
    ticker: Record<string, { price: number; change_24h: number }>;
    orderBook: OrderBookData | null;
    isConnected: boolean;
}

export interface StrategyConfig {
    name: string;
    description?: string;
    regime: Record<string, any>;
    setup: Record<string, any>;
    signals: Record<string, any>[];
    risk: Record<string, any>;
    confidence_threshold: number;
}

export interface Strategy {
    id?: number;
    name: string;
    config: StrategyConfig;
    is_active: boolean;
    created_at?: string;
    updated_at?: string;
}
