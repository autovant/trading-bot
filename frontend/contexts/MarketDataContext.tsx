"use client";

import React, { createContext, useContext, useEffect, useState, useRef, ReactNode } from 'react';
import { OrderBookData, MarketDataState } from '@/types';
import { useWebSocket } from '@/hooks/useWebSocket';

interface MarketDataContextType {
    marketData: OrderBookData | null;
    isConnected: boolean;
    lastPrice: number;
}

const MarketDataContext = createContext<MarketDataContextType | undefined>(undefined);

export const MarketDataProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    // Use window.location.hostname to allow connecting from other devices/containers if needed, 
    // but for now hardcode localhost as per existing code or make it configurable.
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_BASE_URL}/ws/market-data`;

    const { lastMessage: marketData, isConnected } = useWebSocket<OrderBookData>(wsUrl, {
        shouldConnect: true,
        reconnectInterval: 3000,
        validator: (data: unknown): data is OrderBookData => {
            // Basic shape check
            return typeof data === 'object' && data !== null && 'symbol' in data && 'best_bid' in data;
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

export const useMarketData = () => {
    const context = useContext(MarketDataContext);
    if (context === undefined) {
        throw new Error('useMarketData must be used within a MarketDataProvider');
    }
    return context;
};
