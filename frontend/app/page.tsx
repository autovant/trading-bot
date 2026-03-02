
"use client";

import React, { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { MarketView } from '@/components/MarketView';
import { StrategyBuilder } from '@/components/StrategyBuilder';
import { BacktestDashboard } from '@/components/BacktestDashboard';
import { SettingsView } from '@/components/SettingsView';
import { AIAssistant } from '@/components/AIAssistant';
import { TabType, TradeSuggestion } from '@/types';
import { useMarketStream } from '@/services/marketStream';
import { cn } from '@/lib/utils';

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>('market');
  const [showAI, setShowAI] = useState(false);

  // Market Data Stream - Integrated at root level to persist data across tabs
  const { marketData, connectionStatus } = useMarketStream('BTC-PERP');

  // AI Suggestion Handler
  const handleAISuggestion = (suggestion: TradeSuggestion) => {
    console.log("AI Suggestion received:", suggestion);
    // Future: Automatically pre-fill order form or chart overlay
  };

  // Render Active View
  const renderContent = () => {
    switch (activeTab) {
      case 'market':
        return <MarketView />;
      case 'strategy':
        return <StrategyBuilder />;
      case 'backtest':
        return <BacktestDashboard />;
      case 'settings':
        return <SettingsView />;
      default:
        return <MarketView />;
    }
  };

  return (
    <AppShell
      activeTab={activeTab}
      onTabChange={setActiveTab}
      onToggleAI={() => setShowAI(!showAI)}
      isAIActive={showAI}
    >
      {/* Main Content Area */}
      <div className="h-full w-full relative">
        {renderContent()}
      </div>

      {/* AI Assistant Overlay */}
      {showAI && (
        <AIAssistant
          isOpen={showAI}
          onClose={() => setShowAI(false)}
          marketData={marketData}
          onSuggestionReceived={handleAISuggestion}
        />
      )}
    </AppShell>
  );
}
