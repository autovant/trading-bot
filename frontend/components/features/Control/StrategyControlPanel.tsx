"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Settings, Zap, Layers, Activity } from "lucide-react";
import StrategyBuilder from "../Strategy/StrategyBuilder";
import { api } from "@/utils/api";
import { Strategy } from "@/types";

const StrategyControlPanel = () => {
    const [showBuilder, setShowBuilder] = useState(false);
    const [activeStrategy, setActiveStrategy] = useState<Strategy | null>(null);

    const fetchActiveStrategy = useCallback(async () => {
        try {
            const strategies = await api.getStrategies();
            const active = strategies.find((s: Strategy) => s.is_active);
            setActiveStrategy(active || null);
        } catch {
            console.error("Failed to fetch active strategy");
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        fetchActiveStrategy();
    }, [showBuilder, fetchActiveStrategy]);

    return (
        <>
            <div className="glass-card rounded-xl p-5 relative overflow-hidden mb-4 group">
                {/* Background Grid Effect */}
                <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:20px_20px] opacity-20 pointer-events-none"></div>

                <div className="flex items-center justify-between mb-5 relative z-10">
                    <div className="flex items-center gap-2">
                        <Activity className="w-4 h-4 text-brand" />
                        <h3 className="text-sm font-bold uppercase tracking-widest text-gray-300">Strategy Engine</h3>
                    </div>
                    <button
                        onClick={() => setShowBuilder(true)}
                        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[10px] font-bold uppercase text-gray-400 border border-gray-700 bg-gray-950/50 hover:border-brand hover:text-brand hover:shadow-[0_0_10px_rgba(0,255,157,0.2)] transition-all duration-300"
                    >
                        <Settings className="w-3 h-3" />
                        Config
                    </button>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-5 relative z-10">
                    <div className="bg-gray-950/50 rounded-lg p-3 border border-gray-800 hover:border-brand/30 transition-colors group/card">
                        <div className="flex items-center gap-2 text-[10px] uppercase text-gray-500 mb-2 font-bold tracking-wider">
                            <Layers className="w-3 h-3 text-brand group-hover/card:text-brand-hover transition-colors" />
                            <span>Active Protocol</span>
                        </div>
                        <span className="text-sm font-bold text-gray-100 truncate block font-mono tracking-tight" title={activeStrategy?.name || "None"}>
                            {activeStrategy ? activeStrategy.name : "NO ACTIVE STRATEGY"}
                        </span>
                    </div>

                    <div className="bg-gray-950/50 rounded-lg p-3 border border-gray-800 hover:border-brand-secondary/30 transition-colors group/card">
                        <div className="flex items-center gap-2 text-[10px] uppercase text-gray-500 mb-2 font-bold tracking-wider">
                            <Zap className="w-3 h-3 text-brand-secondary group-hover/card:text-brand-secondary-hover transition-colors" />
                            <span>Execution Mode</span>
                        </div>
                        <span className="text-sm font-bold text-gray-100 font-mono tracking-tight">AUTONOMOUS</span>
                    </div>
                </div>

                <div className="relative z-10">
                    <div className="flex justify-between text-[10px] text-gray-500 uppercase mb-2 font-bold tracking-wider">
                        <span>Risk Leverage</span>
                        <span className="text-brand-secondary font-mono">10x</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden relative">
                        {/* Animated Gradient Bar */}
                        <div className="w-1/3 h-full bg-gradient-to-r from-brand-secondary to-brand animate-pulse-slow relative">
                            <div className="absolute right-0 top-0 bottom-0 w-2 bg-white/50 blur-[2px]"></div>
                        </div>
                    </div>
                </div>
            </div>

            {showBuilder && (
                <div className="fixed inset-0 z-50">
                    <StrategyBuilder onClose={() => setShowBuilder(false)} />
                </div>
            )}
        </>
    );
};

export default StrategyControlPanel;
