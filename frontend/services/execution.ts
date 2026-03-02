
import { ExchangeId, Order, OrderStatus, OrderType, Side, ExecutionUpdate, MarketSnapshot } from "@/types";
import { SecureStorage } from "./secureStorage";
import { backendApi, backendStream } from "./backend";
import { ExecutionJournal } from "./executionJournal";
import { OrderIdempotency } from "./orderIdempotency";

/**
 * Institutional Execution Pipeline Service
 * 
 * Features:
 * 1. Event-Driven Architecture (Sub/Pub)
 * 2. Internal Order Queue for Rate Limiting
 * 3. Mock Request Signing & Validation
 * 4. Circuit Breaker for Reliability
 * 5. Latency Simulation
 */

type ExecutionListener = (update: ExecutionUpdate) => void;

interface QueueItem {
    order: Order;
    snapshot: MarketSnapshot;
    attempts: number;
}

const TERMINAL_STATUSES = new Set<OrderStatus>([
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED
]);

class ExecutionPipeline {
    private listeners: ExecutionListener[] = [];
    private queue: QueueItem[] = [];
    private isProcessing = false;
    private submittedOrderKeys = new Set<string>();
    private queuedOrderKeys = new Set<string>();
    private cancelledOrderIds = new Set<string>();
    private orderSequences = new Map<string, number>();
    private lastUpdates = new Map<string, ExecutionUpdate>();
    private lastMarketSnapshot: MarketSnapshot | null = null;

    private pendingTimeoutMs = 15000;
    private maxPendingAgeMs = 120000;
    private maxClockSkewMs = 2 * 60 * 1000;
    private maxSnapshotAgeMs = 15000;

    private rateLimiter = {
        windowMs: 1000,
        maxRequests: 5,
        timestamps: [] as number[]
    };

    // Circuit Breaker State
    private breaker = {
        failures: 0,
        isOpen: false,
        nextAttempt: 0,
        threshold: 3,
        timeout: 30000
    };

    constructor() {
        // Start processing loop
        if (typeof window !== 'undefined') {
            setInterval(() => this.processQueue(), 500);
        }

        // Subscribe to Backend Updates
        backendStream.subscribe((data: any) => {
            if (data.type === 'ORDER_UPDATE') {
                const orderId = data.orderId;
                if (!orderId) return;
                const sequence = this.nextSequence(orderId);
                this.publish({
                    orderId,
                    status: data.status,
                    timestamp: Date.now(),
                    message: data.message || "Update from Backend",
                    eventId: `evt_bk_${orderId}_${sequence}`,
                    sequence,
                    filledSize: data.filledSize,
                    remainingSize: data.remainingSize,
                    filledPrice: data.filledPrice,
                    avgFillPrice: data.avgFillPrice
                });
            }
        });
    }

    // --- Public API ---

    public subscribe(listener: ExecutionListener): () => void {
        this.listeners.push(listener);
        return () => {
            this.listeners = this.listeners.filter(l => l !== listener);
        };
    }

    public hydrate(orders: Order[]): void {
        OrderIdempotency.hydrate(orders);
        orders.forEach(order => {
            const key = this.getIdempotencyKey(order);
            this.submittedOrderKeys.add(key);
            const existingSeq = this.orderSequences.get(order.id) || 0;
            const journalSeq = ExecutionJournal.getLatestSequence(order.id);
            const orderSeq = order.updateSequence ?? 0;
            this.orderSequences.set(order.id, Math.max(existingSeq, journalSeq, orderSeq));

            if (order.status === OrderStatus.CANCELLED || order.status === OrderStatus.REJECTED) {
                this.cancelledOrderIds.add(order.id);
            }
        });
    }

