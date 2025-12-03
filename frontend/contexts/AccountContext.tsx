"use client";

import React, { createContext, useContext, useEffect, useState, useRef, ReactNode } from 'react';
import { ExecutionReport, Position, Order, AccountSummary } from '@/types';
import { useWebSocket } from '@/hooks/useWebSocket';

interface AccountContextType {
    positions: Position[];
    openOrders: Order[];
    summary: AccountSummary;
    isConnected: boolean;
    refreshPositions: () => Promise<void>;
    executeOrder: (order: { symbol: string, side: 'buy' | 'sell', type: 'market' | 'limit', quantity: number, price?: number }) => Promise<void>;
}

const AccountContext = createContext<AccountContextType | undefined>(undefined);

export const AccountDataProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [positions, setPositions] = useState<Position[]>([]);
    const [openOrders, setOpenOrders] = useState<Order[]>([]);
    const [summary, setSummary] = useState<AccountSummary>({
        equity: 10000, // Mock initial
        balance: 10000,
        unrealized_pnl: 0,
        margin_used: 0,
        free_margin: 10000,
        leverage: 10
    });

    // Fetch initial positions via HTTP
    const fetchPositions = React.useCallback(async () => {
        try {
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/positions`);
            if (res.ok) {
                const data = await res.json();
                // Map API response to Position type if needed
                // Assuming API returns list of positions compatible with our type or we map it
                const mappedPositions: Position[] = data.map((p: any) => ({
                    symbol: p.symbol,
                    side: p.side,
                    size: p.size,
                    entry_price: p.entry_price,
                    mark_price: p.mark_price,
                    unrealized_pnl: p.unrealized_pnl,
                    percentage: p.percentage,
                    mode: p.mode
                }));
                setPositions(mappedPositions);
            }
        } catch (e) {
            console.error("Failed to fetch positions:", e);
        }
    }, []);

    const handleExecution = React.useCallback((exec: ExecutionReport) => {
        // Simple logic to update local state based on execution
        // In a real app, we might just re-fetch positions or apply delta
        // For now, let's trigger a refresh of positions
        if (exec.executed) {
            fetchPositions();
            // Remove from open orders
            setOpenOrders(prev => prev.filter(o => o.order_id !== exec.order_id));
        } else {
            // New order or update
            setOpenOrders(prev => {
                const exists = prev.find(o => o.order_id === exec.order_id);
                if (exists) return prev; // Update logic could go here
                return [...prev, {
                    order_id: exec.order_id,
                    symbol: exec.symbol,
                    side: exec.side as 'buy' | 'sell',
                    type: 'market', // Default or inferred
                    quantity: exec.quantity,
                    price: exec.price,
                    status: 'new',
                    timestamp: exec.timestamp
                }];
            });
        }
    }, [fetchPositions]);

    const { isConnected } = useWebSocket<ExecutionReport>(`${process.env.NEXT_PUBLIC_WS_BASE_URL}/ws/executions`, {
        onOpen: fetchPositions,
        onMessage: handleExecution,
        validator: (data: unknown): data is ExecutionReport => {
            return typeof data === 'object' && data !== null && 'order_id' in data;
        }
    });

    // Calculate summary based on positions
    useEffect(() => {
        const upnl = positions.reduce((acc, p) => acc + p.unrealized_pnl, 0);
        setSummary(prev => ({
            ...prev,
            unrealized_pnl: upnl,
            equity: prev.balance + upnl,
            free_margin: prev.balance + upnl - prev.margin_used // Simplified
        }));
    }, [positions]);

    const executeOrder = React.useCallback(async (order: { symbol: string, side: 'buy' | 'sell', type: 'market' | 'limit', quantity: number, price?: number }) => {
        console.log("Executing order:", order);
        try {
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/orders`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(order)
            });
            if (!res.ok) throw new Error('Order execution failed');
        } catch (e) {
            console.error("Order execution error:", e);
            throw e;
        }
    }, []);

    const value = React.useMemo(() => ({
        positions,
        openOrders,
        summary,
        isConnected,
        refreshPositions: fetchPositions,
        executeOrder
    }), [positions, openOrders, summary, isConnected, fetchPositions, executeOrder]);

    return (
        <AccountContext.Provider value={value}>
            {children}
        </AccountContext.Provider>
    );
};

export const useAccount = () => {
    const context = useContext(AccountContext);
    if (context === undefined) {
        throw new Error('useAccount must be used within a AccountDataProvider');
    }
    return context;
};
