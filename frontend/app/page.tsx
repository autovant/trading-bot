"use client";

import React, { useState, useEffect } from "react";
import AppShell from "@/components/layout/AppShell";
import { TradingChart } from "@/components/TradingChart";
import OrderBook from "@/components/dashboard/OrderBook";
import PositionsTable from "@/components/dashboard/PositionsTable";
import HealthMonitor from "@/components/features/System/HealthMonitor";
import StrategyControlPanel from "@/components/features/Control/StrategyControlPanel";
import ManualTradePanel from "@/components/features/Control/ManualTradePanel";
import BotControlModal from "@/components/features/Control/BotControlModal";
import EmergencyConfirmModal from "@/components/features/Control/EmergencyConfirmModal";

import { MarketDataProvider } from "@/contexts/MarketDataContext";
import { AccountDataProvider } from "@/contexts/AccountContext";
import { SystemStatusProvider } from "@/contexts/SystemStatusContext";

export default function Home() {
  const [isBotModalOpen, setIsBotModalOpen] = useState(false);
  const [isEmergencyModalOpen, setIsEmergencyModalOpen] = useState(false);

  const handleEmergencyConfirm = () => {
    console.log("EMERGENCY HALT TRIGGERED");
    // TODO: Call API
    setIsEmergencyModalOpen(false);
    setIsBotModalOpen(false);
  };

  const handleBotStart = () => {
    console.log("Starting bot...");
    // TODO: Call API
    setIsBotModalOpen(false);
  };

  const handleBotStop = () => {
    console.log("Stopping bot...");
    // TODO: Call API
    setIsBotModalOpen(false);
  };

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable
      ) {
        return;
      }

      // Ctrl+Space -> Open Bot Control
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        setIsBotModalOpen(true);
      }
      // Esc -> Close Modals
      if (e.code === 'Escape') {
        setIsBotModalOpen(false);
        setIsEmergencyModalOpen(false);
      }
      // Ctrl+Shift+O -> Cancel All
      if (e.ctrlKey && e.shiftKey && e.code === 'KeyO') {
        e.preventDefault();
        setIsEmergencyModalOpen(true);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <MarketDataProvider>
      <AccountDataProvider>
        <SystemStatusProvider>
          <AppShell
            rightPanel={
              <>
                <HealthMonitor />
                <StrategyControlPanel />
                <ManualTradePanel />
              </>
            }
            bottomPanel={
              <PositionsTable />
            }
          >
            {/* Main Content: Chart + OrderBook Split */}
            <div className="flex h-full">
              <div className="flex-1 min-w-0">
                <TradingChart />
              </div>
              <div className="w-[280px] border-l border-card-border hidden xl:block">
                <OrderBook />
              </div>
            </div>

            <BotControlModal
              isOpen={isBotModalOpen}
              onClose={() => setIsBotModalOpen(false)}
              status="stopped" // This should come from SystemStatusContext in a real implementation
              onStart={handleBotStart}
              onStop={handleBotStop}
              onHalt={() => setIsEmergencyModalOpen(true)}
            />

            <EmergencyConfirmModal
              isOpen={isEmergencyModalOpen}
              onConfirm={handleEmergencyConfirm}
              onCancel={() => setIsEmergencyModalOpen(false)}
            />
          </AppShell>
        </SystemStatusProvider>
      </AccountDataProvider>
    </MarketDataProvider>
  );
}