    public submitOrder(order: Order, snapshot: MarketSnapshot): void {
        const key = this.getIdempotencyKey(order);
        if (this.submittedOrderKeys.has(key) || OrderIdempotency.has(key)) {
            return;
        }

        this.submittedOrderKeys.add(key);
        OrderIdempotency.record({
            key,
            orderId: order.id,
            createdAt: order.timestamp,
            source: order.isSimulation ? 'paper' : 'live'
        });
        this.lastMarketSnapshot = snapshot;

        // 1. Immediate Validation
        if (!order.symbol || order.size <= 0) {
            this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                message: "Invalid order parameters"
            }));
            return;
        }

        if (snapshot.symbol && snapshot.symbol !== order.symbol) {
            this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                message: "Market snapshot symbol mismatch"
            }));
            return;
        }

        if (!this.isSnapshotUsable(snapshot)) {
            this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                message: "Market data stale or unavailable"
            }));
            return;
        }

        if (!this.isClockSkewAcceptable(order, snapshot)) {
            this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                message: "Clock drift exceeds safety threshold"
            }));
            return;
        }

        if (!order.isSimulation) {
            // Forward to Backend Exec Service
            backendApi.placeOrder(order).then(res => {
                if (res.success) {
                    this.publish(this.buildUpdate(order, OrderStatus.PENDING, {
                        message: "Sent to Execution Backend"
                    }));
                } else {
                    this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                        message: res.error || "Backend-Rejected"
                    }));
                }
            });
            return;
        }

        // 2. Add to Queue
        this.queueOrder(order, snapshot, "Order Queued");
    }

    public reconcile(orders: Order[], snapshot: MarketSnapshot): void {
        this.lastMarketSnapshot = snapshot;
        const now = Date.now();

        orders.forEach(order => {
            if (snapshot.symbol && order.symbol !== snapshot.symbol) {
                return;
            }

            if (TERMINAL_STATUSES.has(order.status)) {
                return;
            }

            if (this.cancelledOrderIds.has(order.id)) {
                return;
            }

            const key = this.getIdempotencyKey(order);
            if (!this.submittedOrderKeys.has(key)) {
                this.submittedOrderKeys.add(key);
            }
            if (order.updateSequence !== undefined) {
                const existingSeq = this.orderSequences.get(order.id) || 0;
                if (order.updateSequence > existingSeq) {
                    this.orderSequences.set(order.id, order.updateSequence);
                }
            }

            const filledSize = order.filledSize || 0;
            const remainingSize = Math.max(order.size - filledSize, 0);

            if (remainingSize <= 0 && order.status !== OrderStatus.FILLED) {
                this.publish(this.buildUpdate(order, OrderStatus.FILLED, {
                    filledSize: order.size,
                    remainingSize: 0,
                    avgFillPrice: order.avgFillPrice,
                    message: "Reconciled full fill"
                }));
                return;
            }

            if (order.status === OrderStatus.PENDING) {
                const lastUpdate = order.lastUpdate || order.timestamp;
                const age = now - lastUpdate;
                if (age > this.maxPendingAgeMs) {
                    this.publish(this.buildUpdate(order, OrderStatus.REJECTED, {
                        message: "Order expired during recovery",
                        retriable: false
                    }));
                    return;
                }

                if (age > this.pendingTimeoutMs) {
                    if (order.isSimulation && this.isSnapshotUsable(snapshot)) {
                        this.queueOrder(order, snapshot, "Requeued after pending timeout");
                    }
                }
            }

            if (order.status === OrderStatus.OPEN || order.status === OrderStatus.PARTIALLY_FILLED) {
                this.evaluateOpenOrder(order, snapshot);
            }
        });
    }

    public cancelOrder(orderId: string, reason = "Cancelled by user"): void {
        const lastUpdate = this.lastUpdates.get(orderId);
        if (lastUpdate && TERMINAL_STATUSES.has(lastUpdate.status)) {
            return;
        }

        this.cancelledOrderIds.add(orderId);
        this.queue.forEach(item => {
            if (item.order.id === orderId) {
                this.queuedOrderKeys.delete(this.getIdempotencyKey(item.order));
            }
        });
        this.queue = this.queue.filter(item => item.order.id !== orderId);

        const sequence = this.nextSequence(orderId);
        const update: ExecutionUpdate = {
            orderId,
            status: OrderStatus.CANCELLED,
            timestamp: Date.now(),
            message: reason,
            eventId: `evt_${orderId}_${sequence}`,
            sequence
        };

        this.publish(update);
    }

    public async testConnection(exchangeId: ExchangeId): Promise<boolean> {
        const creds = SecureStorage.getCredentials(exchangeId);
        if (!creds) return false;
        await this.delay(400);
        return Math.random() > 0.1;
    }

    // --- Internal Pipeline ---

    private publish(update: ExecutionUpdate) {
        this.lastUpdates.set(update.orderId, update);
        this.listeners.forEach(l => l(update));
    }

    private getIdempotencyKey(order: Order): string {
        return `${order.exchange}:${order.idempotencyKey || order.id}`;
    }

    private buildFallbackSnapshot(order: Order): MarketSnapshot {
        const ageMs = Math.abs(Date.now() - order.timestamp);
        const isStale = ageMs > this.maxSnapshotAgeMs;
        return {
            price: order.price || order.triggerPrice || 0,
            timestamp: order.timestamp,
            isStale,
            staleForMs: isStale ? ageMs : 0,
            source: 'manual',
            symbol: order.symbol
        };
    }

    private isSnapshotUsable(snapshot: MarketSnapshot): boolean {
        if (!snapshot || snapshot.price <= 0 || snapshot.isStale) {
            return false;
        }

        if (snapshot.clockSkewMs !== undefined && Math.abs(snapshot.clockSkewMs) > this.maxClockSkewMs) {
            return false;
        }

        const ageMs = Math.abs(Date.now() - snapshot.timestamp);
        if (!Number.isFinite(ageMs) || ageMs > this.maxSnapshotAgeMs) {
            return false;
        }

        return true;
    }

    private isClockSkewAcceptable(order: Order, snapshot: MarketSnapshot): boolean {
        if (snapshot.clockSkewMs !== undefined && Math.abs(snapshot.clockSkewMs) > this.maxClockSkewMs) {
            return false;
        }

        return Math.abs(Date.now() - order.timestamp) <= this.maxClockSkewMs;
    }

    private queueOrder(order: Order, snapshot: MarketSnapshot, message: string) {
        const key = this.getIdempotencyKey(order);
        if (this.queuedOrderKeys.has(key)) {
            return;
        }

        this.queuedOrderKeys.add(key);
        this.queue.push({ order, snapshot, attempts: 0 });
        this.publish(this.buildUpdate(order, OrderStatus.PENDING, {
            message
        }));
    }

    private nextSequence(orderId: string): number {
        const current = this.orderSequences.get(orderId) || 0;
        const next = current + 1;
        this.orderSequences.set(orderId, next);
        return next;
    }

    private buildUpdate(order: Order, status: OrderStatus, details: Partial<ExecutionUpdate>): ExecutionUpdate {
        const filledSize = details.filledSize ?? order.filledSize ?? 0;
        const remainingSize = details.remainingSize ?? Math.max(order.size - filledSize, 0);
        const sequence = this.nextSequence(order.id);

        return {
            orderId: order.id,
            status,
            filledPrice: details.filledPrice,
            filledSize,
            timestamp: details.timestamp || Date.now(),
            message: details.message,
            eventId: `evt_${order.id}_${sequence}`,
            sequence,
            remainingSize,
            avgFillPrice: details.avgFillPrice ?? order.avgFillPrice,
            retriable: details.retriable
        };
    }

    private isRateLimited(): boolean {
        const now = Date.now();
        this.rateLimiter.timestamps = this.rateLimiter.timestamps.filter(ts => now - ts < this.rateLimiter.windowMs);
        if (this.rateLimiter.timestamps.length >= this.rateLimiter.maxRequests) {
            return true;
        }

        this.rateLimiter.timestamps.push(now);
        return false;
    }

    private getEffectiveSnapshot(snapshot: MarketSnapshot): MarketSnapshot {
        if (this.lastMarketSnapshot) {
            const sameSymbol = !snapshot.symbol
                || !this.lastMarketSnapshot.symbol
                || this.lastMarketSnapshot.symbol === snapshot.symbol;
            if (sameSymbol && this.lastMarketSnapshot.timestamp >= snapshot.timestamp) {
                return this.lastMarketSnapshot;
            }
        }

        return snapshot;
    }

    private async processQueue() {
        if (this.isProcessing || this.queue.length === 0) return;

        // Circuit Breaker Check
        if (this.breaker.isOpen) {
            if (Date.now() < this.breaker.nextAttempt) return;
            this.breaker.isOpen = false; // Half-open
        }

        this.isProcessing = true;
        const item = this.queue.shift();

        if (item) {
            try {
                await this.executeItem(item);
                this.breaker.failures = 0; // Reset on success
            } catch (error: any) {
                // Retry Logic
                const retriable = error?.retriable !== false;
                if (retriable && item.attempts < 3) {
                    item.attempts++;
                    // Exponential backoff
                    setTimeout(() => this.queue.unshift(item), Math.pow(2, item.attempts) * 1000);
                } else {
                    this.breaker.failures++;
                    if (this.breaker.failures >= this.breaker.threshold) {
                        this.breaker.isOpen = true;
                        this.breaker.nextAttempt = Date.now() + this.breaker.timeout;
                    }
                    const update = this.buildUpdate(item.order, OrderStatus.REJECTED, {
                        message: `Execution failed: ${error?.message || 'Unknown error'}`,
                        retriable: false
                    });
                    this.publish(update);
                    this.queuedOrderKeys.delete(this.getIdempotencyKey(item.order));
                }
            }
        }

        this.isProcessing = false;
    }

    private async executeItem(item: QueueItem) {
        const { order } = item;
        const exchangeId = order.exchange;
        const snapshot = this.getEffectiveSnapshot(item.snapshot);

        if (this.cancelledOrderIds.has(order.id)) {
            this.queuedOrderKeys.delete(this.getIdempotencyKey(order));
            return;
        }

        if (!this.isSnapshotUsable(snapshot)) {
            const error: any = new Error("Market data stale or unavailable");
            error.retriable = true;
            throw error;
        }

        if (this.isRateLimited()) {
            const error: any = new Error("Rate limit exceeded");
            error.retriable = true;
            throw error;
        }

        if (!order.isSimulation) {
            const creds = SecureStorage.getCredentials(exchangeId);
            if (!creds) {
                const error: any = new Error(`API Credentials missing for ${exchangeId}`);
                error.retriable = false;
                throw error;
            }

            this.publish(this.buildUpdate(order, OrderStatus.PENDING, {
                message: `Signing Request for ${exchangeId}...`
            }));

            await this.delay(150);
            const signature = this.mockSign(creds.apiSecret, order);
            void signature;

            this.publish(this.buildUpdate(order, OrderStatus.PENDING, {
                message: `Sending to ${exchangeId} Gateway...`
            }));
        }

        const latency = 100 + Math.random() * 600;
        await this.delay(latency);
        if (latency > 700) {
            const error: any = new Error("Gateway timeout");
            error.retriable = true;
            throw error;
        }

        const isRejected = Math.random() > 0.98;
        if (isRejected) {
            const error: any = new Error("Exchange rejected order: Post-only invalid");
            error.retriable = false;
            throw error;
        }

        const fillDecision = this.computeFillDecision(order, snapshot);
        if (!fillDecision) {
            this.publish(this.buildUpdate(order, OrderStatus.OPEN, {
                message: `Open on ${exchangeId} Order Book`
            }));
            this.queuedOrderKeys.delete(this.getIdempotencyKey(order));
            return;
        }

        const prevFilled = order.filledSize || 0;
        const filledSize = prevFilled + fillDecision.fillSize;
        const avgFillPrice = this.calculateAvgFillPrice(order.avgFillPrice, prevFilled, fillDecision.fillPrice, fillDecision.fillSize);
        const remainingSize = Math.max(order.size - filledSize, 0);
        const status = remainingSize <= 0 ? OrderStatus.FILLED : OrderStatus.PARTIALLY_FILLED;

        this.publish(this.buildUpdate(order, status, {
            filledPrice: fillDecision.fillPrice,
            filledSize,
            remainingSize,
            avgFillPrice,
            message: status === OrderStatus.FILLED
                ? `Filled on ${exchangeId} @ ${fillDecision.fillPrice.toFixed(1)}`
                : `Partial fill on ${exchangeId} @ ${fillDecision.fillPrice.toFixed(1)}`
        }));

        this.queuedOrderKeys.delete(this.getIdempotencyKey(order));
    }

    private evaluateOpenOrder(order: Order, snapshot: MarketSnapshot) {
        const lastUpdate = this.lastUpdates.get(order.id);
        if (lastUpdate && Date.now() - lastUpdate.timestamp < 750) {
            return;
        }

        const fillDecision = this.computeFillDecision(order, snapshot);
        if (!fillDecision) {
            return;
        }

        const prevFilled = order.filledSize || 0;
        const filledSize = prevFilled + fillDecision.fillSize;
        const avgFillPrice = this.calculateAvgFillPrice(order.avgFillPrice, prevFilled, fillDecision.fillPrice, fillDecision.fillSize);
        const remainingSize = Math.max(order.size - filledSize, 0);
        const status = remainingSize <= 0 ? OrderStatus.FILLED : OrderStatus.PARTIALLY_FILLED;

        this.publish(this.buildUpdate(order, status, {
            filledPrice: fillDecision.fillPrice,
            filledSize,
            remainingSize,
            avgFillPrice,
            message: status === OrderStatus.FILLED
                ? `Filled ${order.type} Order on ${order.exchange}`
                : `Partial fill ${order.type} Order on ${order.exchange}`
        }));
    }

    private computeFillDecision(order: Order, snapshot: MarketSnapshot): { fillPrice: number; fillSize: number } | null {
        if (!this.isSnapshotUsable(snapshot)) {
            return null;
        }

        const remaining = Math.max(order.size - (order.filledSize || 0), 0);
        if (remaining <= 0) {
            return null;
        }

        const currentPrice = snapshot.price;
        const bestBid = snapshot.bestBid || currentPrice;
        const bestAsk = snapshot.bestAsk || currentPrice;
        let fillPrice = currentPrice;
        let isMatch = false;

        if (order.type === OrderType.STOP && order.triggerPrice) {
            const triggered = (order.side === Side.BUY && currentPrice >= order.triggerPrice) ||
                (order.side === Side.SELL && currentPrice <= order.triggerPrice);
            if (!triggered) {
                return null;
            }
            isMatch = true;
            fillPrice = order.side === Side.BUY ? bestAsk : bestBid;
        } else if (order.type === OrderType.MARKET) {
            isMatch = true;
            fillPrice = order.side === Side.BUY ? bestAsk : bestBid;
        } else if (order.type === OrderType.LIMIT) {
            if (order.side === Side.BUY && bestAsk <= order.price) {
                isMatch = true;
                fillPrice = order.price;
            } else if (order.side === Side.SELL && bestBid >= order.price) {
                isMatch = true;
                fillPrice = order.price;
            }
        }

        if (!isMatch) {
            return null;
        }

        const fillSize = this.simulateFillSize(remaining);
        return { fillPrice, fillSize };
    }

    private simulateFillSize(remaining: number): number {
        if (remaining <= 0) return 0;
        const partialChance = 0.35;
        if (Math.random() > partialChance) {
            return remaining;
        }

        const ratio = 0.2 + Math.random() * 0.6;
        const size = remaining * ratio;
        return Math.max(Math.min(size, remaining), Math.min(remaining, 0.0001));
    }

    private calculateAvgFillPrice(prevAvg: number | undefined, prevFilled: number, fillPrice: number, fillSize: number): number {
        const nextFilled = prevFilled + fillSize;
        if (nextFilled <= 0) return fillPrice;
        const prevValue = (prevAvg ?? fillPrice) * prevFilled;
        return (prevValue + fillPrice * fillSize) / nextFilled;
    }

    private mockSign(secret: string, order: Order): string {
        // Simulation of HMAC-SHA256
        const payload = `${order.symbol}${order.side}${order.size}${order.timestamp}`;
        return `SIGN_${payload}_${secret.substring(0, 4)}`;
    }

    private delay(ms: number) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

}

// Singleton Instance
export const ExecutionService = new ExecutionPipeline();
