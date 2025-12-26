"use client";

import React from "react";
import { AlertTriangle, X } from "lucide-react";

interface EmergencyConfirmModalProps {
    isOpen: boolean;
    onConfirm: () => void;
    onCancel: () => void;
}

const EmergencyConfirmModal: React.FC<EmergencyConfirmModalProps> = ({ isOpen, onConfirm, onCancel }) => {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/85 backdrop-blur-sm p-4">
            <div className="w-full max-w-[460px] rounded-2xl border border-red-500/40 bg-card/90 shadow-[0_25px_80px_-40px_rgba(0,0,0,0.95)] animate-in fade-in zoom-in duration-200 overflow-hidden">
                <div className="flex items-center justify-between px-5 py-4 border-b border-red-500/30 bg-gradient-to-r from-red-500/15 via-card/80 to-card/80">
                    <h2 className="text-sm font-semibold text-red-400 uppercase tracking-[0.18em] flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4" />
                        Emergency Action
                    </h2>
                    <button onClick={onCancel} className="text-red-300 hover:text-white rounded-full p-2 hover:bg-white/5 transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <div className="p-6 space-y-4">
                    <p className="text-white font-semibold text-center text-lg">
                        Cancel every open order now?
                    </p>
                    <p className="text-gray-400 text-center text-sm">
                        This is irreversible. Orders are pulled from the book immediately and the bot will remain stopped until restarted.
                    </p>

                    <div className="grid grid-cols-2 gap-3 pt-2">
                        <button
                            onClick={onCancel}
                            className="py-3 rounded-lg bg-card-hover hover:bg-card-border text-gray-200 font-bold text-xs uppercase tracking-wide border border-card-border/70 transition-colors"
                        >
                            Keep Running
                        </button>
                        <button
                            onClick={onConfirm}
                            className="py-3 rounded-lg bg-gradient-to-r from-red-500 to-red-600 text-white font-bold text-xs uppercase tracking-wide shadow-[0_12px_30px_-18px_rgba(239,68,68,0.8)] hover:brightness-110 transition-transform active:scale-95"
                        >
                            Confirm Cancel All
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default EmergencyConfirmModal;
