const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "default-insecure-key";

export interface OrderParams {
    symbol: string;
    side: "buy" | "sell";
    type: "limit" | "market";
    quantity: number;
    price?: number;
}

const getHeaders = () => ({
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY,
});

export const api = {
    placeOrder: async (order: OrderParams) => {
        const response = await fetch(`${API_BASE}/api/orders`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify(order),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Failed to place order");
        }

        return response.json();
    },

    cancelOrder: async (orderId: string, symbol: string) => {
        const response = await fetch(`${API_BASE}/api/orders/${orderId}?symbol=${symbol}`, {
            method: "DELETE",
            headers: getHeaders(),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Failed to cancel order");
        }

        return response.json();
    },

    closePosition: async (symbol: string) => {
        const response = await fetch(`${API_BASE}/api/positions/close`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify({ symbol }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Failed to close position");
        }

        return response.json();
    },

    startBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/start`, {
            method: "POST",
            headers: getHeaders()
        });
        if (!response.ok) throw new Error("Failed to start bot");
        return response.json();
    },

    stopBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/stop`, {
            method: "POST",
            headers: getHeaders()
        });
        if (!response.ok) throw new Error("Failed to stop bot");
        return response.json();
    },

    haltBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/halt`, {
            method: "POST",
            headers: getHeaders()
        });
        if (!response.ok) throw new Error("Failed to halt bot");
        return response.json();
    },

    getBotStatus: async () => {
        const response = await fetch(`${API_BASE}/api/bot/status`, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to get bot status");
        return response.json();
    },

    getStrategies: async () => {
        const response = await fetch(`${API_BASE}/api/strategies`, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch strategies");
        return response.json();
    },

    saveStrategy: async (strategy: { name: string; config: Record<string, unknown> }) => {
        const response = await fetch(`${API_BASE}/api/strategies`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify(strategy),
        });
        if (!response.ok) throw new Error("Failed to save strategy");
        return response.json();
    },

    activateStrategy: async (name: string) => {
        const response = await fetch(`${API_BASE}/api/strategies/${name}/activate`, {
            method: "POST",
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to activate strategy");
        return response.json();
    },

    deleteStrategy: async (name: string) => {
        const response = await fetch(`${API_BASE}/api/strategies/${name}`, {
            method: "DELETE",
            headers: getHeaders(),
        });
        if (!response.ok) throw new Error("Failed to delete strategy");
        return response.json();
    },

    getKlines: async (symbol: string, interval: string = "15m", limit: number = 100) => {
        const response = await fetch(`${API_BASE}/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch klines");
        return response.json();
    },

    getAccountSummary: async () => {
        const response = await fetch(`${API_BASE}/api/account`, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch account summary");
        return response.json();
    },

    getSystemLogs: async (limit: number = 50) => {
        const response = await fetch(`${API_BASE}/api/logs?limit=${limit}`, { headers: getHeaders() });
        if (!response.ok) throw new Error("Failed to fetch system logs");
        return response.json();
    },
};
