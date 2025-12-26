"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSystemStatus } from "@/contexts/SystemStatusContext";
import { useMarketData } from "@/contexts/MarketDataContext";
import { useAccount } from "@/contexts/AccountContext";
import { cn } from "@/utils/cn";
import { Settings, Activity, Wifi, WifiOff, Power, Gauge } from "lucide-react";
import BotControlModal from "@/components/features/Control/BotControlModal";
import { api } from "@/utils/api";

const Header = () => {
    const { status } = useSystemStatus();
    const { lastPrice, marketData } = useMarketData();
    const { summary } = useAccount();
    const pathname = usePathname();
    const [isControlModalOpen, setIsControlModalOpen] = useState(false);
    const [botStatus, setBotStatus] = useState<{ enabled: boolean; status: string }>({ enabled: false, status: "unknown" });

    const navItems = [
        { href: "/", label: "Trading Desk", badge: "Live" },
        { href: "/strategy-studio", label: "Strategy Studio" },
    ];

    const fetchStatus = useCallback(async () => {
        try {
            const data = await api.getBotStatus();
            setBotStatus(data);
        } catch {
            console.error("Failed to fetch bot status");
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, [fetchStatus]);

    const handleStart = async () => {
        try {
            await api.startBot();
            await fetchStatus();
            setIsControlModalOpen(false);
        } catch {
            alert("Failed to start bot");
        }
    };

    const handleStop = async () => {
        try {
            await api.stopBot();
            await fetchStatus();
            setIsControlModalOpen(false);
        } catch {
            alert("Failed to stop bot");
        }
    };

    const handleHalt = async () => {
        if (confirm("ARE YOU SURE? This will cancel all orders and stop the bot.")) {
            try {
                await api.haltBot();
                await fetchStatus();
                setIsControlModalOpen(false);
            } catch {
                alert("Failed to halt bot");
            }
        }
    };

    const formatCurrency = (val: number) => {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val);
    };

    const priceColor = lastPrice >= (marketData?.best_bid || lastPrice) ? "text-trade-long text-glow" : "text-trade-short text-glow-red";

    return (
        <header className="h-14 shrink-0 flex items-center justify-between px-4 bg-background/80 backdrop-blur-md border-b border-card-border z-40 relative">
            {/* Top Glow Line */}
            <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-brand/20 to-transparent"></div>

            {/* Left: Logo & Status */}
            <div className="flex items-center gap-6">
                <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-card border border-brand/20 text-brand shadow-[0_0_10px_rgba(0,255,157,0.2)]">
                        <Activity className="h-5 w-5" />
                    </div>
                    <div className="leading-tight">
                        <p className="text-sm font-bold text-gray-100 tracking-wide font-sans">ZOOMEX</p>
                        <p className="text-[10px] text-brand-secondary font-mono tracking-wider">TERMINAL v2.0</p>
                    </div>
                </div>

                {/* Connection Status */}
                <div className="hidden md:flex items-center gap-3 pl-6 border-l border-gray-800/50">
                    <div className={cn(
                        "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all duration-300",
                        status.connected
                            ? "border-brand/30 bg-brand/10 text-brand"
                            : "border-accent-danger/30 bg-accent-danger/10 text-accent-danger"
                    )}>
                        {status.connected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
                        {status.connected ? "CNX: STABLE" : "CNX: LOST"}
                    </div>
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold border border-gray-800 bg-card text-gray-400 font-mono">
                        <Gauge className="h-3 w-3 text-brand-secondary" />
                        {status.latency_ms || 0}ms
                    </div>
                    <button
                        onClick={() => setIsControlModalOpen(true)}
                        className={cn(
                            "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all duration-300 hover:shadow-lg",
                            botStatus.enabled
                                ? "border-brand/30 bg-brand/10 text-brand hover:bg-brand/20 shadow-[0_0_10px_rgba(0,255,157,0.1)]"
                                : "border-accent-amber/30 bg-accent-amber/10 text-accent-amber hover:bg-accent-amber/20"
                        )}
                    >
                        <Power className="h-3 w-3" />
                        {botStatus.status?.toUpperCase?.() || "SYSTEM STANDBY"}
                    </button>
                </div>
            </div>

            {/* Center: Navigation */}
            <nav className="flex items-center gap-1 bg-card/50 p-1 rounded-lg border border-card-border">
                {navItems.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={cn(
                                "flex items-center gap-2 px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wide transition-all duration-200",
                                isActive
                                    ? "bg-brand-secondary/10 text-brand-secondary border border-brand-secondary/20 shadow-[0_0_10px_rgba(0,224,255,0.1)]"
                                    : "text-gray-500 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            {item.label}
                            {item.badge && (
                                <span className={cn(
                                    "px-1.5 py-0.5 rounded text-[9px]",
                                    isActive ? "bg-brand-secondary/20 text-brand-secondary" : "bg-gray-800 text-gray-400"
                                )}>
                                    {item.badge}
                                </span>
                            )}
                        </Link>
                    );
                })}
            </nav>

            {/* Right: Price & Account Info */}
            <div className="flex items-center gap-6">
                <div className="hidden lg:flex items-center gap-6 pr-6 border-r border-gray-800/50">
                    <div className="text-right">
                        <p className="text-[10px] uppercase text-gray-500 font-bold tracking-wider mb-0.5">Market</p>
                        <p className={cn("text-base font-mono font-bold tracking-tight", priceColor)}>
                            {lastPrice ? lastPrice.toLocaleString(undefined, { minimumFractionDigits: 1 }) : "---"}
                        </p>
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] uppercase text-gray-500 font-bold tracking-wider mb-0.5">Equity</p>
                        <p className="text-sm font-mono font-bold text-gray-100">{formatCurrency(summary.equity)}</p>
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] uppercase text-gray-500 font-bold tracking-wider mb-0.5">Unrealized</p>
                        <p className={cn(
                            "text-sm font-mono font-bold",
                            summary.unrealized_pnl >= 0 ? "text-trade-long" : "text-trade-short"
                        )}>
                            {summary.unrealized_pnl >= 0 ? "+" : ""}{formatCurrency(summary.unrealized_pnl)}
                        </p>
                    </div>
                </div>

                <button className="p-2.5 rounded-lg text-gray-400 border border-transparent hover:border-gray-700 hover:bg-card hover:text-gray-100 transition-all duration-200">
                    <Settings className="h-4 w-4" />
                </button>
            </div>

            {/* Bot Control Modal - z-50 */}
            {isControlModalOpen && (
                <div className="fixed inset-0 z-50">
                    <BotControlModal
                        isOpen={isControlModalOpen}
                        onClose={() => setIsControlModalOpen(false)}
                        status={botStatus.status as "running" | "stopped" | "error"}
                        onStart={handleStart}
                        onStop={handleStop}
                        onHalt={handleHalt}
                    />
                </div>
            )}
        </header>
    );
};

export default Header;
