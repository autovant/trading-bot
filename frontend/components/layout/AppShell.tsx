"use client";

import React from "react";
import { Navbar } from "@/components/Navbar";
import { TabType } from "@/types";
import { Zap } from "lucide-react";

interface AppShellProps {
    children: React.ReactNode;
    activeTab: TabType;
    onTabChange: (tab: TabType) => void;
    onToggleAI: () => void;
    isAIActive: boolean;
}

/**
 * Generic Application Shell with Navbar and Status Bar
 */
const AppShell: React.FC<AppShellProps> = ({
    children,
    activeTab,
    onTabChange,
    onToggleAI,
    isAIActive
}) => {
    return (
        <div className="min-h-screen w-screen overflow-hidden bg-background text-foreground font-sans flex flex-col">
            <Navbar
                activeTab={activeTab}
                onTabChange={onTabChange}
                onToggleAI={onToggleAI}
                isAIActive={isAIActive}
            />

            <main className="flex-1 pt-[60px] pb-6 overflow-hidden relative">
                {children}
            </main>

            {/* Persistent Status Bar */}
            <div className="fixed bottom-0 w-full h-6 bg-background-secondary border-t border-white/5 flex items-center justify-between px-4 text-[10px] text-text-tertiary select-none z-50">
                <div className="flex items-center gap-4">
                    <span className="flex items-center gap-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></div>
                        Stable Connection
                    </span>
                    <span>Latency: 32ms</span>
                    <span>v2.4.2 (Build 8920)</span>
                </div>
                <div className="flex items-center gap-4">
                    <span>Paper Trading Environment</span>
                    <span>24h Vol: $4.2B</span>
                </div>
            </div>
        </div>
    );
};

export default AppShell;

