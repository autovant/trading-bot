"use client";

import React, { createContext, useContext, ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { OrderBookData } from '@/types';
import { AccountSummaryResponse, PositionResponse, OrderResponse } from '@/types/api';
import { useWebSocket } from '@/hooks/useWebSocket';

// --- Types ---

interface MarketContextState {
    marketData: OrderBookData | null;
    isConnected: boolean;
    lastPrice: number;
}

const MarketDataContext = createContext<MarketContextState | undefined>(undefined);

// --- Fetchers ---

const fetchAccount = async (): Promise<AccountSummaryResponse> => {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/account`);
    if (!res.ok) throw new Error('Failed to fetch account');
    return res.json();
};

const fetchPositions = async (): Promise<PositionResponse[]> => {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/positions`);
    if (!res.ok) throw new Error('Failed to fetch positions');
    return res.json();
};

// --- Provider ---

export const MarketDataProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_BASE_URL || 'ws://localhost:8000'}/ws/market-data`;

    // 1. WebSocket for Real-time Market Data
    const { lastMessage: marketData, isConnected } = useWebSocket<OrderBookData>(wsUrl, {
        shouldConnect: true,
        reconnectInterval: 3000,
        validator: (data: unknown): data is OrderBookData => {
            return typeof data === 'object' && data !== null && 'symbol' in data;
        }
    });

    const value = React.useMemo(() => ({
        marketData,
        isConnected,
        lastPrice: marketData?.last_price || 0
    }), [marketData, isConnected]);

    return (
        <MarketDataContext.Provider value={value}>
            {children}
        </MarketDataContext.Provider>
    );
};

// --- Hooks ---

export const useMarketData = () => {
    const context = useContext(MarketDataContext);
    if (context === undefined) {
        throw new Error('useMarketData must be used within a MarketDataProvider');
    }
    return context;
};

export const useAccount = () => {
    return useQuery({
        queryKey: ['account'],
        queryFn: fetchAccount,
        refetchInterval: 5000,
    });
};

const fetchOpenOrders = async (): Promise<OrderResponse[]> => {
    // Assuming endpoint exists or we use a placeholder
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/orders?status=open`);
    if (!res.ok) return []; // Fallback or throw
    return res.json();
};

export const useOpenOrders = () => {
    return useQuery({
        queryKey: ['openOrders'],
        queryFn: fetchOpenOrders,
        refetchInterval: 3000,
    });
};

export const usePositions = () => {
    return useQuery({
        queryKey: ['positions'],
        queryFn: fetchPositions,
        refetchInterval: 3000,
    });
};
