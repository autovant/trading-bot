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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <div className="bg-card border border-card-border rounded-lg w-[400px] shadow-2xl animate-in fade-in zoom-in duration-200">
                <div className="flex items-center justify-between p-4 border-b border-card-border">
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider">Bot Control</h2>
                    <button onClick={onClose} className="text-gray-500 hover:text-white">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <div className="p-6 flex flex-col gap-4">
                    <div className="flex items-center justify-center py-4">
                        <div className={cn(
                            "w-16 h-16 rounded-full flex items-center justify-center border-4",
                            status === 'running' ? "border-green-500/20 text-green-500" : "border-gray-500/20 text-gray-500"
                        )}>
                            {status === 'running' ? <Play className="w-8 h-8 fill-current" /> : <Square className="w-8 h-8 fill-current" />}
                        </div>
                    </div>

                    <div className="text-center">
                        <p className="text-white font-medium">Current Status: <span className={status === 'running' ? "text-green-500" : "text-gray-400"}>{status.toUpperCase()}</span></p>
                        <p className="text-xs text-gray-500 mt-1">Select an action below. All actions require confirmation.</p>
                    </div>

                    <div className="grid grid-cols-2 gap-3 mt-4">
                        <button
                            onClick={onStart}
                            className="flex items-center justify-center gap-2 py-3 rounded bg-green-600 hover:bg-green-500 text-white font-bold text-xs transition-colors"
                        >
                            <Play className="w-3 h-3 fill-current" />
                            START BOT
                        </button>
                        <button
                            onClick={onStop}
                            className="flex items-center justify-center gap-2 py-3 rounded bg-red-600 hover:bg-red-500 text-white font-bold text-xs transition-colors"
                        >
                            <Square className="w-3 h-3 fill-current" />
                            STOP BOT
                        </button>
                    </div>

                    <button
                        onClick={onHalt}
                        className="flex items-center justify-center gap-2 py-3 rounded border border-red-500/20 text-red-500 hover:bg-red-500/10 font-bold text-xs transition-colors mt-2"
                    >
                        <AlertOctagon className="w-3 h-3" />
                        EMERGENCY HALT (CANCEL ALL)
                    </button>
                </div>
            </div>
        </div>
    );
};

export default BotControlModal;
