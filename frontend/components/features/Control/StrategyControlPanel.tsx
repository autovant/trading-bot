"use client";

import React, { useState, useEffect } from "react";
import { Settings, Shield, Zap, Activity } from "lucide-react";
import StrategyBuilder from "../Strategy/StrategyBuilder";
import { api } from "@/utils/api";
import { Strategy } from "@/types";

const StrategyControlPanel = () => {
    const [showBuilder, setShowBuilder] = useState(false);
    const [activeStrategy, setActiveStrategy] = useState<Strategy | null>(null);

    useEffect(() => {
        fetchActiveStrategy();
    }, [showBuilder]); // Refresh when builder closes

    const fetchActiveStrategy = async () => {
        try {
            const strategies = await api.getStrategies();
            const active = strategies.find((s: Strategy) => s.is_active);
            setActiveStrategy(active || null);
        } catch (err) {
            console.error("Failed to fetch active strategy", err);
        }
    };

    return (
        <>
            <div className="bg-card border-b border-card-border p-3 flex flex-col gap-3">
                <div className="flex items-center justify-between">
                    <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">Strategy Config</h3>
                    <button
                        onClick={() => setShowBuilder(true)}
                        className="text-gray-500 hover:text-white transition-colors"
                        title="Manage Strategies"
                    >
                        <Settings className="w-3 h-3" />
                    </button>
                </div>

                <div className="grid grid-cols-2 gap-2">
                    <div className="bg-white/5 rounded p-2 flex flex-col gap-1 border border-white/5 hover:border-brand/30 transition-colors cursor-pointer">
                        <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                            <Activity className="w-3 h-3" />
                            <span>Active Strategy</span>
                        </div>
                        <span className="text-xs font-medium text-white truncate" title={activeStrategy?.name || "None"}>
                            {activeStrategy ? activeStrategy.name : "None"}
                        </span>
                    </div>

                    <div className="bg-white/5 rounded p-2 flex flex-col gap-1 border border-white/5 hover:border-brand/30 transition-colors cursor-pointer">
                        <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                            <Zap className="w-3 h-3" />
                            <span>Mode</span>
                        </div>
                        <span className="text-xs font-medium text-white">Auto-Trade</span>
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <div className="flex justify-between text-[10px] text-gray-500">
                        <span>Leverage</span>
                        <span className="text-white">10x</span>
                    </div>
                    <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                        <div className="w-1/3 h-full bg-brand"></div>
                    </div>
                </div>
            </div>

            {showBuilder && <StrategyBuilder onClose={() => setShowBuilder(false)} />}
        </>
    );
};

export default StrategyControlPanel;
