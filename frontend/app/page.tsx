"use client";

import React, { useState, useEffect } from "react";
import { api } from "@/utils/api";
import AppShell from "@/components/layout/AppShell";
import { TradingChart } from "@/components/TradingChart";
import PositionsTable from "@/components/dashboard/PositionsTable";
import HealthMonitor from "@/components/features/System/HealthMonitor";
import StrategyControlPanel from "@/components/features/Control/StrategyControlPanel";
import ManualTradePanel from "@/components/features/Control/ManualTradePanel";
import BotControlModal from "@/components/features/Control/BotControlModal";
import EmergencyConfirmModal from "@/components/features/Control/EmergencyConfirmModal";

import { MarketDataProvider } from "@/contexts/MarketDataContext";
import { AccountDataProvider } from "@/contexts/AccountContext";
import { SystemStatusProvider } from "@/contexts/SystemStatusContext";
import { useAccount } from "@/contexts/AccountContext";
import { useSystemStatus } from "@/contexts/SystemStatusContext";
import { useMarketData } from "@/contexts/MarketDataContext";
import { cn } from "@/utils/cn";
import { Zap, Activity, Server } from "lucide-react";

function DashboardView() {
  const [isBotModalOpen, setIsBotModalOpen] = useState(false);
  const [isEmergencyModalOpen, setIsEmergencyModalOpen] = useState(false);
  const { summary } = useAccount();
  const { status } = useSystemStatus();
  const { isConnected, lastPrice, marketData } = useMarketData();
  const symbol = marketData?.symbol || "BTCUSDT";

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(val);

  const handleEmergencyConfirm = async () => {
    try {
      await api.haltBot();
      alert("EMERGENCY HALT TRIGGERED");
    } catch (e) {
      alert("Failed to halt bot: " + e);
    }
    setIsEmergencyModalOpen(false);
    setIsBotModalOpen(false);
  };

  const handleBotStart = async () => {
    try {
      await api.startBot();
      // alert("Bot started"); 
    } catch (e) {
      alert("Failed to start bot: " + e);
    }
    setIsBotModalOpen(false);
  };

  const handleBotStop = async () => {
    try {
      await api.stopBot();
      // alert("Bot stopped");
    } catch (e) {
      alert("Failed to stop bot: " + e);
    }
    setIsBotModalOpen(false);
  };

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      if (e.ctrlKey && e.code === "Space") {
        e.preventDefault();
        setIsBotModalOpen(true);
      }
      if (e.code === "Escape") {
        setIsBotModalOpen(false);
        setIsEmergencyModalOpen(false);
      }
      if (e.ctrlKey && e.shiftKey && e.code === "KeyO") {
        e.preventDefault();
        setIsEmergencyModalOpen(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Sidebar content
  const sidebarContent = (
    <>
      {/* Account Summary */}
      <div className="rounded-lg bg-gray-800 border border-gray-700 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400">Account</h3>
          <span className={cn(
            "flex items-center gap-1.5 text-[10px] font-mono font-bold",
            status.connected ? "text-green-400" : "text-red-400"
          )}>
            <span className={cn(
              "h-1.5 w-1.5 rounded-full",
              status.connected ? "bg-green-400 animate-pulse" : "bg-red-400"
            )} />
            {status.connected ? "ONLINE" : "OFFLINE"}
          </span>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between">
            <span className="text-xs text-gray-500">Equity</span>
            <span className="text-sm font-mono font-bold text-green-400">{formatCurrency(summary.equity)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-xs text-gray-500">Free Margin</span>
            <span className="text-sm font-mono text-gray-100">{formatCurrency(summary.free_margin)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-xs text-gray-500">Unrealized PnL</span>
            <span className={cn(
              "text-sm font-mono font-bold",
              summary.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"
            )}>
              {summary.unrealized_pnl >= 0 ? "+" : ""}{formatCurrency(summary.unrealized_pnl)}
            </span>
          </div>
        </div>

        <div className="flex gap-2 mt-3 pt-3 border-t border-gray-700">
          <div className={cn(
            "flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-bold border",
            isConnected
              ? "border-green-500/30 bg-green-500/10 text-green-400"
              : "border-amber-500/30 bg-amber-500/10 text-amber-400"
          )}>
            <Activity className="h-3 w-3" />
            {isConnected ? "FEED" : "..."}
          </div>
          <div className="flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-bold border border-gray-700 bg-gray-800 text-gray-400">
            <Server className="h-3 w-3" />
            {status.latency_ms || 0}ms
          </div>
          <button
            onClick={() => setIsBotModalOpen(true)}
            className="ml-auto flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-bold border border-cyan-500/50 bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
          >
            <Zap className="h-3 w-3" />
            BOT
          </button>
        </div>
      </div>

      {/* Health Monitor */}
      <HealthMonitor />

      {/* Strategy Control */}
      <StrategyControlPanel />

      {/* Manual Trade Panel */}
      <ManualTradePanel />
    </>
  );

  // Main chart content
  const chartContent = (
    <div className="h-full flex flex-col">
      {/* Chart Header */}
      <div className="flex items-center justify-between border-b border-gray-800 bg-black px-4 py-2">
        <div className="flex items-center gap-3">
          <div className="rounded bg-gray-800 px-2 py-1 text-xs font-bold font-mono text-gray-100 border border-gray-700">
            {symbol}
          </div>
          <div className="h-4 w-px bg-gray-700" />
          <div className="text-sm font-mono text-gray-100">
            {lastPrice ? lastPrice.toLocaleString(undefined, { minimumFractionDigits: 1 }) : "--"}
          </div>
        </div>
        <span className="text-[10px] text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          1H
        </span>
      </div>

      {/* Chart Body */}
      <div className="flex-1 min-h-0">
        <TradingChart />
      </div>
    </div>
  );

  return (
    <>
      <AppShell
        sidebar={sidebarContent}
        bottomPanel={<PositionsTable />}
      >
        {chartContent}
      </AppShell>

      {/* Modals - z-50 to stay above everything */}
      {isBotModalOpen && (
        <div className="fixed inset-0 z-50">
          <BotControlModal
            isOpen={isBotModalOpen}
            onClose={() => setIsBotModalOpen(false)}
            status="stopped"
            onStart={handleBotStart}
            onStop={handleBotStop}
            onHalt={() => setIsEmergencyModalOpen(true)}
          />
        </div>
      )}

      {isEmergencyModalOpen && (
        <div className="fixed inset-0 z-50">
          <EmergencyConfirmModal
            isOpen={isEmergencyModalOpen}
            onConfirm={handleEmergencyConfirm}
            onCancel={() => setIsEmergencyModalOpen(false)}
          />
        </div>
      )}
    </>
  );
}

export default function Home() {
  return (
    <MarketDataProvider>
      <AccountDataProvider>
        <SystemStatusProvider>
          <DashboardView />
        </SystemStatusProvider>
      </AccountDataProvider>
    </MarketDataProvider>
  );
}
