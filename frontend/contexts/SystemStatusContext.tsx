"use client";

import React, { createContext, useContext, useEffect, useState, useMemo, ReactNode } from 'react';
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

    const [latencyMs, setLatencyMs] = useState(0);

    // Derive connection status directly (no effect needed)
    const connected = isMarketConnected && isAccountConnected;
    const derivedStatus: SystemStatus['status'] = connected ? 'ok' : 'error';
    const derivedMessage = connected ? 'System Operational' : 'Connection Lost';

    // Memoize final status object
    const status = useMemo<SystemStatus>(() => ({
        status: derivedStatus,
        message: derivedMessage,
        latency_ms: latencyMs,
        last_updated: new Date().toISOString(),
        connected
    }), [derivedStatus, derivedMessage, latencyMs, connected]);

    // Poll /health endpoint for backend status
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const start = Date.now();
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/health`);
                const end = Date.now();
                if (res.ok) {
                    setLatencyMs(end - start);
                }
            } catch {
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
