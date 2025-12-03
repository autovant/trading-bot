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
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 backdrop-blur-sm">
            <div className="bg-card border border-red-500 rounded-lg w-[400px] shadow-2xl animate-in fade-in zoom-in duration-200">
                <div className="flex items-center justify-between p-4 border-b border-red-500/30 bg-red-500/10">
                    <h2 className="text-sm font-bold text-red-500 uppercase tracking-wider flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4" />
                        Emergency Action
                    </h2>
                    <button onClick={onCancel} className="text-red-400 hover:text-red-300">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <div className="p-6">
                    <p className="text-white font-medium text-center text-lg mb-2">
                        Are you sure you want to cancel ALL open orders?
                    </p>
                    <p className="text-gray-400 text-center text-xs mb-6">
                        This action cannot be undone. All active orders will be immediately removed from the book.
                    </p>

                    <div className="grid grid-cols-2 gap-3">
                        <button
                            onClick={onCancel}
                            className="py-3 rounded bg-card-hover hover:bg-card-border text-gray-300 font-bold text-xs transition-colors"
                        >
                            CANCEL
                        </button>
                        <button
                            onClick={onConfirm}
                            className="py-3 rounded bg-red-600 hover:bg-red-500 text-white font-bold text-xs transition-colors"
                        >
                            CONFIRM CANCEL ALL
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default EmergencyConfirmModal;
