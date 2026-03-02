/**
 * Signal Engine API types and utilities.
 * Connects the frontend to the Confluence Signal Engine backend.
 */

// =============================================================================
// Types
// =============================================================================

export interface SignalAlert {
    exchange: string;
    symbol: string;
    tf: string;
    ts: number;
    candle: {
        o: number;
        h: number;
        l: number;
        c: number;
        v: number;
    };
    score: number;
    side: "BUY" | "SELL" | "HOLD";
    strength: "LOW" | "MEDIUM" | "HIGH";
    reasons: string[];
    gates: GateResult[];
    features: Record<string, number | string | null>;
    idempotency_key: string;
}

export interface GateResult {
    name: string;
    pass: boolean;
    detail: string;
}

export interface Subscription {
    id: number;
    exchange: string;
    symbol: string;
    timeframe: string;
    strategy: string;
    enabled: boolean;
}

export interface SubscriptionCreate {
    exchange: string;
    symbol: string;
    timeframe: string;
    strategy?: string;
    enabled?: boolean;
}

export interface Strategy {
    name: string;
    description?: string;
    buy_threshold: number;
    sell_threshold: number;
    timeframe?: string;
}

export interface SignalEngineHealth {
    status: string;
    subscriptions_active: number;
    websocket_connections: number;
    timestamp: string;
}

// =============================================================================
// API Client
// =============================================================================

const SIGNAL_ENGINE_BASE = process.env.NEXT_PUBLIC_SIGNAL_ENGINE_URL || "http://localhost:8086";

const getHeaders = () => ({
    "Content-Type": "application/json",
});

export const signalEngineApi = {
    // Health
    getHealth: async (): Promise<SignalEngineHealth> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/health`, {
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to get signal engine health");
        return response.json();
    },

    // Signals
    getLatestSignals: async (
        exchange?: string,
        symbol?: string,
        tf?: string
    ): Promise<SignalAlert[]> => {
        let url = `${SIGNAL_ENGINE_BASE}/signals/latest`;
        const params = new URLSearchParams();
        if (exchange) params.append("exchange", exchange);
        if (symbol) params.append("symbol", symbol);
        if (tf) params.append("tf", tf);
        if (params.toString()) url += `?${params.toString()}`;

        const response = await fetch(url, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch latest signals");
        const data = await response.json();
        return Array.isArray(data) ? data : [data];
    },

    getSignalHistory: async (
        limit: number = 50,
        exchange?: string,
        symbol?: string,
        tf?: string
    ): Promise<SignalAlert[]> => {
        let url = `${SIGNAL_ENGINE_BASE}/signals/history`;
        const params = new URLSearchParams();
        params.append("limit", limit.toString());
        if (exchange) params.append("exchange", exchange);
        if (symbol) params.append("symbol", symbol);
        if (tf) params.append("tf", tf);
        url += `?${params.toString()}`;

        const response = await fetch(url, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch signal history");
        return response.json();
    },

    // Subscriptions
    getSubscriptions: async (): Promise<Subscription[]> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/subscriptions`, {
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to fetch subscriptions");
        return response.json();
    },

    createSubscription: async (sub: SubscriptionCreate): Promise<Subscription> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/subscriptions`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify(sub),
        });
        if (!response.ok) throw new Error("Failed to create subscription");
        return response.json();
    },

    deleteSubscription: async (id: number): Promise<void> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/subscriptions/${id}`, {
            method: "DELETE",
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to delete subscription");
    },

    // Strategies
    getStrategies: async (): Promise<Strategy[]> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/strategies`, {
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to fetch strategies");
        return response.json();
    },

    // Control
    startEngine: async (): Promise<{ status: string }> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/start`, {
            method: "POST",
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to start signal engine");
        return response.json();
    },

    stopEngine: async (): Promise<{ status: string }> => {
        const response = await fetch(`${SIGNAL_ENGINE_BASE}/stop`, {
            method: "POST",
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to stop signal engine");
        return response.json();
    },
};

// =============================================================================
// WebSocket Hook
// =============================================================================

export interface UseSignalStreamOptions {
    exchange?: string;
    symbol?: string;
    tf?: string;
    onSignal?: (signal: SignalAlert) => void;
    onError?: (error: Error) => void;
    autoConnect?: boolean;
}

export function createSignalWebSocket(options: UseSignalStreamOptions): {
    connect: () => void;
    disconnect: () => void;
    isConnected: () => boolean;
} {
    let ws: WebSocket | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let connected = false;

    const connect = () => {
        if (ws && ws.readyState === WebSocket.OPEN) return;

        const params = new URLSearchParams();
        if (options.exchange) params.append("exchange", options.exchange);
        if (options.symbol) params.append("symbol", options.symbol);
        if (options.tf) params.append("tf", options.tf);

        const wsUrl = `${SIGNAL_ENGINE_BASE.replace("http", "ws")}/ws/stream${params.toString() ? `?${params.toString()}` : ""
            }`;

        try {
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                connected = true;
                console.log("[SignalStream] Connected");
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === "connected" || data.type === "heartbeat") {
                        return;
                    }
                    options.onSignal?.(data as SignalAlert);
                } catch (e) {
                    console.error("[SignalStream] Parse error:", e);
                }
            };

            ws.onerror = (event) => {
                console.error("[SignalStream] Error:", event);
                options.onError?.(new Error("WebSocket error"));
            };

            ws.onclose = () => {
                connected = false;
                console.log("[SignalStream] Disconnected, reconnecting in 5s...");
                reconnectTimeout = setTimeout(connect, 5000);
            };
        } catch (e) {
            options.onError?.(e as Error);
        }
    };

    const disconnect = () => {
        if (reconnectTimeout) {
            clearTimeout(reconnectTimeout);
            reconnectTimeout = null;
        }
        if (ws) {
            ws.close();
            ws = null;
        }
        connected = false;
    };

    const isConnected = () => connected;

    if (options.autoConnect) {
        connect();
    }

    return { connect, disconnect, isConnected };
}

// =============================================================================
// Utility Functions
// =============================================================================

export function formatTimestamp(ts: number): string {
    return new Date(ts).toLocaleString();
}

export function getStrengthColor(strength: string): string {
    switch (strength) {
        case "HIGH":
            return "text-green-400";
        case "MEDIUM":
            return "text-yellow-400";
        case "LOW":
            return "text-gray-400";
        default:
            return "text-gray-500";
    }
}

export function getSideColor(side: string): string {
    switch (side) {
        case "BUY":
            return "text-trade-long";
        case "SELL":
            return "text-trade-short";
        default:
            return "text-gray-500";
    }
}

export function getSideBgColor(side: string): string {
    switch (side) {
        case "BUY":
            return "bg-green-500/20 border-green-500/30";
        case "SELL":
            return "bg-red-500/20 border-red-500/30";
        default:
            return "bg-gray-500/20 border-gray-500/30";
    }
}
