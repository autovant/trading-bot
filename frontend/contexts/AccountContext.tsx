"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { ExecutionReport, Position, Order, AccountSummary } from '@/types';
import { useWebSocket } from '@/hooks/useWebSocket';
import { api } from '@/utils/api';

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
        used_margin: 0,
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
                const mappedPositions: Position[] = data.map((p: { symbol: string; side: string; size: number; entry_price: number; mark_price: number; unrealized_pnl: number; percentage: number; mode: string }) => ({
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

    // Poll Account Summary
    useEffect(() => {
        const fetchAccount = async () => {
            try {
                const data = await api.getAccountSummary(); // You need to import api if not imported, or pass it in
                setSummary(data);
            } catch (e) {
                console.error("Failed to fetch account summary:", e);
            }
        };

        fetchAccount();
        const interval = setInterval(fetchAccount, 2000); // Poll every 2s
        return () => clearInterval(interval);
    }, []);

    // Calculate summary based on positions - OPTIONAL OVERRIDE or MERGE
    // If backend provides full summary, we might rely on that. 
    // However, unrealized_pnl from positions might be faster via WS.
    // Let's use backend summary as base, and maybe override PnL if positions update faster?
    // For now, let's trust the backend polling for simplicity, or just use WS for positions PnL updates.
    // Actually, let's merge: use fetched summary, but if positions change, update PnL?
    // The previous logic was:
    /*
    useEffect(() => {
        const upnl = positions.reduce((acc, p) => acc + p.unrealized_pnl, 0);
        setSummary(prev => ({
            ...prev,
            unrealized_pnl: upnl,
            equity: prev.balance + upnl,
            free_margin: prev.balance + upnl - prev.margin_used 
        }));
    }, [positions]);
    */
    // We can keep this if we trust positions array more than 2s poll. 
    // But `balance` comes from API.
    // Let's keep the API poll for Balance/Margin, and let positions drive PnL/Equity for real-time feel.
    useEffect(() => {
        if (positions.length > 0) {
            const upnl = positions.reduce((acc, p) => acc + p.unrealized_pnl, 0);
            setSummary(prev => ({
                ...prev,
                unrealized_pnl: upnl,
                equity: prev.balance + upnl, // Recalculate equity based on realtime PnL
                free_margin: prev.balance + upnl - prev.used_margin // Update free margin too
            }));
        }
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
