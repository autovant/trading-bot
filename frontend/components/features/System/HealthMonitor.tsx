"use client";

import React from "react";
import { useSystemStatus } from "@/contexts/SystemStatusContext";
import { cn } from "@/utils/cn";
import { Activity, Server, AlertTriangle, CheckCircle } from "lucide-react";

const HealthMonitor = () => {
    const { status } = useSystemStatus();

    return (
        <div className="bg-card border-b border-card-border p-3">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">System Health</h3>
                <div className={cn(
                    "w-2 h-2 rounded-full",
                    status.status === 'ok' ? "bg-green-500 animate-pulse" :
                        status.status === 'warning' ? "bg-amber-500" : "bg-red-500"
                )} />
            </div>

            <div className="grid grid-cols-2 gap-2">
                <div className="bg-white/5 rounded p-2 flex flex-col gap-1">
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-500">
                        <Server className="w-3 h-3" />
                        <span>Latency</span>
                    </div>
                    <span className={cn(
                        "text-sm font-mono font-medium",
                        status.latency_ms < 100 ? "text-green-500" :
                            status.latency_ms < 300 ? "text-amber-500" : "text-red-500"
                    )}>
                        {status.latency_ms}ms
                    </span>
                </div>

                <div className="bg-white/5 rounded p-2 flex flex-col gap-1">
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-500">
                        <Activity className="w-3 h-3" />
                        <span>Uptime</span>
                    </div>
                    <span className="text-sm font-mono font-medium text-white">99.9%</span>
                </div>
            </div>

            {status.status !== 'ok' && (
                <div className={cn(
                    "mt-2 p-2 rounded text-[10px] flex items-start gap-2",
                    status.status === 'warning' ? "bg-amber-500/10 text-amber-500" : "bg-red-500/10 text-red-500"
                )}>
                    <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                    <span>{status.message || "System experiencing issues"}</span>
                </div>
            )}
        </div>
    );
};

export default HealthMonitor;
