"use client";

import React, { useState, useEffect } from "react";
import { useSystemStatus } from "@/contexts/SystemStatusContext";
import { useMarketData } from "@/contexts/MarketDataContext";
import { useAccount } from "@/contexts/AccountContext";
import { cn } from "@/utils/cn";
import { Settings, Moon, Sun, Activity, Wifi, WifiOff, Power } from "lucide-react";
import BotControlModal from "@/components/features/Control/BotControlModal";
import { api } from "@/utils/api";

const Header = () => {
    const { status } = useSystemStatus();
    const { lastPrice } = useMarketData();
    const { summary } = useAccount();
    const [isControlModalOpen, setIsControlModalOpen] = useState(false);
    const [botStatus, setBotStatus] = useState<{ enabled: boolean; status: string }>({ enabled: false, status: "unknown" });

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    const fetchStatus = async () => {
        try {
            const data = await api.getBotStatus();
            setBotStatus(data);
        } catch (e) {
            console.error("Failed to fetch bot status", e);
        }
    };

    const handleStart = async () => {
        try {
            await api.startBot();
            await fetchStatus();
            setIsControlModalOpen(false);
        } catch (e) {
            alert("Failed to start bot");
        }
    };

    const handleStop = async () => {
        try {
            await api.stopBot();
            await fetchStatus();
            setIsControlModalOpen(false);
        } catch (e) {
            alert("Failed to stop bot");
        }
    };

    const handleHalt = async () => {
        if (confirm("ARE YOU SURE? This will cancel all orders and stop the bot.")) {
            try {
                await api.haltBot();
                await fetchStatus();
                setIsControlModalOpen(false);
            } catch (e) {
                alert("Failed to halt bot");
            }
        }
    };

    const formatCurrency = (val: number) => {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
    };

    return (
        <header className="h-12 border-b border-card-border bg-card px-4 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-brand-primary/20 flex items-center justify-center">
                        <Activity className="w-5 h-5 text-brand-primary" />
                    </div>
                    <h1 className="font-bold text-lg tracking-tight">
                        <span className="text-brand-primary">ZOOMEX</span>
                        <span className="text-white">BOT</span>
                    </h1>
                </div>

                <div className="h-6 w-px bg-card-border mx-2" />

                <div className="flex items-center gap-2 text-xs">
                    <div className={cn(
                        "flex items-center gap-1.5 px-2 py-1 rounded-full border",
                        status.connected
                            ? "bg-green-500/10 border-green-500/20 text-green-500"
                            : "bg-red-500/10 border-red-500/20 text-red-500"
                    )}>
                        {status.connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
                        <span className="font-medium uppercase">{status.status}</span>
                    </div>

                    <button
                        onClick={() => setIsControlModalOpen(true)}
                        className={cn(
                            "flex items-center gap-1.5 px-2 py-1 rounded-full border transition-colors hover:opacity-80",
                            botStatus.enabled
                                ? "bg-green-500/10 border-green-500/20 text-green-500"
                                : "bg-yellow-500/10 border-yellow-500/20 text-yellow-500"
                        )}
                    >
                        <Power className="w-3 h-3" />
                        <span className="font-medium uppercase">{botStatus.status}</span>
                    </button>
                </div>
            </div>

            <div className="flex items-center gap-4">
                {/* Ticker */}
                <div className="flex items-center gap-3 text-sm">
                    <span className="font-mono text-brand-secondary">BTC/USDT</span>
                    <span className={cn(
                        "font-mono font-bold",
                        lastPrice > 0 ? "text-green-400" : "text-white"
                    )}>
                        {lastPrice.toLocaleString(undefined, { minimumFractionDigits: 1 })}
                    </span>
                </div>

                <div className="h-6 w-px bg-card-border" />

                {/* Account Summary */}
                <div className="flex items-center gap-4 text-xs">
                    <div>
                        <div className="text-gray-500">Equity</div>
                        <div className="font-mono font-medium">{formatCurrency(summary.equity)}</div>
                    </div>
                    <div>
                        <div className="text-gray-500">Unrealized PnL</div>
                        <div className={cn(
                            "font-mono font-medium",
                            summary.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500"
                        )}>
                            {summary.unrealized_pnl >= 0 ? "+" : ""}{formatCurrency(summary.unrealized_pnl)}
                        </div>
                    </div>
                </div>

                <div className="h-6 w-px bg-card-border" />

                {/* Actions */}
                <div className="flex items-center gap-2">
                    <button className="p-2 hover:bg-white/5 rounded-lg text-gray-400 hover:text-white transition-colors">
                        <Settings className="w-4 h-4" />
                    </button>
                </div>
            </div>

            <BotControlModal
                isOpen={isControlModalOpen}
                onClose={() => setIsControlModalOpen(false)}
                status={botStatus.status as "running" | "stopped" | "error"}
                onStart={handleStart}
                onStop={handleStop}
                onHalt={handleHalt}
            />
        </header>
    );
};

export default Header;
