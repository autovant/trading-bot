"use client";

import React, { useState, useEffect } from "react";
import { Plus, Save, Trash2, Play, Edit, ArrowLeft, CheckCircle, AlertCircle } from "lucide-react";
import { api } from "@/utils/api";
import { Strategy } from "@/types";

interface StrategyBuilderProps {
    onClose: () => void;
}

const StrategyBuilder: React.FC<StrategyBuilderProps> = ({ onClose }) => {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
    const [editMode, setEditMode] = useState(false);
    const [configJson, setConfigJson] = useState("");
    const [name, setName] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    useEffect(() => {
        fetchStrategies();
    }, []);

    const fetchStrategies = async () => {
        try {
            const data = await api.getStrategies();
            setStrategies(data);
        } catch (err) {
            setError("Failed to fetch strategies");
        }
    };

    const handleSelectStrategy = (strategy: Strategy) => {
        setSelectedStrategy(strategy);
        setName(strategy.name);
        setConfigJson(JSON.stringify(strategy.config, null, 2));
        setEditMode(true);
        setError(null);
        setSuccess(null);
    };

    const handleCreateNew = () => {
        setSelectedStrategy(null);
        setName("New Strategy");
        setConfigJson(JSON.stringify({
            name: "New Strategy",
            regime: { timeframe: "1d" },
            setup: { timeframe: "4h" },
            signals: [],
            risk: { stop_loss_type: "atr", stop_loss_value: 1.5 }
        }, null, 2));
        setEditMode(true);
        setError(null);
        setSuccess(null);
    };

    const handleSave = async () => {
        try {
            let config;
            try {
                config = JSON.parse(configJson);
            } catch (e) {
                setError("Invalid JSON configuration");
                return;
            }

            const payload = {
                name: name,
                config: config
            };

            await api.saveStrategy(payload);
            setSuccess("Strategy saved successfully");
            fetchStrategies();
            if (!selectedStrategy) {
                // If creating new, switch to edit mode for the new one (simplified by just fetching)
                setEditMode(false);
            }
        } catch (err: any) {
            setError(err.message || "Failed to save strategy");
        }
    };

    const handleActivate = async (strategyName: string) => {
        try {
            await api.activateStrategy(strategyName);
            setSuccess(`Strategy ${strategyName} activated`);
            fetchStrategies();
        } catch (err: any) {
            setError(err.message || "Failed to activate strategy");
        }
    };

    const handleDelete = async (strategyName: string) => {
        if (!confirm(`Are you sure you want to delete ${strategyName}?`)) return;
        try {
            await api.deleteStrategy(strategyName);
            setSuccess(`Strategy ${strategyName} deleted`);
            fetchStrategies();
            setEditMode(false);
        } catch (err: any) {
            setError(err.message || "Failed to delete strategy");
        }
    };

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-[#0B0E11] border border-white/10 rounded-lg w-full max-w-4xl h-[80vh] flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-white/10">
                    <h2 className="text-lg font-medium text-white flex items-center gap-2">
                        {editMode ? (
                            <>
                                <button onClick={() => setEditMode(false)} className="hover:text-brand transition-colors">
                                    <ArrowLeft className="w-5 h-5" />
                                </button>
                                {selectedStrategy ? "Edit Strategy" : "New Strategy"}
                            </>
                        ) : (
                            "Strategy Library"
                        )}
                    </h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-hidden flex">
                    {editMode ? (
                        <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-gray-400">Strategy Name</label>
                                <input
                                    type="text"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    className="bg-black/20 border border-white/10 rounded px-3 py-2 text-white focus:border-brand outline-none"
                                />
                            </div>
                            <div className="flex-1 flex flex-col gap-1">
                                <label className="text-xs text-gray-400">Configuration (JSON)</label>
                                <textarea
                                    value={configJson}
                                    onChange={(e) => setConfigJson(e.target.value)}
                                    className="flex-1 bg-black/20 border border-white/10 rounded p-3 text-xs font-mono text-gray-300 focus:border-brand outline-none resize-none"
                                    spellCheck={false}
                                />
                            </div>
                            <div className="flex items-center justify-between pt-2">
                                <div className="flex items-center gap-2">
                                    {selectedStrategy && (
                                        <button
                                            onClick={() => handleDelete(selectedStrategy.name)}
                                            className="flex items-center gap-2 px-4 py-2 bg-red-500/10 text-red-500 hover:bg-red-500/20 rounded text-sm transition-colors"
                                        >
                                            <Trash2 className="w-4 h-4" /> Delete
                                        </button>
                                    )}
                                </div>
                                <button
                                    onClick={handleSave}
                                    className="flex items-center gap-2 px-6 py-2 bg-brand text-black font-medium rounded hover:bg-brand-hover transition-colors"
                                >
                                    <Save className="w-4 h-4" /> Save Strategy
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="flex-1 p-4 flex flex-col gap-3 overflow-y-auto">
                            <button
                                onClick={handleCreateNew}
                                className="flex items-center justify-center gap-2 p-4 border border-dashed border-white/20 rounded-lg text-gray-400 hover:text-white hover:border-brand/50 hover:bg-white/5 transition-all group"
                            >
                                <Plus className="w-5 h-5 group-hover:scale-110 transition-transform" />
                                <span>Create New Strategy</span>
                            </button>

                            {strategies.map(strategy => (
                                <div key={strategy.id || strategy.name} className={`p-4 rounded-lg border ${strategy.is_active ? 'border-brand/50 bg-brand/5' : 'border-white/10 bg-white/5'} flex items-center justify-between group hover:border-white/20 transition-all`}>
                                    <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-white">{strategy.name}</span>
                                            {strategy.is_active && (
                                                <span className="text-[10px] bg-brand/20 text-brand px-1.5 py-0.5 rounded flex items-center gap-1">
                                                    <CheckCircle className="w-3 h-3" /> Active
                                                </span>
                                            )}
                                        </div>
                                        <span className="text-xs text-gray-500">Last updated: {strategy.updated_at ? new Date(strategy.updated_at).toLocaleDateString() : 'N/A'}</span>
                                    </div>
                                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                        {!strategy.is_active && (
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleActivate(strategy.name); }}
                                                className="p-2 hover:bg-white/10 rounded text-gray-400 hover:text-brand transition-colors"
                                                title="Activate"
                                            >
                                                <Play className="w-4 h-4" />
                                            </button>
                                        )}
                                        <button
                                            onClick={() => handleSelectStrategy(strategy)}
                                            className="p-2 hover:bg-white/10 rounded text-gray-400 hover:text-white transition-colors"
                                            title="Edit"
                                        >
                                            <Edit className="w-4 h-4" />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Status Bar */}
                {(error || success) && (
                    <div className={`p-3 text-xs font-medium flex items-center gap-2 ${error ? 'bg-red-500/10 text-red-500' : 'bg-green-500/10 text-green-500'}`}>
                        {error ? <AlertCircle className="w-4 h-4" /> : <CheckCircle className="w-4 h-4" />}
                        {error || success}
                    </div>
                )}
            </div>
        </div>
    );
};

export default StrategyBuilder;
