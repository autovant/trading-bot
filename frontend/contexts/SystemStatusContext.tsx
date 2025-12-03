"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { SystemStatus } from '@/types';
import { useMarketData } from './MarketDataContext';
import { useAccount } from './AccountContext';

interface SystemStatusContextType {
    status: SystemStatus;
}

const SystemStatusContext = createContext<SystemStatusContextType | undefined>(undefined);

export const SystemStatusProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const { isConnected: isMarketConnected } = useMarketData();
    const { isConnected: isAccountConnected } = useAccount();

    const [status, setStatus] = useState<SystemStatus>({
        status: 'ok',
        message: 'System Operational',
        latency_ms: 0,
        last_updated: new Date().toISOString(),
        connected: false
    });

    useEffect(() => {
        const connected = isMarketConnected && isAccountConnected;
        const newStatus: SystemStatus['status'] = connected ? 'ok' : 'error';
        const message = connected ? 'System Operational' : 'Connection Lost';

        setStatus(prev => ({
            ...prev,
            status: newStatus,
            message,
            connected,
            last_updated: new Date().toISOString()
        }));
    }, [isMarketConnected, isAccountConnected]);

    // Poll /health endpoint for backend status
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const start = Date.now();
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/health`);
                const end = Date.now();
                if (res.ok) {
                    setStatus(prev => ({
                        ...prev,
                        latency_ms: end - start
                    }));
                }
            } catch (e) {
                // Ignore fetch errors here, relying on WS status for main connection state
            }
        }, 5000);

        return () => clearInterval(interval);
    }, []);

    return (
        <SystemStatusContext.Provider value={{ status }}>
            {children}
        </SystemStatusContext.Provider>
    );
};

export const useSystemStatus = () => {
    const context = useContext(SystemStatusContext);
    if (context === undefined) {
        throw new Error('useSystemStatus must be used within a SystemStatusProvider');
    }
    return context;
};
