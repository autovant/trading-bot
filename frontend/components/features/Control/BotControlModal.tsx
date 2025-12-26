"use client";

import React from "react";
import { X, Play, Square, AlertOctagon } from "lucide-react";
import { cn } from "@/utils/cn";

interface BotControlModalProps {
    isOpen: boolean;
    onClose: () => void;
    status: 'running' | 'stopped' | 'error';
    onStart?: () => void;
    onStop?: () => void;
    onHalt?: () => void;
}

const BotControlModal: React.FC<BotControlModalProps> = ({
    isOpen,
    onClose,
    status,
    onStart,
    onStop,
    onHalt
}) => {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
            <div className="w-full max-w-[520px] rounded-2xl border border-card-border/80 bg-card/90 shadow-[0_25px_80px_-40px_rgba(0,0,0,0.9)] animate-in fade-in zoom-in duration-200 overflow-hidden">
                <div className="relative flex items-center justify-between px-6 py-4 border-b border-card-border/70 bg-gradient-to-r from-card-hover/90 via-card/90 to-card-hover/90">
                    <div>
                        <p className="text-[11px] uppercase tracking-[0.2em] text-gray-400">Execution Control</p>
                        <h2 className="text-lg font-semibold text-white">Bot Command Center</h2>
                    </div>
                    <button onClick={onClose} className="text-gray-500 hover:text-white rounded-full p-2 hover:bg-white/5 transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <div className="p-6 flex flex-col gap-5">
                    <div className="flex items-center gap-4 rounded-xl border border-card-border/70 bg-card-hover/60 p-4">
                        <div className={cn(
                            "flex h-14 w-14 items-center justify-center rounded-full border-4",
                            status === 'running' ? "border-trade-long/30 text-trade-long bg-trade-long/5" : "border-card-border/70 text-gray-400 bg-card-hover"
                        )}>
                            {status === 'running' ? <Play className="w-7 h-7" /> : <Square className="w-7 h-7" />}
                        </div>
                        <div className="flex-1">
                            <p className="text-sm text-gray-400">Current status</p>
                            <p className={cn("text-xl font-semibold", status === 'running' ? "text-trade-long" : "text-gray-200")}>
                                {status.toUpperCase()}
                            </p>
                            <p className="text-[11px] text-gray-500">Use the controls below to orchestrate the bot state.</p>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <button
                            onClick={onStart}
                            className="flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-trade-long/90 to-brand-secondary/70 px-4 py-3 text-xs font-bold uppercase tracking-wide text-black shadow-[0_10px_30px_-16px_rgba(82,227,184,0.8)] hover:brightness-110 transition-transform active:scale-95"
                        >
                            <Play className="w-3.5 h-3.5" />
                            Start Bot
                        </button>
                        <button
                            onClick={onStop}
                            className="flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-card-hover to-card border border-card-border/80 px-4 py-3 text-xs font-bold uppercase tracking-wide text-gray-200 hover:border-trade-short/50 hover:text-white transition-transform active:scale-95"
                        >
                            <Square className="w-3.5 h-3.5" />
                            Stop Bot
                        </button>
                    </div>

                    <button
                        onClick={onHalt}
                        className="flex items-center justify-center gap-2 rounded-lg border border-trade-short/50 bg-trade-short/10 px-4 py-3 text-xs font-bold uppercase tracking-wide text-trade-short hover:bg-trade-short/15 transition-transform active:scale-95"
                    >
                        <AlertOctagon className="w-4 h-4" />
                        Emergency Halt (Cancel All)
                    </button>
                </div>
            </div>
        </div>
    );
};

export default BotControlModal;
