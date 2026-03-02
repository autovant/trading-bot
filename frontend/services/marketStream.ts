
import { Candle, OrderBookItem, MarketDataHealth } from '@/types';


// Bybit V5 Public Linear (Perpetual) WebSocket
const WS_URL = 'wss://stream.bybit.com/v5/public/linear';
// Pointing to our Python backend which should implement /api/klines with proxy or DB support
const REST_URL = 'http://localhost:8000/api/klines';

type TickerCallback = (price: number) => void;
type OrderBookCallback = (data: { bids: OrderBookItem[], asks: OrderBookItem[] }) => void;
type CandleCallback = (candle: Candle) => void;
type StatusCallback = (status: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED') => void;
type HealthCallback = (health: MarketDataHealth) => void;

interface Subscription {
    onTicker: TickerCallback;
    onOrderBook: OrderBookCallback;
    onCandle: CandleCallback;
    onStatus?: StatusCallback;
    onHealth?: HealthCallback;
}

class MarketStreamService {
    private ws: WebSocket | null = null;
    private activeSymbol: string | null = null;
    private pingInterval: any;
    private reconnectTimeout: any;
    private subscribers: Subscription[] = [];
    private healthInterval: any;
    private lastTickerAt = 0;
    private lastOrderBookAt = 0;
    private lastCandleAt = 0;
    private lastMessageAt = 0;
    private lastServerTimestamp: number | null = null;
    private staleThresholdMs = 8000;

    // Order Book State
    private currentBids: Map<string, number> = new Map();
    private currentAsks: Map<string, number> = new Map();

    private mapSymbol(symbol: string): string {
        // Map internal symbols to Bybit symbols
        if (symbol === 'BTC-PERP') return 'BTCUSDT';
        if (symbol === 'ETH-PERP') return 'ETHUSDT';
        if (symbol === 'SOL-PERP') return 'SOLUSDT';
        if (symbol === 'XRP-PERP') return 'XRPUSDT';
        if (symbol === 'DOGE-PERP') return 'DOGEUSDT';
        if (symbol === 'AVAX-PERP') return 'AVAXUSDT';
        if (symbol === 'LINK-PERP') return 'LINKUSDT';
        return symbol.replace('-', '');
    }

    private mapInterval(timeframe: string): string {
        if (timeframe === '1m') return '1';
        if (timeframe === '5m') return '5';
        if (timeframe === '15m') return '15';
        if (timeframe === '1h') return '60';
        if (timeframe === '4h') return '240';
        if (timeframe === '1d') return 'D';
        return '1';
    }

    private getDurationMs(timeframe: string): number {
        const min = 60 * 1000;
        switch (timeframe) {
            case '1m': return min;
            case '5m': return 5 * min;
            case '15m': return 15 * min;
            case '1h': return 60 * min;
            case '4h': return 4 * 60 * min;
            case '1d': return 24 * 60 * min;
            default: return min;
        }
    }

    public async fetchHistory(symbol: string, timeframe: string = '1h'): Promise<Candle[]> {
        // Default to last 200 candles
        const duration = 200 * this.getDurationMs(timeframe);
        return this.fetchHistoryRange(symbol, timeframe, Date.now() - duration, Date.now());
    }

    public async fetchHistoryRange(symbol: string, timeframe: string, startMs: number, endMs: number): Promise<Candle[]> {
        const apiSymbol = this.mapSymbol(symbol);
        const apiInterval = this.mapInterval(timeframe);
        const allCandles: Candle[] = [];
        const LIMIT = 1000; // Bybit max is 1000 for V5

        let currentEnd = endMs;

        try {
            while (currentEnd > startMs) {
                // Backend API must support 'end', 'start', 'limit', 'symbol', 'interval'
                // If Python backend doesn't support 'end', this loop might be broken.
                // We will assume backend implementation will be updated.
                const url = `${REST_URL}?symbol=${apiSymbol}&interval=${apiInterval}&end=${currentEnd}&limit=${LIMIT}`;

                const res = await fetch(url);
                const data = await res.json();

                // Adjust error checking based on backend response format
                // Assuming backend proxies Bybit response:
                if (data.retCode !== undefined && data.retCode !== 0) {
                    console.warn(`API Error: ${data.retMsg}`);
                    break;
                }

                // If backend returns list directly or wrapped in result
                const list = data.result?.list || data.list || data;

                if (!Array.isArray(list) || list.length === 0) break;

                const chunk = list.map((k: any) => {
                    // Handle array [time, open, ...] or object { time: ..., open: ... }
                    if (Array.isArray(k)) {
                        return {
                            time: parseInt(k[0]),
                            open: parseFloat(k[1]),
                            high: parseFloat(k[2]),
                            low: parseFloat(k[3]),
                            close: parseFloat(k[4]),
                            volume: parseFloat(k[5]),
                            rawTime: parseInt(k[0])
                        }
                    }
                    return { ...k, rawTime: k.timestamp || k.time };
                });

                // Bybit returns Descending time (newest first).
                const validCandles = chunk.filter((c: any) => c.rawTime >= startMs);

                allCandles.push(...validCandles);

                const oldestInChunk = chunk[chunk.length - 1].rawTime;
                if (list.length < LIMIT) break;

                currentEnd = oldestInChunk - 1;

                if (validCandles.length < chunk.length) {
                    break;
                }
            }

            return allCandles
                .sort((a: any, b: any) => a.rawTime - b.rawTime)
                .map((c: any) => ({
                    time: new Date(c.rawTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }), // Simple HH:mm for Chart
                    open: c.open,
                    high: c.high,
                    low: c.low,
                    close: c.close,
                    volume: c.volume,
                    timestamp: c.rawTime
                }));

        } catch (e) {
            console.error("Fetch History Error", e);
            return [];
        }
    }

    public subscribe(symbol: string, callbacks: Subscription): () => void {
        const isNewSymbol = this.activeSymbol !== symbol;
        this.activeSymbol = symbol;
        this.subscribers.push(callbacks);

        if (!this.healthInterval) {
            this.startHealthMonitor();
        }

        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.connect();
        } else if (isNewSymbol) {
            this.sendSubscription(symbol);
        }

        // Immediate status report
        callbacks.onStatus?.(this.ws?.readyState === WebSocket.OPEN ? 'CONNECTED' : 'RECONNECTING');
        callbacks.onHealth?.(this.buildHealth());

        return () => {
            this.subscribers = this.subscribers.filter(s => s !== callbacks);
            if (this.subscribers.length === 0) {
                this.stopHealthMonitor();
            }
        };
    }

    private connect() {
        if (typeof window === 'undefined') return;
        if (this.ws) return;

        this.ws = new WebSocket(WS_URL);
        this.notifyStatus('RECONNECTING');

        this.ws.onopen = () => {
            console.log('Market Data Stream Connected (Bybit V5)');
            this.notifyStatus('CONNECTED');
            this.startPing();
            if (this.activeSymbol) {
                this.sendSubscription(this.activeSymbol);
            }
        };

        this.ws.onmessage = (event) => {
            try {
                this.lastMessageAt = Date.now();
                const msg = JSON.parse(event.data);
                if (msg.op === 'pong') return;
                this.handleMessage(msg);
            } catch (e) {
                console.error('Parse error', e);
            }
        };

        this.ws.onclose = () => {
            console.log('Market Data Stream Closed');
            this.notifyStatus('DISCONNECTED');
            this.stopPing();
            this.ws = null;
            // Auto reconnect
            this.reconnectTimeout = setTimeout(() => this.connect(), 3000);
        };

        this.ws.onerror = (err) => {
            console.error('WebSocket Error: Connection failed or interrupted.');
            this.ws?.close();
        };
    }

    private disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.stopPing();
        this.stopHealthMonitor();
        clearTimeout(this.reconnectTimeout);
        this.notifyStatus('DISCONNECTED');
    }

    private startHealthMonitor() {
        this.healthInterval = setInterval(() => this.emitHealth(), 2000);
    }

    private stopHealthMonitor() {
        clearInterval(this.healthInterval);
        this.healthInterval = null;
    }

    private buildHealth(): MarketDataHealth {
        const now = Date.now();
        const tickerAge = this.lastTickerAt ? now - this.lastTickerAt : Number.POSITIVE_INFINITY;
        const bookAge = this.lastOrderBookAt ? now - this.lastOrderBookAt : Number.POSITIVE_INFINITY;
        const candleAge = this.lastCandleAt ? now - this.lastCandleAt : Number.POSITIVE_INFINITY;
        const isDisconnected = !this.ws || this.ws.readyState !== WebSocket.OPEN;

        let status: MarketDataHealth['status'] = 'OK';
        let reason: string | undefined = undefined;

        if (isDisconnected) {
            status = 'STALE';
            reason = 'ws-disconnected';
        } else if (tickerAge > this.staleThresholdMs) {
            status = 'STALE';
            reason = 'ticker-stale';
        } else if (bookAge > this.staleThresholdMs || candleAge > this.staleThresholdMs) {
            status = 'DEGRADED';
            reason = 'book-or-candle-stale';
        }

        const isStale = status === 'STALE';
        const staleForMs = isStale ? Math.max(tickerAge, bookAge, candleAge) : 0;
        const clockSkewMs = this.lastServerTimestamp ? now - this.lastServerTimestamp : undefined;

        return {
            status,
            isStale,
            lastTickerAt: this.lastTickerAt || undefined,
            lastOrderBookAt: this.lastOrderBookAt || undefined,
            lastCandleAt: this.lastCandleAt || undefined,
            lastMessageAt: this.lastMessageAt || undefined,
            staleForMs,
            clockSkewMs,
            reason
        };
    }

    private emitHealth() {
        const health = this.buildHealth();
        this.subscribers.forEach(s => s.onHealth?.(health));
    }

    private notifyStatus(status: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED') {
        this.subscribers.forEach(s => s.onStatus?.(status));
        this.emitHealth();
    }

    private sendSubscription(symbol: string) {
        const apiSymbol = this.mapSymbol(symbol);

        // Bybit V5 Topics
        const payload = {
            op: 'subscribe',
            args: [
                `kline.1.${apiSymbol}`,
                `orderbook.50.${apiSymbol}`,
                `tickers.${apiSymbol}`
            ]
        };

        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(payload));
        }

        // Reset Orderbook
        this.currentBids.clear();
        this.currentAsks.clear();
    }

    private startPing() {
        this.pingInterval = setInterval(() => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ op: 'ping' }));
            }
        }, 20000);
    }

    private stopPing() {
        clearInterval(this.pingInterval);
    }

    private handleMessage(msg: any) {
        const topic = msg.topic;
        if (!topic) return;

        if (topic.startsWith('kline.1')) {
            this.processCandle(msg.data);
        } else if (topic.startsWith('orderbook')) {
            this.processOrderBook(msg);
        } else if (topic.startsWith('tickers')) {
            this.processTicker(msg.data);
        }
    }

    private processTicker(data: any) {
        const info = data;
        if (info && info.lastPrice) {
            const price = parseFloat(info.lastPrice);
            const serverTimestamp = info.ts || info.time || info.timestamp;
            if (serverTimestamp) {
                this.lastServerTimestamp = parseInt(serverTimestamp);
            }
            this.lastTickerAt = Date.now();
            this.subscribers.forEach(s => s.onTicker(price));
            this.emitHealth();
        }
    }

    private processCandle(data: any[]) {
        if (!data || data.length === 0) return;
        const k = data[0];

        const candle: Candle = {
            time: new Date(k.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }),
            open: parseFloat(k.open),
            high: parseFloat(k.high),
            low: parseFloat(k.low),
            close: parseFloat(k.close),
            volume: parseFloat(k.volume),
            timestamp: k.end ? parseInt(k.end) : (k.start ? parseInt(k.start) : undefined)
        };

        const serverTimestamp = k.end || k.start;
        if (serverTimestamp) {
            this.lastServerTimestamp = parseInt(serverTimestamp);
        }

        this.lastCandleAt = Date.now();
        this.subscribers.forEach(s => s.onCandle(candle));
        if (!k.confirm) {
            this.lastTickerAt = Date.now();
            this.subscribers.forEach(s => s.onTicker(candle.close));
        }
        this.emitHealth();
    }

    private processOrderBook(msg: any) {
        const type = msg.type;
        const data = msg.data;

        const processLevel = (arr: string[], map: Map<string, number>) => {
            const price = arr[0];
            const size = parseFloat(arr[1]);
            if (size === 0) {
                map.delete(price);
            } else {
                map.set(price, size);
            }
        };

        if (type === 'snapshot') {
            this.currentBids.clear();
            this.currentAsks.clear();
            if (data.b) data.b.forEach((item: string[]) => this.currentBids.set(item[0], parseFloat(item[1])));
            if (data.a) data.a.forEach((item: string[]) => this.currentAsks.set(item[0], parseFloat(item[1])));
        } else if (type === 'delta') {
            if (data.b) data.b.forEach((item: string[]) => processLevel(item, this.currentBids));
            if (data.a) data.a.forEach((item: string[]) => processLevel(item, this.currentAsks));
        }

        this.lastOrderBookAt = Date.now();
        this.emitOrderBook();
        this.emitHealth();
    }

    private emitOrderBook() {
        const bids: OrderBookItem[] = Array.from(this.currentBids.entries())
            .map(([p, s]) => ({ price: parseFloat(p), size: s, total: 0, percent: 0 }))
            .sort((a, b) => b.price - a.price);

        const asks: OrderBookItem[] = Array.from(this.currentAsks.entries())
            .map(([p, s]) => ({ price: parseFloat(p), size: s, total: 0, percent: 0 }))
            .sort((a, b) => a.price - b.price);

        const finalBids = bids.slice(0, 20);
        const finalAsks = asks.slice(0, 20);

        let bidTotal = 0;
        finalBids.forEach(b => { bidTotal += b.size; b.total = bidTotal; });

        let askTotal = 0;
        finalAsks.forEach(a => { askTotal += a.size; a.total = askTotal; });

        const maxVol = Math.max(bidTotal, askTotal);
        finalBids.forEach(b => b.percent = maxVol ? (b.total / maxVol) * 100 : 0);
        finalAsks.forEach(a => a.percent = maxVol ? (a.total / maxVol) * 100 : 0);

        this.subscribers.forEach(s => s.onOrderBook({ bids: finalBids, asks: finalAsks }));
    }
}

export const MarketStream = new MarketStreamService();

import { useState, useEffect } from 'react';

export const useMarketStream = (symbol: string) => {
    const [marketData, setMarketData] = useState<any>({
        price: 0,
        candles: [],
        orderBook: { bids: [], asks: [] },
        positions: []
    });
    const [connectionStatus, setConnectionStatus] = useState<string>('CONNECTING');
    const [health, setHealth] = useState<MarketDataHealth | null>(null);

    useEffect(() => {
        const unsub = MarketStream.subscribe(symbol, {
            onTicker: (price) => setMarketData((prev: any) => ({ ...prev, price })),
            onOrderBook: (data) => setMarketData((prev: any) => ({ ...prev, orderBook: data })),
            onCandle: (candle) => setMarketData((prev: any) => ({
                ...prev,
                candles: [...(prev.candles || []).slice(-99), candle]
            })),
            onStatus: (status) => setConnectionStatus(status),
            onHealth: (h) => setHealth(h)
        });

        // Initial fetch
        MarketStream.fetchHistory(symbol).then(candles => {
            setMarketData((prev: any) => ({ ...prev, candles }));
        });

        return () => unsub();
    }, [symbol]);

    return { marketData, connectionStatus, health };
};
