"use client";

import React, { useState, useEffect } from 'react';
import { MarketStream } from '@/services/marketStream';
import { ChartWidget } from '@/components/ChartWidget';
import { OrderBook } from '@/components/OrderBook';
import { Order, OrderBookItem, Candle, ExchangeId, TradeSuggestion, Position, Side, OrderType, OrderStatus, Notification, TradeHistoryItem, MarketDataHealth } from '@/types';
import { ExecutionService } from '@/services/execution';
import { Card } from '@/components/ui/Card';
import { useAccountState } from '@/lib/useAccountState';
import { backendApi } from '@/services/backend';
import { Wallet, Settings2, ChevronDown, Loader2, Zap, Wifi, XCircle, AlertCircle, Activity, ListOrdered, Clock } from 'lucide-react';

const DEFAULT_LEVERAGE = 20;

// Temporary AI signal logic (Mock)
const mockAiSignal = (price: number): TradeSuggestion => {
    const signal = Math.random() > 0.7 ? (Math.random() > 0.5 ? 'LONG' : 'SHORT') : 'WAIT';
    return {
        symbol: 'BTC-PERP',
        direction: signal,
        confidence: Math.floor(Math.random() * 40) + 60,
        entryPrice: price,
        takeProfit: signal === 'LONG' ? price * 1.05 : price * 0.95,
        stopLoss: signal === 'LONG' ? price * 0.98 : price * 1.02,
        reasoning: "Market momentum indicates a potential breakout pattern with increasing volume."
    };
};

