"use client";

import React, { useState, useEffect, useCallback } from "react";
import { X, Plus, Save, Play, ChevronRight, ArrowRight, CheckCircle, AlertCircle } from "lucide-react";
import { api } from "@/utils/api";
import { Strategy } from "@/types";
import { cn } from "@/utils/cn";

interface StrategyBuilderProps {
    onClose: () => void;
}

interface TriggerCondition {
    id: string;
    field: "price" | "rsi" | "volume";
    operator: ">" | "<" | "crosses_above" | "crosses_below";
    value: string;
}

interface ActionConfig {
    side: "buy" | "sell";
    amount: string;
    amountType: "fixed" | "percent";
    orderType: "market" | "limit";
}

    const StrategyBuilder: React.FC<StrategyBuilderProps> = ({ onClose }) => {
        const [strategies, setStrategies] = useState<Strategy[]>([]);
        const [isBuilderView, setIsBuilderView] = useState(false);
        const [, setSelectedStrategy] = useState<Strategy | null>(null);
        const [strategyName, setStrategyName] = useState("New Strategy");
        const [error, setError] = useState<string | null>(null);
        const [success, setSuccess] = useState<string | null>(null);

    // Three-column workflow state
    const [triggers, setTriggers] = useState<TriggerCondition[]>([
        { id: "1", field: "price", operator: ">", value: "" }
    ]);
    const [action, setAction] = useState<ActionConfig>({
        side: "buy",
        amount: "100",
        amountType: "percent",
        orderType: "market"
    });

    const fetchStrategies = useCallback(async () => {
        try {
            const data = await api.getStrategies();
            setStrategies(data);
        } catch {
            setError("Failed to fetch strategies");
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        fetchStrategies();
    }, [fetchStrategies]);

    const addTrigger = () => {
        setTriggers([...triggers, {
            id: Date.now().toString(),
            field: "price",
            operator: ">",
            value: ""
        }]);
    };

    const removeTrigger = (id: string) => {
        if (triggers.length > 1) {
            setTriggers(triggers.filter(t => t.id !== id));
        }
    };

    const updateTrigger = (id: string, updates: Partial<TriggerCondition>) => {
        setTriggers(triggers.map(t => t.id === id ? { ...t, ...updates } : t));
    };

    const buildConfigFromWorkflow = () => {
        return {
            name: strategyName,
            triggers: triggers.map(t => ({
                field: t.field,
                operator: t.operator,
                value: parseFloat(t.value) || 0
            })),
            action: {
                side: action.side,
                amount: parseFloat(action.amount) || 0,
                amount_type: action.amountType,
                order_type: action.orderType
            }
        };
    };

    const generateSummary = (): string => {
        const triggerText = triggers.map(t => {
            const fieldLabel = { price: "Price", rsi: "RSI", volume: "Volume" }[t.field];
            const opLabel = { ">": "is above", "<": "is below", "crosses_above": "crosses above", "crosses_below": "crosses below" }[t.operator];
            return `${fieldLabel} ${opLabel} ${t.value || "___"}`;
        }).join(" AND ");

        const actionText = `${action.side === "buy" ? "BUY" : "SELL"} ${action.amount}${action.amountType === "percent" ? "%" : ""} at ${action.orderType.toUpperCase()}`;

        return `IF ${triggerText}\nTHEN ${actionText}`;
    };

    const handleSave = async () => {
        try {
            const config = buildConfigFromWorkflow();
            await api.saveStrategy({ name: strategyName, config });
            setSuccess("Strategy saved!");
            fetchStrategies();
            setTimeout(() => setIsBuilderView(false), 1000);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Failed to save';
            setError(message);
        }
    };

    const handleActivate = async (name: string) => {
        try {
            await api.activateStrategy(name);
            setSuccess(`${name} activated`);
            fetchStrategies();
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Failed to activate';
            setError(message);
        }
    };

    const handleNew = () => {
        setSelectedStrategy(null);
        setStrategyName("New Strategy");
        setTriggers([{ id: "1", field: "price", operator: ">", value: "" }]);
        setAction({ side: "buy", amount: "100", amountType: "percent", orderType: "market" });
        setIsBuilderView(true);
        setError(null);
        setSuccess(null);
    };

    const handleEdit = (strategy: Strategy) => {
        setSelectedStrategy(strategy);
        setStrategyName(strategy.name);
        // Parse existing config if it matches our format
        const cfg = strategy.config as { triggers?: Array<{ field?: string; operator?: string; value?: unknown }>; action?: { side?: string; amount?: unknown; amount_type?: string; order_type?: string } };
        if (cfg?.triggers) {
            setTriggers(cfg.triggers.map((t, i: number) => ({
                id: String(i),
                field: (t.field || "price") as TriggerCondition['field'],
                operator: (t.operator || ">") as TriggerCondition['operator'],
                value: String(t.value || "")
            })));
        }
        if (cfg?.action) {
            setAction({
                side: (cfg.action.side || "buy") as ActionConfig['side'],
                amount: String(cfg.action.amount || "100"),
                amountType: (cfg.action.amount_type || "percent") as ActionConfig['amountType'],
                orderType: (cfg.action.order_type || "market") as ActionConfig['orderType']
            });
        }
        setIsBuilderView(true);
        setError(null);
        setSuccess(null);
    };

    // Three-column builder UI
    const renderBuilder = () => (
        <div className="flex-1 flex flex-col overflow-hidden">
            {/* Strategy Name */}
            <div className="px-4 py-3 border-b border-gray-800">
                <input
                    type="text"
                    value={strategyName}
                    onChange={(e) => setStrategyName(e.target.value)}
                    className="bg-transparent text-lg font-bold text-gray-100 focus:outline-none border-b border-transparent focus:border-cyan-500 w-full"
                    placeholder="Strategy Name"
                />
            </div>

            {/* Three Column Workflow */}
            <div className="flex-1 p-4 grid grid-cols-[1fr_auto_1fr_auto_1fr] gap-2 overflow-auto">
                {/* Column 1: Triggers */}
                <div className="flex flex-col">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2 flex items-center gap-2">
                        <span className="h-5 w-5 rounded bg-cyan-500/20 text-cyan-400 flex items-center justify-center text-xs font-bold">1</span>
                        TRIGGER (IF)
                    </div>
                    <div className="flex-1 flex flex-col gap-2">
                        {triggers.map((trigger, idx) => (
                            <div key={trigger.id} className="bg-gray-800 border border-gray-700 rounded-lg p-3">
                                {idx > 0 && (
                                    <div className="text-[10px] text-cyan-400 font-bold mb-2">AND</div>
                                )}
                                <div className="flex flex-col gap-2">
                                    <select
                                        value={trigger.field}
                                        onChange={(e) => updateTrigger(trigger.id, { field: e.target.value as TriggerCondition['field'] })}
                                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-cyan-500"
                                    >
                                        <option value="price">Price</option>
                                        <option value="rsi">RSI</option>
                                        <option value="volume">Volume</option>
                                    </select>
                                    <select
                                        value={trigger.operator}
                                        onChange={(e) => updateTrigger(trigger.id, { operator: e.target.value as TriggerCondition['operator'] })}
                                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-cyan-500"
                                    >
                                        <option value=">">is above</option>
                                        <option value="<">is below</option>
                                        <option value="crosses_above">crosses above</option>
                                        <option value="crosses_below">crosses below</option>
                                    </select>
                                    <input
                                        type="text"
                                        value={trigger.value}
                                        onChange={(e) => updateTrigger(trigger.id, { value: e.target.value })}
                                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-cyan-500 font-mono"
                                        placeholder="Value"
                                    />
                                    {triggers.length > 1 && (
                                        <button
                                            onClick={() => removeTrigger(trigger.id)}
                                            className="text-red-400 hover:text-red-300 text-[10px] font-bold uppercase self-end"
                                        >
                                            Remove
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                        <button
                            onClick={addTrigger}
                            className="flex items-center justify-center gap-1 py-2 border border-dashed border-gray-700 rounded-lg text-gray-500 hover:text-cyan-400 hover:border-cyan-500/50 text-xs transition-colors"
                        >
                            <Plus className="w-3 h-3" />
                            Add Condition
                        </button>
                    </div>
                </div>

                {/* Connector Arrow 1→2 */}
                <div className="flex items-center justify-center">
                    <div className="flex flex-col items-center gap-1">
                        <div className="w-8 h-0.5 bg-gradient-to-r from-cyan-500 to-green-500"></div>
                        <ArrowRight className="w-4 h-4 text-green-400" />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-cyan-500 to-green-500"></div>
                    </div>
                </div>

                {/* Column 2: Action */}
                <div className="flex flex-col">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2 flex items-center gap-2">
                        <span className="h-5 w-5 rounded bg-green-500/20 text-green-400 flex items-center justify-center text-xs font-bold">2</span>
                        ACTION (THEN)
                    </div>
                    <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 flex flex-col gap-3">
                        {/* Buy/Sell Toggle */}
                        <div className="flex bg-gray-900 p-0.5 rounded border border-gray-700">
                            <button
                                onClick={() => setAction({ ...action, side: "buy" })}
                                className={cn(
                                    "flex-1 py-2 text-xs font-bold rounded transition-all uppercase",
                                    action.side === "buy" ? "bg-green-500 text-black" : "text-gray-500 hover:text-gray-300"
                                )}
                            >
                                Buy / Long
                            </button>
                            <button
                                onClick={() => setAction({ ...action, side: "sell" })}
                                className={cn(
                                    "flex-1 py-2 text-xs font-bold rounded transition-all uppercase",
                                    action.side === "sell" ? "bg-red-500 text-white" : "text-gray-500 hover:text-gray-300"
                                )}
                            >
                                Sell / Short
                            </button>
                        </div>

                        {/* Amount */}
                        <div>
                            <label className="text-[10px] text-gray-500 uppercase">Amount</label>
                            <div className="flex gap-2 mt-1">
                                <input
                                    type="text"
                                    value={action.amount}
                                    onChange={(e) => setAction({ ...action, amount: e.target.value })}
                                    className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-cyan-500 font-mono"
                                />
                                <select
                                    value={action.amountType}
                                    onChange={(e) => setAction({ ...action, amountType: e.target.value as ActionConfig['amountType'] })}
                                    className="bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-cyan-500"
                                >
                                    <option value="percent">% of Balance</option>
                                    <option value="fixed">Fixed USD</option>
                                </select>
                            </div>
                        </div>

                        {/* Order Type */}
                        <div>
                            <label className="text-[10px] text-gray-500 uppercase">Order Type</label>
                            <div className="flex bg-gray-900 p-0.5 rounded border border-gray-700 mt-1">
                                <button
                                    onClick={() => setAction({ ...action, orderType: "market" })}
                                    className={cn(
                                        "flex-1 py-1.5 text-[10px] font-bold rounded transition-all uppercase",
                                        action.orderType === "market" ? "bg-gray-700 text-gray-100" : "text-gray-500 hover:text-gray-300"
                                    )}
                                >
                                    Market
                                </button>
                                <button
                                    onClick={() => setAction({ ...action, orderType: "limit" })}
                                    className={cn(
                                        "flex-1 py-1.5 text-[10px] font-bold rounded transition-all uppercase",
                                        action.orderType === "limit" ? "bg-gray-700 text-gray-100" : "text-gray-500 hover:text-gray-300"
                                    )}
                                >
                                    Limit
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Connector Arrow 2→3 */}
                <div className="flex items-center justify-center">
                    <div className="flex flex-col items-center gap-1">
                        <div className="w-8 h-0.5 bg-gradient-to-r from-green-500 to-purple-500"></div>
                        <ArrowRight className="w-4 h-4 text-purple-400" />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-green-500 to-purple-500"></div>
                    </div>
                </div>

                {/* Column 3: Summary */}
                <div className="flex flex-col">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2 flex items-center gap-2">
                        <span className="h-5 w-5 rounded bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs font-bold">3</span>
                        SUMMARY
                    </div>
                    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex-1">
                        <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap leading-relaxed">
                            {generateSummary()}
                        </pre>
                    </div>
                </div>
            </div>

            {/* Save Button */}
            <div className="px-4 py-3 border-t border-gray-800 flex justify-between">
                <button
                    onClick={() => setIsBuilderView(false)}
                    className="px-4 py-2 text-xs font-bold text-gray-400 hover:text-gray-100 transition-colors"
                >
                    Cancel
                </button>
                <button
                    onClick={handleSave}
                    className="flex items-center gap-2 px-6 py-2 bg-cyan-500 text-black font-bold rounded text-xs uppercase tracking-wide hover:bg-cyan-400 transition-colors"
                >
                    <Save className="w-4 h-4" />
                    Save Strategy
                </button>
            </div>
        </div>
    );

    // Strategy list view
    const renderList = () => (
        <div className="flex-1 p-4 overflow-auto">
            <button
                onClick={handleNew}
                className="w-full flex items-center justify-center gap-2 p-4 mb-3 border border-dashed border-gray-700 rounded-lg text-gray-500 hover:text-cyan-400 hover:border-cyan-500/50 transition-colors"
            >
                <Plus className="w-4 h-4" />
                Create New Strategy
            </button>

            <div className="flex flex-col gap-2">
                {strategies.map(strategy => (
                    <div
                        key={strategy.id || strategy.name}
                        className={cn(
                            "p-4 rounded-lg border flex items-center justify-between group transition-colors",
                            strategy.is_active
                                ? "border-cyan-500/50 bg-cyan-500/5"
                                : "border-gray-700 bg-gray-800 hover:border-gray-600"
                        )}
                    >
                        <div>
                            <div className="flex items-center gap-2">
                                <span className="font-bold text-gray-100">{strategy.name}</span>
                                {strategy.is_active && (
                                    <span className="text-[9px] bg-cyan-500/20 text-cyan-400 px-1.5 py-0.5 rounded uppercase font-bold">
                                        Active
                                    </span>
                                )}
                            </div>
                            <span className="text-[10px] text-gray-500">
                                Updated: {strategy.updated_at ? new Date(strategy.updated_at).toLocaleDateString() : 'N/A'}
                            </span>
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            {!strategy.is_active && (
                                <button
                                    onClick={() => handleActivate(strategy.name)}
                                    className="p-2 rounded text-gray-400 hover:text-green-400 hover:bg-gray-700 transition-colors"
                                    title="Activate"
                                >
                                    <Play className="w-4 h-4" />
                                </button>
                            )}
                            <button
                                onClick={() => handleEdit(strategy)}
                                className="p-2 rounded text-gray-400 hover:text-cyan-400 hover:bg-gray-700 transition-colors"
                                title="Edit"
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );

    return (
        <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-5xl h-[85vh] flex flex-col shadow-2xl">
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
                    <h2 className="text-sm font-bold text-gray-100 uppercase tracking-wide">
                        {isBuilderView ? "Strategy Builder" : "Strategy Library"}
                    </h2>
                    <button
                        onClick={onClose}
                        className="p-2 rounded text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>

                {/* Content */}
                {isBuilderView ? renderBuilder() : renderList()}

                {/* Status Bar */}
                {(error || success) && (
                    <div className={cn(
                        "px-4 py-2 text-xs font-bold flex items-center gap-2",
                        error ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"
                    )}>
                        {error ? <AlertCircle className="w-4 h-4" /> : <CheckCircle className="w-4 h-4" />}
                        {error || success}
                    </div>
                )}
            </div>
        </div>
    );
};

export default StrategyBuilder;
