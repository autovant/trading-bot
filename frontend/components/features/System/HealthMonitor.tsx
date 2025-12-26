"use client";

import React from "react";
import { useSystemStatus } from "@/contexts/SystemStatusContext";
import { cn } from "@/utils/cn";
import { Activity, Server, AlertTriangle, ShieldCheck } from "lucide-react";

const HealthMonitor = () => {
    const { status } = useSystemStatus();

    return (
        <div className="glass-card rounded-xl p-5 relative overflow-hidden group">
            {/* Status Pulse Background */}
            <div className={cn(
                "absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl blur-3xl opacity-10 rounded-full pointer-events-none",
                status.status === 'ok' ? "from-brand" : status.status === 'warning' ? "from-accent-amber" : "from-accent-danger"
            )} />

            <div className="flex items-center justify-between mb-5 relative z-10">
                <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-brand" />
                    <h3 className="text-sm font-bold uppercase tracking-widest text-gray-300">System Health</h3>
                </div>
                <div className={cn(
                    "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold border shadow-[0_0_10px_rgba(0,0,0,0.2)]",
                    status.status === 'ok'
                        ? "border-brand/30 text-brand bg-brand/10 shadow-[0_0_10px_rgba(0,255,157,0.1)]"
                        : status.status === 'warning'
                            ? "border-accent-amber/30 text-accent-amber bg-accent-amber/10"
                            : "border-accent-danger/30 text-accent-danger bg-accent-danger/10"
                )}>
                    <div className={cn(
                        "h-1.5 w-1.5 rounded-full animate-pulse",
                        status.status === 'ok' ? "bg-brand" : status.status === 'warning' ? "bg-accent-amber" : "bg-accent-danger"
                    )} />
                    {status.status === 'ok' ? "OPERATIONAL" : status.status === 'warning' ? "DEGRADED" : "CRITICAL"}
                </div>
            </div>

            <div className="grid grid-cols-2 gap-3 relative z-10">
                <div className="bg-gray-950/50 rounded-lg p-3 border border-gray-800 hover:border-brand-secondary/30 transition-colors group/metric">
                    <div className="flex items-center gap-2 text-[10px] uppercase text-gray-500 mb-2 font-bold tracking-wider">
                        <Server className="w-3 h-3 text-brand-secondary group-hover/metric:text-brand-secondary-hover transition-colors" />
                        <span>Latency</span>
                    </div>
                    <div className={cn(
                        "text-base font-mono font-bold tracking-tight",
                        status.latency_ms < 100 ? "text-brand" :
                            status.latency_ms < 300 ? "text-accent-amber" : "text-accent-danger"
                    )}>
                        {status.latency_ms}ms
                    </div>
                </div>

                <div className="bg-gray-950/50 rounded-lg p-3 border border-gray-800 hover:border-brand/30 transition-colors group/metric">
                    <div className="flex items-center gap-2 text-[10px] uppercase text-gray-500 mb-2 font-bold tracking-wider">
                        <Activity className="w-3 h-3 text-brand group-hover/metric:text-brand-hover transition-colors" />
                        <span>Uptime</span>
                    </div>
                    <div className="text-base font-mono font-bold text-gray-100 tracking-tight">99.9%</div>
                </div>
            </div>

            {status.status !== 'ok' && (
                <div className={cn(
                    "mt-3 p-2.5 rounded-lg text-[10px] flex items-center gap-2 border animate-in fade-in slide-in-from-top-1",
                    status.status === 'warning'
                        ? "border-accent-amber/30 bg-accent-amber/10 text-accent-amber"
                        : "border-accent-danger/30 bg-accent-danger/10 text-accent-danger"
                )}>
                    <AlertTriangle className="w-3 h-3 shrink-0" />
                    <span className="font-bold">{status.message || "System issue detected"}</span>
                </div>
            )}
        </div>
    );
};

export default HealthMonitor;