export const MarketView: React.FC = () => {
    // --- State ---
    const [activeSymbol, setActiveSymbol] = useState('BTC-PERP');
    const [timeframe, setTimeframe] = useState('1h');
    const [currentExchange, setCurrentExchange] = useState<ExchangeId>('BYBIT');

    // Data State
    const [candles, setCandles] = useState<Candle[]>([]);
    const [orderBook, setOrderBook] = useState<{ bids: OrderBookItem[], asks: OrderBookItem[] }>({ bids: [], asks: [] });
    const [currentPrice, setCurrentPrice] = useState<number>(0);
    const [connectionStatus, setConnectionStatus] = useState<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED');
    const [marketHealth, setMarketHealth] = useState<MarketDataHealth | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    // Account State (Persistent)
    const {
        balance, setBalance,
        positions, setPositions,
        orders, setOrders,
        activeOrders,
        tradeHistory, setTradeHistory
    } = useAccountState();

    // AI
    const [tradeSuggestion, setTradeSuggestion] = useState<TradeSuggestion | null>(null);

    // Notifications
    const [notifications, setNotifications] = useState<Notification[]>([]);

    // Order Form State
    const [orderSide, setOrderSide] = useState<Side>(Side.BUY);
    const [orderType, setOrderType] = useState<OrderType>(OrderType.LIMIT);
    const [orderSize, setOrderSize] = useState<string>('0.5');
    const [orderPrice, setOrderPrice] = useState<string>('');
    const [orderTriggerPrice, setOrderTriggerPrice] = useState<string>('');
    const [isLiveMode, setIsLiveMode] = useState(false);
    const [isExecuting, setIsExecuting] = useState(false);

    // Bottom Panel Tab
    const [activeBottomTab, setActiveBottomTab] = useState<'positions' | 'orders' | 'history'>('positions');

    // --- Notification Helper ---
    const addNotification = (type: Notification['type'], title: string, message: string) => {
        const id = Date.now().toString();
        setNotifications(prev => [...prev, { id, type, title, message, timestamp: Date.now() }]);
        setTimeout(() => {
            setNotifications(prev => prev.filter(n => n.id !== id));
        }, 5000);
    };

    // --- Effects ---

    // 1. Initial History Fetch + Real-time Subscription
    useEffect(() => {
        setCandles([]);
        setIsLoading(true);

        const loadHistory = async () => {
            const data = await MarketStream.fetchHistory(activeSymbol, timeframe);
            if (data.length > 0) {
                setCandles(data);
                const lastClose = data[data.length - 1].close;
                setCurrentPrice(lastClose);
                setOrderPrice(lastClose.toFixed(2));
                setTradeSuggestion(mockAiSignal(lastClose));
            }
            setIsLoading(false);
        };
        loadHistory();

        const unsub = MarketStream.subscribe(activeSymbol, {
            onTicker: (price) => {
                setCurrentPrice(price);
            },
            onOrderBook: (data) => {
                setOrderBook(data);
            },
            onCandle: (candle) => {
                setCandles(prev => {
                    if (prev.length === 0) return [candle];
                    const last = prev[prev.length - 1];
                    if (last.time === candle.time) {
                        return [...prev.slice(0, -1), candle];
                    }
                    return [...prev, candle];
                });
            },
            onStatus: (status) => setConnectionStatus(status),
            onHealth: (health) => setMarketHealth(health)
        });

        return () => unsub();
    }, [activeSymbol, timeframe]);

    // 2. Positions PnL Update Loop
    useEffect(() => {
        const interval = setInterval(() => {
            setPositions(prev => prev.map(pos => {
                const pnl = pos.side === Side.BUY
                    ? (currentPrice - pos.entryPrice) * pos.size
                    : (pos.entryPrice - currentPrice) * pos.size;
                const initialMargin = (pos.entryPrice * pos.size) / pos.leverage;
                const roe = initialMargin > 0 ? (pnl / initialMargin) * 100 : 0;
                return { ...pos, markPrice: currentPrice, uPnL: pnl, roe, initialMargin };
            }));
        }, 1000);
        return () => clearInterval(interval);
    }, [currentPrice, setPositions]);

    // --- Order Placement ---
    const placeOrder = async () => {
        const size = parseFloat(orderSize);
        let limitPrice = parseFloat(orderPrice);
        let stopPrice = parseFloat(orderTriggerPrice);

        if (isNaN(size) || size <= 0) {
            addNotification('error', 'Invalid Order', 'Please enter a valid size.');
            return;
        }

        if (orderType === OrderType.MARKET) {
            limitPrice = currentPrice;
        } else if (orderType === OrderType.LIMIT) {
            if (isNaN(limitPrice) || limitPrice <= 0) {
                addNotification('error', 'Invalid Price', 'Please enter a valid price.');
                return;
            }
        } else if (orderType === OrderType.STOP) {
            if (isNaN(stopPrice) || stopPrice <= 0) {
                addNotification('error', 'Invalid Trigger', 'Please enter a valid trigger price.');
                return;
            }
            limitPrice = isNaN(limitPrice) ? currentPrice : limitPrice;
        }

        const newOrderId = typeof crypto !== 'undefined' && 'randomUUID' in crypto
            ? crypto.randomUUID()
            : `ord_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

        const newOrder: Order = {
            id: newOrderId,
            idempotencyKey: newOrderId,
            symbol: activeSymbol,
            side: orderSide,
            type: orderType,
            size: size,
            price: limitPrice,
            triggerPrice: orderType === OrderType.STOP ? stopPrice : undefined,
            status: isLiveMode ? OrderStatus.PENDING : OrderStatus.OPEN,
            timestamp: Date.now(),
            exchange: currentExchange,
            isSimulation: !isLiveMode,
            filledSize: 0,
            remainingSize: size,
            lastUpdate: Date.now(),
            updateSequence: 0
        };

        setOrders(prev => [newOrder, ...prev]);
        setIsExecuting(true);

        if (isLiveMode) {
            // Call backend API for live orders
            try {
                const result = await backendApi.placeOrder(newOrder);
                if (result.success) {
                    addNotification('info', 'Order Submitted', `Order sent to ${currentExchange}`);
                } else {
                    addNotification('error', 'Order Failed', result.error || 'Unknown error');
                    setOrders(prev => prev.map(o =>
                        o.id === newOrderId ? { ...o, status: OrderStatus.REJECTED, error: result.error } : o
                    ));
                }
            } catch (e) {
                addNotification('error', 'Network Error', 'Failed to submit order');
            }
        } else {
            // Paper trading - simulate immediate fill for market orders
            if (orderType === OrderType.MARKET) {
                const filledOrder = { ...newOrder, status: OrderStatus.FILLED, filledSize: size, avgFillPrice: limitPrice };
                setOrders(prev => prev.map(o => o.id === newOrderId ? filledOrder : o));

                // Create position
                const margin = (limitPrice * size) / DEFAULT_LEVERAGE;
                const liquidationPrice = orderSide === Side.BUY
                    ? limitPrice * (1 - 1 / DEFAULT_LEVERAGE * 0.9)
                    : limitPrice * (1 + 1 / DEFAULT_LEVERAGE * 0.9);

                const newPosition: Position = {
                    id: `pos_${Date.now()}`,
                    sourceOrderId: newOrderId,
                    symbol: activeSymbol,
                    side: orderSide,
                    size: size,
                    entryPrice: limitPrice,
                    markPrice: limitPrice,
                    leverage: DEFAULT_LEVERAGE,
                    uPnL: 0,
                    roe: 0,
                    initialMargin: margin,
                    liquidationPrice: liquidationPrice,
                    isSimulation: true
                };
                setPositions(prev => [...prev, newPosition]);
                setBalance(prev => prev - margin);
                addNotification('success', 'Order Filled', `Market order filled at ${limitPrice.toFixed(2)}`);
            } else {
                addNotification('info', 'Paper Order', 'Order placed in simulation engine.');
            }
        }
        setIsExecuting(false);
    };

    const handleCancelOrder = async (orderId: string) => {
        const order = orders.find(o => o.id === orderId);
        if (!order) return;

        setOrders(prev => prev.map(o =>
            o.id === orderId ? { ...o, status: OrderStatus.CANCELLED } : o
        ));

        if (!order.isSimulation) {
            await backendApi.cancelOrder(orderId, order.symbol);
        }
        addNotification('warning', 'Order Cancelled', `Order ${orderId.slice(0, 8)}... cancelled`);
    };

    const closePosition = (id: string) => {
        const pos = positions.find(p => p.id === id);
        if (!pos) return;

        const exitPrice = pos.markPrice;
        const realizedPnL = pos.side === Side.BUY
            ? (exitPrice - pos.entryPrice) * pos.size
            : (pos.entryPrice - exitPrice) * pos.size;
        const fee = exitPrice * pos.size * 0.0006;

        setBalance(prev => prev + pos.initialMargin + realizedPnL - fee);

        const historyItem: TradeHistoryItem = {
            id: `hist_${Date.now()}`,
            sourceOrderId: pos.sourceOrderId,
            symbol: pos.symbol,
            side: pos.side,
            size: pos.size,
            entryPrice: pos.entryPrice,
            exitPrice: exitPrice,
            leverage: pos.leverage,
            pnl: realizedPnL - fee,
            fee: fee,
            closedAt: Date.now(),
            type: 'TRADE',
            isSimulation: pos.isSimulation
        };
        setTradeHistory(prev => [historyItem, ...prev]);
        setPositions(prev => prev.filter(p => p.id !== id));

        addNotification((realizedPnL - fee) >= 0 ? 'success' : 'warning', 'Position Closed',
            `Realized: ${realizedPnL - fee >= 0 ? '+' : ''}${(realizedPnL - fee).toFixed(2)} USDT`);
    };

    const toggleLiveMode = (next: boolean) => {
        if (next) {
            addNotification('warning', 'Live Mode', 'Live trading requires API keys in Settings');
        }
        setIsLiveMode(next);
    };

    const isOrderBlocked = isExecuting || (marketHealth?.isStale ?? true);

    return (
        <div className="h-full flex flex-col overflow-hidden bg-background-primary">
            {/* Notifications */}
            <div className="fixed top-20 right-6 z-[100] flex flex-col gap-2 pointer-events-none">
                {notifications.map(n => (
                    <div key={n.id} className={`pointer-events-auto bg-card/90 backdrop-blur-md border border-white/10 shadow-2xl rounded-xl p-4 min-w-[300px] animate-fade-in border-l-4 ${n.type === 'success' ? 'border-l-accent-success' : n.type === 'error' ? 'border-l-accent-danger' : 'border-l-accent-primary'}`}>
                        <div className="flex justify-between items-start">
                            <div className="font-bold text-sm text-white mb-1">{n.title}</div>
                            <div className="text-[10px] text-text-tertiary">{new Date(n.timestamp).toLocaleTimeString()}</div>
                        </div>
                        <div className="text-xs text-text-secondary">{n.message}</div>
                    </div>
                ))}
            </div>

            {/* Main Grid Layout */}
            <div className="flex-1 grid grid-cols-12 grid-rows-12 gap-4 p-4 min-h-0">
                {/* Chart Area - 9 cols, 8 rows */}
                <div className="col-span-9 row-span-8 relative">
                    <Card className="h-full w-full flex flex-col" noPadding>
                        {isLoading ? (
                            <div className="flex-1 flex flex-col items-center justify-center text-text-tertiary gap-2">
                                <Loader2 size={32} className="animate-spin text-accent-primary" />
                                <span className="text-xs">Loading Market Data...</span>
                            </div>
                        ) : (
                            <ChartWidget
                                data={candles}
                                tradeSuggestion={tradeSuggestion}
                                currentExchange={currentExchange}
                                onExchangeChange={setCurrentExchange}
                                currentTimeframe={timeframe}
                                onTimeframeChange={setTimeframe}
                            />
                        )}
                    </Card>
                </div>

                {/* Right Panel - OrderBook + Order Form - 3 cols, 12 rows */}
                <div className="col-span-3 row-span-12 flex flex-col gap-4">
                    <Card className="flex-1 flex flex-col min-h-0" noPadding>
                        <OrderBook bids={orderBook.bids} asks={orderBook.asks} currentPrice={currentPrice} />
                    </Card>

                    {/* Order Form */}
                    <Card className="h-auto shrink-0 flex flex-col gap-4 bg-card relative overflow-hidden" data-testid="order-form">
                        {/* Paper/Live Toggle */}
                        <div className="flex justify-center mb-1">
                            <div className="bg-background-secondary p-1 rounded-full flex gap-1 relative border border-white/5">
                                <button onClick={() => toggleLiveMode(false)} className={`px-6 py-1 text-[10px] font-bold uppercase tracking-wider rounded-full transition-all z-10 ${!isLiveMode ? 'text-white' : 'text-text-tertiary'}`}>Paper</button>
                                <button onClick={() => toggleLiveMode(true)} className={`px-6 py-1 text-[10px] font-bold uppercase tracking-wider rounded-full transition-all z-10 flex items-center gap-1 ${isLiveMode ? 'text-white' : 'text-text-tertiary'}`}>Live <Zap size={10} className={isLiveMode ? "fill-accent-warning text-accent-warning" : ""} /></button>
                                <div className={`absolute top-1 bottom-1 w-[50%] bg-card rounded-full transition-all duration-300 ${isLiveMode ? 'left-[48%] bg-accent-warning/20 border border-accent-warning/30' : 'left-1 bg-brand/20 border border-brand/30'}`}></div>
                            </div>
                        </div>

                        {/* Buy/Sell Toggle */}
                        <div className="flex gap-1 p-1 bg-background-elevated rounded-lg">
                            <button onClick={() => setOrderSide(Side.BUY)} data-testid="btn-buy" className={`flex-1 py-2 rounded text-sm font-bold transition-all ${orderSide === Side.BUY ? 'bg-accent-success text-white shadow-sm' : 'text-text-secondary hover:text-white'}`}>Buy / Long</button>
                            <button onClick={() => setOrderSide(Side.SELL)} data-testid="btn-sell" className={`flex-1 py-2 rounded text-sm font-bold transition-all ${orderSide === Side.SELL ? 'bg-accent-danger text-white shadow-sm' : 'text-text-secondary hover:text-white'}`}>Sell / Short</button>
                        </div>

                        <div className="space-y-3">
                            <div className="flex justify-between text-xs text-text-tertiary">
                                <span>Avail: {balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT</span>
                                <Wallet size={12} />
                            </div>

                            {/* Order Type */}
                            <div className="relative group z-20">
                                <label className="text-[10px] text-text-tertiary mb-1 block uppercase tracking-wider font-semibold">Order Type</label>
                                <div className="relative">
                                    <select value={orderType} onChange={(e) => setOrderType(e.target.value as OrderType)} data-testid="select-order-type" className="w-full bg-background-elevated border border-white/5 rounded-lg px-3 py-2 text-sm appearance-none focus:border-brand focus:outline-none transition-colors cursor-pointer text-white">
                                        <option value={OrderType.LIMIT}>Limit Order</option>
                                        <option value={OrderType.MARKET}>Market Order</option>
                                        <option value={OrderType.STOP}>Stop Order</option>
                                    </select>
                                    <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary pointer-events-none" />
                                </div>
                            </div>

                            {/* Trigger Price (Stop orders) */}
                            {orderType === OrderType.STOP && (
                                <div className="relative group animate-fade-in">
                                    <label className="absolute -top-2 left-2 px-1 bg-background-elevated text-[10px] text-text-tertiary group-focus-within:text-accent-primary transition-colors">Trigger Price</label>
                                    <input type="number" value={orderTriggerPrice} onChange={(e) => setOrderTriggerPrice(e.target.value)} placeholder="0.00" data-testid="input-order-trigger-price" className="w-full bg-background-secondary border border-white/5 rounded-lg px-3 py-2 text-right font-mono text-sm focus:border-accent-primary focus:outline-none transition-colors" />
                                    <span className="absolute right-3 top-2.5 text-xs text-text-tertiary">USDT</span>
                                </div>
                            )}

                            {/* Price */}
                            <div className={`relative group transition-opacity ${orderType === OrderType.MARKET ? 'opacity-50' : ''}`}>
                                <label className="absolute -top-2 left-2 px-1 bg-background-elevated text-[10px] text-text-tertiary group-focus-within:text-accent-primary transition-colors">{orderType === OrderType.STOP ? 'Order Price' : 'Price'}</label>
                                <input type="number" value={orderType === OrderType.MARKET ? '' : orderPrice} onChange={(e) => setOrderPrice(e.target.value)} disabled={orderType === OrderType.MARKET} placeholder={orderType === OrderType.MARKET ? "Market Price" : "0.00"} data-testid="input-order-price" className="w-full bg-background-secondary border border-white/5 rounded-lg px-3 py-2 text-right font-mono text-sm focus:border-accent-primary focus:outline-none transition-colors disabled:cursor-not-allowed disabled:bg-white/5" />
                                <span className="absolute right-3 top-2.5 text-xs text-text-tertiary">USDT</span>
                            </div>

                            {/* Size */}
                            <div className="relative group">
                                <label className="absolute -top-2 left-2 px-1 bg-background-elevated text-[10px] text-text-tertiary group-focus-within:text-accent-primary transition-colors">Size</label>
                                <input type="number" data-testid="input-size" value={orderSize} onChange={(e) => setOrderSize(e.target.value)} placeholder="0.00" className="w-full bg-background-secondary border border-white/5 rounded-lg px-3 py-2 text-right font-mono text-sm focus:border-accent-primary focus:outline-none transition-colors" />
                                <span className="absolute right-3 top-2.5 text-xs text-text-tertiary">BTC</span>
                            </div>

                            {/* Leverage */}
                            <div className="flex justify-between items-center py-2">
                                <span className="text-xs text-text-secondary">Leverage</span>
                                <div className="flex items-center gap-1 text-xs font-bold text-accent-primary cursor-pointer hover:text-white bg-accent-primary/10 px-2 py-1 rounded"><span>{DEFAULT_LEVERAGE}x</span><Settings2 size={12} /></div>
                            </div>

                            {/* Submit Button */}
                            <button onClick={placeOrder} disabled={isOrderBlocked} className={`w-full py-3 font-bold rounded-lg transition-all active:scale-[0.98] shadow-lg flex items-center justify-center gap-2 ${orderSide === Side.BUY ? 'bg-accent-success hover:bg-accent-success/90 shadow-accent-success/20' : 'bg-accent-danger hover:bg-accent-danger/90 shadow-accent-danger/20'} text-white disabled:opacity-70 disabled:cursor-not-allowed`}>
                                {isExecuting ? <Loader2 size={16} className="animate-spin" /> : (orderSide === Side.BUY ? 'Buy / Long' : 'Sell / Short')}
                                {!isExecuting && ' BTC'}
                            </button>

                            {isLiveMode && <div className="text-[10px] text-center text-text-tertiary flex items-center justify-center gap-1"><Wifi size={10} className="text-accent-success" />Connected to {currentExchange} Execution</div>}
                        </div>
                    </Card>
                </div>

                {/* Bottom Panel - Positions/Orders/History - 9 cols, 4 rows */}
                <div className="col-span-9 row-span-4">
                    <Card className="h-full flex flex-col" noPadding>
                        <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between">
                            <div className="flex gap-6">
                                <button onClick={() => setActiveBottomTab('positions')} className={`text-sm font-medium transition-all pb-3 -mb-3.5 border-b-2 ${activeBottomTab === 'positions' ? 'text-text-primary border-accent-primary' : 'text-text-tertiary border-transparent hover:text-text-primary'}`}>Positions ({positions.length})</button>
                                <button onClick={() => setActiveBottomTab('orders')} className={`text-sm font-medium transition-all pb-3 -mb-3.5 border-b-2 ${activeBottomTab === 'orders' ? 'text-text-primary border-accent-primary' : 'text-text-tertiary border-transparent hover:text-text-primary'}`}>Open Orders ({activeOrders.length})</button>
                                <button onClick={() => setActiveBottomTab('history')} className={`text-sm font-medium transition-all pb-3 -mb-3.5 border-b-2 ${activeBottomTab === 'history' ? 'text-text-primary border-accent-primary' : 'text-text-tertiary border-transparent hover:text-text-primary'}`}>Trade History ({tradeHistory.length})</button>
                            </div>
                            <div className="flex items-center gap-2 text-xs text-text-secondary">
                                <input type="checkbox" className="rounded bg-white/10 border-none" /><span>Hide other symbols</span>
                            </div>
                        </div>

                        <div className="flex-1 overflow-y-auto custom-scrollbar" data-testid="positions-table">
                            {/* Positions Tab */}
                            {activeBottomTab === 'positions' && (
                                <>
                                    <div className="grid grid-cols-12 gap-4 px-4 py-2 bg-background-secondary/30 text-xs text-text-tertiary uppercase tracking-wider font-semibold sticky top-0 z-10 backdrop-blur-sm">
                                        <div className="col-span-2">Symbol</div>
                                        <div className="col-span-2 text-right">Size</div>
                                        <div className="col-span-2 text-right">Entry Price</div>
                                        <div className="col-span-2 text-right">Mark Price</div>
                                        <div className="col-span-2 text-right">PnL (ROE%)</div>
                                        <div className="col-span-2 text-right">Action</div>
                                    </div>
                                    {positions.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center h-24 text-text-tertiary text-sm"><p>No open positions</p></div>
                                    ) : positions.map(pos => (
                                        <div key={pos.id} className="grid grid-cols-12 gap-4 px-4 py-3 border-b border-white/5 text-sm hover:bg-white/5 group">
                                            <div className="col-span-2 font-bold flex items-center gap-2">
                                                {pos.symbol}
                                                <span className={`text-[10px] px-1 rounded ${pos.side === Side.BUY ? 'bg-accent-success/20 text-accent-success' : 'bg-accent-danger/20 text-accent-danger'}`}>{pos.side}</span>
                                            </div>
                                            <div className="col-span-2 text-right font-mono">{pos.size}</div>
                                            <div className="col-span-2 text-right font-mono">{pos.entryPrice.toFixed(2)}</div>
                                            <div className="col-span-2 text-right font-mono">{pos.markPrice.toFixed(2)}</div>
                                            <div className={`col-span-2 text-right font-mono ${pos.uPnL >= 0 ? 'text-accent-success' : 'text-accent-danger'}`}>
                                                {pos.uPnL >= 0 ? '+' : ''}{pos.uPnL.toFixed(2)} ({pos.roe.toFixed(1)}%)
                                            </div>
                                            <div className="col-span-2 text-right">
                                                <button onClick={() => closePosition(pos.id)} className="text-xs bg-accent-danger/10 text-accent-danger px-3 py-1.5 rounded-md hover:bg-accent-danger/20 transition-colors border border-accent-danger/20">Close</button>
                                            </div>
                                        </div>
                                    ))}
                                </>
                            )}

                            {/* Orders Tab */}
                            {activeBottomTab === 'orders' && (
                                <div className="flex flex-col min-h-[100px]">
                                    {activeOrders.length === 0 && <p className="text-center text-text-tertiary mt-8">No open orders</p>}
                                    {activeOrders.map(order => (
                                        <div key={order.id} className="w-full grid grid-cols-12 gap-4 px-4 py-3 border-b border-white/5 text-sm hover:bg-white/5">
                                            <div className="col-span-2 font-bold flex items-center gap-2">
                                                {order.symbol}
                                                {order.isSimulation ? <span className="text-[10px] bg-white/10 px-1 rounded">PAPER</span> : <span className="text-[10px] bg-accent-warning/20 text-accent-warning px-1 rounded">LIVE</span>}
                                            </div>
                                            <div className="col-span-2 text-right font-mono">{order.size}</div>
                                            <div className="col-span-2 text-right font-mono">{order.type === OrderType.MARKET ? 'MARKET' : order.price}</div>
                                            <div className={`col-span-2 text-right font-bold ${order.side === Side.BUY ? 'text-accent-success' : 'text-accent-danger'}`}>{order.side}</div>
                                            <div className="col-span-4 text-right text-xs text-text-tertiary flex items-center justify-end gap-2">
                                                <span>{new Date(order.timestamp).toLocaleTimeString()}</span>
                                                <span className="text-[10px] uppercase tracking-wide">{order.status.replace(/_/g, ' ')}</span>
                                                <button onClick={() => handleCancelOrder(order.id)} className="text-accent-danger hover:text-accent-danger/80">Cancel</button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* History Tab */}
                            {activeBottomTab === 'history' && (
                                <>
                                    <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-background-secondary/30 text-xs text-text-tertiary uppercase tracking-wider font-semibold sticky top-0 z-10 backdrop-blur-sm">
                                        <div className="col-span-2">Symbol</div>
                                        <div className="col-span-1">Type</div>
                                        <div className="col-span-1">Side</div>
                                        <div className="col-span-1 text-right">Lev.</div>
                                        <div className="col-span-1 text-right">Size</div>
                                        <div className="col-span-1 text-right">Entry</div>
                                        <div className="col-span-1 text-right">Exit</div>
                                        <div className="col-span-1 text-right">Fee</div>
                                        <div className="col-span-3 text-right">Net PnL</div>
                                    </div>
                                    {tradeHistory.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center h-24 text-text-tertiary text-sm"><p>No trade history available</p></div>
                                    ) : tradeHistory.map(hist => (
                                        <div key={hist.id} className={`grid grid-cols-12 gap-2 px-4 py-3 border-b border-white/5 text-sm hover:bg-white/5 ${hist.type === 'LIQUIDATION' ? 'bg-accent-danger/5' : ''}`}>
                                            <div className="col-span-2 font-bold flex flex-col">
                                                <span className="flex items-center gap-1">
                                                    {hist.symbol}
                                                    {hist.type === 'LIQUIDATION' && <AlertCircle size={10} className="text-accent-danger" />}
                                                </span>
                                                <span className="text-[10px] font-normal text-text-tertiary">{new Date(hist.closedAt).toLocaleTimeString()}</span>
                                            </div>
                                            <div className="col-span-1 flex items-center">
                                                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${hist.type === 'LIQUIDATION' ? 'bg-accent-danger/20 border-accent-danger/30 text-accent-danger' : 'bg-background-elevated border-white/10 text-text-secondary'}`}>
                                                    {hist.type === 'LIQUIDATION' ? 'LIQ' : 'TRADE'}
                                                </span>
                                            </div>
                                            <div className={`col-span-1 font-bold flex items-center ${hist.side === Side.BUY ? 'text-accent-success' : 'text-accent-danger'}`}>{hist.side}</div>
                                            <div className="col-span-1 text-right font-mono text-text-secondary">{hist.leverage}x</div>
                                            <div className="col-span-1 text-right font-mono text-text-secondary">{hist.size}</div>
                                            <div className="col-span-1 text-right font-mono text-text-secondary text-xs">{hist.entryPrice.toFixed(0)}</div>
                                            <div className="col-span-1 text-right font-mono text-text-secondary text-xs">{hist.exitPrice.toFixed(0)}</div>
                                            <div className="col-span-1 text-right font-mono text-text-tertiary text-xs">{hist.fee.toFixed(2)}</div>
                                            <div className={`col-span-3 text-right font-mono font-medium ${hist.pnl >= 0 ? 'text-accent-success' : 'text-accent-danger'}`}>
                                                {hist.pnl >= 0 ? '+' : ''}{hist.pnl.toFixed(2)}
                                                <span className="text-xs text-text-tertiary ml-1">USDT</span>
                                            </div>
                                        </div>
                                    ))}
                                </>
                            )}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
};
