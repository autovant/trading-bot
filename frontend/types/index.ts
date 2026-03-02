
export enum Side {
    BUY = 'BUY',
    SELL = 'SELL',
}

export enum OrderType {
    LIMIT = 'LIMIT',
    MARKET = 'MARKET',
    STOP = 'STOP',
}

export enum OrderStatus {
    OPEN = 'OPEN',
    FILLED = 'FILLED',
    CANCELLED = 'CANCELLED',
    REJECTED = 'REJECTED',
    PENDING = 'PENDING',
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
}

export interface Order {
    id: string;
    idempotencyKey?: string;
    symbol: string;
    side: Side;
    type: OrderType;
    size: number;
    price: number;
    status: OrderStatus;
    timestamp: number;
    exchange: ExchangeId;
    isSimulation: boolean;
    error?: string;
    triggerPrice?: number; // For Stop orders
    filledSize?: number;
    avgFillPrice?: number;
    remainingSize?: number;
    lastUpdate?: number;
    lastEventId?: string;
    updateSequence?: number;
}

export interface ExecutionUpdate {
    orderId: string;
    status: OrderStatus;
    filledPrice?: number;
    filledSize?: number;
    timestamp: number;
    message?: string;
    eventId: string;
    sequence: number;
    remainingSize?: number;
    avgFillPrice?: number;
    retriable?: boolean;
}

export interface OrderBookItem {
    price: number;
    size: number;
    total: number;
    percent: number; // For visualization bar
}

export interface Position {
    id: string;
    sourceOrderId?: string;
    symbol: string;
    side: Side;
    size: number;
    entryPrice: number;
    markPrice: number;
    leverage: number;
    uPnL: number;
    roe: number;
    initialMargin: number; // Added for precise ROE calc
    liquidationPrice: number; // New: Critical for leveraged trading
    isSimulation?: boolean;
}

export interface TradeHistoryItem {
    id: string;
    sourceOrderId?: string;
    symbol: string;
    side: Side;
    size: number;
    entryPrice: number;
    exitPrice: number;
    leverage: number;
    pnl: number;
    fee: number;
    closedAt: number;
    type: 'TRADE' | 'LIQUIDATION';
    isSimulation?: boolean;
}

export interface Candle {
    time: string; // HH:mm
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    timestamp?: number;
}

export interface TradeSuggestion {
    symbol: string;
    direction: 'LONG' | 'SHORT' | 'WAIT';
    entryPrice: number;
    stopLoss: number;
    takeProfit: number;
    confidence: number;
    reasoning: string;
}

export interface MarketAnalysis {
    symbol: string;
    sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
    summary: string;
    supportLevel: number;
    resistanceLevel: number;
    signal: 'LONG' | 'SHORT' | 'WAIT';
    confidence: number;
}

export interface ChatMessage {
    id: string;
    role: 'user' | 'ai';
    text: string;
    timestamp: Date;
    isThinking?: boolean;
    tradeSuggestion?: TradeSuggestion;
    marketAnalysis?: MarketAnalysis;
}

export type TabType = 'market' | 'strategy' | 'backtest' | 'settings' | 'signals';
export type ExchangeId = 'ZOOMEX' | 'BYBIT' | 'PHEMEX' | 'BINGX' | 'MEXC';

// --- API & Security Types ---

export interface ExchangeApiConfig {
    exchangeId: ExchangeId;
    apiKey: string; // Encrypted/Obfuscated in storage
    apiSecret: string; // Encrypted/Obfuscated in storage
    isActive: boolean;
    lastTested: number | null;
    status: 'CONNECTED' | 'DISCONNECTED' | 'ERROR';
}

export interface ExecutionResult {
    success: boolean;
    orderId?: string;
    error?: string;
    filledPrice?: number;
    latencyMs: number;
}

export interface MarketDataHealth {
    status: 'OK' | 'STALE' | 'DEGRADED';
    isStale: boolean;
    lastTickerAt?: number;
    lastOrderBookAt?: number;
    lastCandleAt?: number;
    lastMessageAt?: number;
    staleForMs?: number;
    clockSkewMs?: number;
    reason?: string;
}

export interface MarketSnapshot {
    price: number;
    bestBid?: number;
    bestAsk?: number;
    timestamp: number;
    isStale: boolean;
    staleForMs?: number;
    clockSkewMs?: number;
    source?: 'ticker' | 'candle' | 'manual';
    symbol?: string;
}

export interface Notification {
    id: string;
    type: 'success' | 'error' | 'info' | 'warning';
    title: string;
    message: string;
    timestamp: number;
}

// --- Strategy Engine Types ---

export type IndicatorType = 'SMA' | 'EMA' | 'RSI';

export interface IndicatorDefinition {
    id: string;
    type: IndicatorType;
    period: number;
    color: string;
}

export type LogicOperator = '>' | '<' | '==';

export interface RuleCondition {
    id: string;
    left: string; // Indicator ID or 'PRICE'
    operator: LogicOperator;
    right: string; // Indicator ID, 'PRICE', or static number string
}

export interface StrategyConfig {
    id: string;
    name: string;
    description?: string;
    updatedAt: number;
    symbol: string;
    exchange: ExchangeId;
    timeframe: string;
    direction: 'LONG' | 'SHORT';
    fee: number;
    indicators: IndicatorDefinition[];
    entryRules: RuleCondition[];
    exitRules: RuleCondition[];
    lastStats?: BacktestStats; // Persisted performance metrics
}

export interface BacktestTrade {
    id: string;
    entryTime: string;
    entryPrice: number;
    entryIndex: number;
    exitTime: string;
    exitPrice: number;
    exitIndex: number;
    side: Side;
    pnl: number;
    pnlPercent: number;
}

export interface EquityPoint {
    time: string;
    value: number;
    candleIndex: number;
}

export interface BacktestStats {
    totalTrades: number;
    winRate: number;
    profitFactor: number;
    totalPnL: number;
    maxDrawdown: number;
    maxDrawdownPercent: number;
    sharpeRatio: number;
    sortinoRatio: number;
}

export interface BacktestResult extends BacktestStats {
    equityCurve: EquityPoint[];
    trades: BacktestTrade[];
}

export interface BacktestRecord {
    id: string;
    strategyId: string;
    strategyName: string;
    symbol: string;
    timeframe: string;
    startDate: string;
    endDate: string;
    executedAt: number;
    stats: BacktestStats;
}

export interface BackendOrderUpdate {
    orderId: string;
    status: OrderStatus;
    sequence: number;
    isReplay?: boolean;
    data: Order;
}

export interface BackendSignal {
    id: string;
    symbol: string;
    type: 'LONG' | 'SHORT';
    price: number;
    timestamp: number;
}

