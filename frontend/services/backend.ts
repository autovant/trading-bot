import { Order, BackendOrderUpdate, BackendSignal } from "@/types";

const BACKEND_URL = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

export const backendApi = {
    async placeOrder(order: Order): Promise<{ success: boolean; orderId?: string; error?: string }> {
        try {
            const response = await fetch(`${BACKEND_URL}/api/orders`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    clientOrderId: order.id,
                    idempotencyKey: order.idempotencyKey || order.id,
                    symbol: order.symbol,
                    side: order.side,
                    size: order.size,
                    price: order.price,
                    type: order.type
                })
            });
            return await response.json();
        } catch (e) {
            console.error("Backend API Error", e);
            return { success: false, error: "Network Error" };
        }
    },

    async cancelOrder(orderId: string, symbol: string): Promise<{ success: boolean; error?: string }> {
        try {
            const response = await fetch(`${BACKEND_URL}/api/orders/${orderId}?symbol=${symbol}`, {
                method: 'DELETE'
            });
            return await response.json();
        } catch (e) {
            console.error("Backend Cancel Error", e);
            return { success: false, error: "Network Error" };
        }
    },

    async getRiskConfig() {
        const res = await fetch(`${BACKEND_URL}/api/risk`);
        return res.json();
    },

    async getRiskMetrics() {
        // Fallback or implement in python
        return {};
    },

    async updateRiskConfig(config: any) {
        const res = await fetch(`${BACKEND_URL}/api/risk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        return res.json();
    },

    async getOrders() {
        const res = await fetch(`${BACKEND_URL}/api/orders`);
        return res.json();
    },

    async getJournal(orderId?: string) {
        // Optional
        return [];
    }
};

/**
 * WebSocket stream for real-time order updates
 */
class BackendStream {
    private ws: WebSocket | null = null;
    private listeners: ((data: any) => void)[] = [];
    private orderUpdateListeners: ((update: BackendOrderUpdate) => void)[] = [];
    private signalListeners: ((signal: BackendSignal) => void)[] = [];
    private lastSequences = new Map<string, number>();
    private reconnectAttempt = 0;
    private heartbeatTimeout: NodeJS.Timeout | null = null;

    connect() {
        if (typeof window === 'undefined') return; // Server-side check
        if (this.ws?.readyState === WebSocket.OPEN) return;

        this.ws = new WebSocket(WS_URL);

        this.ws.onopen = () => {
            console.log('[BackendStream] Connected');
            this.reconnectAttempt = 0;
            this.startHeartbeatMonitor();
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Generic listeners
                this.listeners.forEach(l => l(data));

                // Handle specific message types
                switch (data.type) {
                    case 'ORDER_UPDATE':
                        this.handleOrderUpdate(data.data);
                        break;
                    case 'SIGNAL':
                        this.signalListeners.forEach(l => l(data.data));
                        break;
                    case 'INFO':
                        this.ws?.send(JSON.stringify({ type: 'PONG' }));
                        this.resetHeartbeatMonitor();
                        break;
                    case 'HEARTBEAT_ACK':
                        this.resetHeartbeatMonitor();
                        break;
                }
            } catch (e) {
                console.error("WS Parse Error", e);
            }
        };

        this.ws.onclose = () => {
            console.log('[BackendStream] Disconnected');
            this.stopHeartbeatMonitor();
            this.scheduleReconnect();
        };

        this.ws.onerror = (err) => {
            console.error('[BackendStream] Error:', err);
        };
    }

    private handleOrderUpdate(update: BackendOrderUpdate) {
        const lastSeq = this.lastSequences.get(update.orderId) || 0;
        // Simple dedupe
        if (update.sequence <= lastSeq && !update.isReplay) {
            return;
        }
        this.lastSequences.set(update.orderId, update.sequence);
        this.orderUpdateListeners.forEach(l => l(update));
    }

    private scheduleReconnect() {
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempt), 30000);
        this.reconnectAttempt++;
        setTimeout(() => this.connect(), delay);
    }

    private startHeartbeatMonitor() {
        this.heartbeatTimeout = setTimeout(() => {
            // console.warn('[BackendStream] Heartbeat timeout');
            // Check connection?
        }, 60000);
    }

    private resetHeartbeatMonitor() {
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
        }
        this.startHeartbeatMonitor();
    }

    private stopHeartbeatMonitor() {
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
        }
    }

    subscribe(cb: (data: any) => void) {
        this.listeners.push(cb);
        return () => {
            this.listeners = this.listeners.filter(l => l !== cb);
        };
    }

    onOrderUpdate(cb: (update: BackendOrderUpdate) => void) {
        this.orderUpdateListeners.push(cb);
        return () => {
            this.orderUpdateListeners = this.orderUpdateListeners.filter(l => l !== cb);
        };
    }

    onSignal(cb: (signal: BackendSignal) => void) {
        this.signalListeners.push(cb);
        return () => {
            this.signalListeners = this.signalListeners.filter(l => l !== cb);
        };
    }
}

export const backendStream = new BackendStream();
// Auto connect in browser
if (typeof window !== 'undefined') {
    backendStream.connect();
}
