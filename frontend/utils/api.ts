const API_BASE = "http://localhost:8000";

export interface OrderParams {
    symbol: string;
    side: "buy" | "sell";
    type: "limit" | "market";
    quantity: number;
    price?: number;
}

export const api = {
    placeOrder: async (order: OrderParams) => {
        const response = await fetch(`${API_BASE}/api/orders`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
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
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ symbol }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Failed to close position");
        }

        return response.json();
    },

    startBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/start`, { method: "POST" });
        if (!response.ok) throw new Error("Failed to start bot");
        return response.json();
    },

    stopBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/stop`, { method: "POST" });
        if (!response.ok) throw new Error("Failed to stop bot");
        return response.json();
    },

    haltBot: async () => {
        const response = await fetch(`${API_BASE}/api/bot/halt`, { method: "POST" });
        if (!response.ok) throw new Error("Failed to halt bot");
        return response.json();
    },

    getBotStatus: async () => {
        const response = await fetch(`${API_BASE}/api/bot/status`);
        if (!response.ok) throw new Error("Failed to get bot status");
        return response.json();
    },

    getStrategies: async () => {
        const response = await fetch(`${API_BASE}/api/strategies`);
        if (!response.ok) throw new Error("Failed to fetch strategies");
        return response.json();
    },

    saveStrategy: async (strategy: any) => {
        const response = await fetch(`${API_BASE}/api/strategies`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(strategy),
        });
        if (!response.ok) throw new Error("Failed to save strategy");
        return response.json();
    },

    activateStrategy: async (name: string) => {
        const response = await fetch(`${API_BASE}/api/strategies/${name}/activate`, {
            method: "POST",
        });
        if (!response.ok) throw new Error("Failed to activate strategy");
        return response.json();
    },

    deleteStrategy: async (name: string) => {
        const response = await fetch(`${API_BASE}/api/strategies/${name}`, {
            method: "DELETE",
        });
        if (!response.ok) throw new Error("Failed to delete strategy");
        return response.json();
    },

    getKlines: async (symbol: string, interval: string = "15m", limit: number = 100) => {
        const response = await fetch(`${API_BASE}/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`);
        if (!response.ok) throw new Error("Failed to fetch klines");
        return response.json();
    },
};
