"use client";

import React, { useState } from "react";
import { cn } from "@/utils/cn";
import { useAccount } from "@/contexts/AccountContext";
import { Position, Order } from "@/types";

import { api } from "@/utils/api";

const PositionsTable = () => {
    const [activeTab, setActiveTab] = useState("positions");
    const { positions, openOrders, isConnected } = useAccount();

    // TODO: Wire up real logs from context/backend
    const logs: Array<{ time: string, type: string, message: string }> = [];

    const handleClosePosition = async (symbol: string) => {
        if (confirm(`Are you sure you want to close position for ${symbol}?`)) {
            try {
                await api.closePosition(symbol);
            } catch (e: any) {
                alert(`Failed to close position: ${e.message}`);
            }
        }
    };

    const handleCancelOrder = async (orderId: string, symbol: string) => {
        try {
            await api.cancelOrder(orderId, symbol);
        } catch (e: any) {
            alert(`Failed to cancel order: ${e.message}`);
        }
    };

    return (
        <div className="flex flex-col h-full bg-card border-t border-card-border overflow-hidden">
            {/* Tabs Header */}
            <div className="flex items-center px-4 border-b border-card-border bg-card-hover shrink-0">
                {["Positions", "Open Orders", "Trade History", "Logs", "Alerts"].map((tab) => {
                    const key = tab.split(" ")[0].toLowerCase();
                    const count = key === 'positions' ? positions.length : key === 'open' ? openOrders.length : 0;

                    return (
                        <button
                            key={key}
                            onClick={() => setActiveTab(key)}
                            className={cn(
                                "px-4 py-2 text-xs font-medium transition-colors relative h-10 flex items-center gap-2",
                                activeTab === key ? "text-white" : "text-gray-500 hover:text-gray-300"
                            )}
                        >
                            {tab}
                            {count > 0 && (
                                <span className="px-1.5 py-0.5 rounded-full bg-white/10 text-[10px] text-gray-300">{count}</span>
                            )}
                            {activeTab === key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand" />}
                        </button>
                    );
                })}
                <div className="ml-auto flex items-center gap-2">
                    <label className="flex items-center gap-2 text-[10px] text-gray-500 cursor-pointer hover:text-gray-300">
                        <input type="checkbox" className="rounded bg-gray-800 border-gray-700 text-brand focus:ring-0" />
                        Hide other symbols
                    </label>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto min-h-0">
                <table className="w-full text-left border-collapse">
                    <thead className="sticky top-0 bg-card z-10">
                        <tr className="text-[10px] text-gray-500 border-b border-card-border/50">
                            {activeTab === "positions" && (
                                <>
                                    <th className="px-4 py-2 font-medium">SYMBOL</th>
                                    <th className="px-4 py-2 font-medium text-right">SIZE</th>
                                    <th className="px-4 py-2 font-medium text-right">ENTRY PRICE</th>
                                    <th className="px-4 py-2 font-medium text-right">MARK PRICE</th>
                                    <th className="px-4 py-2 font-medium text-right">PNL (ROE%)</th>
                                    <th className="px-4 py-2 font-medium text-right">ACTION</th>
                                </>
                            )}
                            {activeTab === "open" && (
                                <>
                                    <th className="px-4 py-2 font-medium">SYMBOL</th>
                                    <th className="px-4 py-2 font-medium text-right">SIZE</th>
                                    <th className="px-4 py-2 font-medium text-right">PRICE</th>
                                    <th className="px-4 py-2 font-medium text-right">FILLED</th>
                                    <th className="px-4 py-2 font-medium text-right">STATUS</th>
                                    <th className="px-4 py-2 font-medium text-right">ACTION</th>
                                </>
                            )}
                            {activeTab === "logs" && (
                                <>
                                    <th className="px-4 py-2 font-medium w-32">TIME</th>
                                    <th className="px-4 py-2 font-medium w-24">TYPE</th>
                                    <th className="px-4 py-2 font-medium">MESSAGE</th>
                                </>
                            )}
                        </tr>
                    </thead>
                    <tbody>
                        {/* Empty States */}
                        {activeTab === "positions" && positions.length === 0 && (
                            <tr><td colSpan={6} className="text-center py-12 text-gray-500 text-xs">No open positions</td></tr>
                        )}
                        {activeTab === "open" && openOrders.length === 0 && (
                            <tr><td colSpan={6} className="text-center py-12 text-gray-500 text-xs">No open orders</td></tr>
                        )}
                        {activeTab === "logs" && logs.length === 0 && (
                            <tr><td colSpan={3} className="text-center py-12 text-gray-500 text-xs">No logs available</td></tr>
                        )}

                        {/* Positions Rows */}
                        {activeTab === "positions" && positions.map((pos, i) => (
                            <tr key={i} className="text-xs border-b border-card-border/30 hover:bg-white/5 group">
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <div className={cn("w-1 h-8 rounded-full", pos.side === "long" ? "bg-trade-long" : "bg-trade-short")} />
                                        <div>
                                            <div className="font-bold text-white">{pos.symbol}</div>
                                            <div className={cn("text-[10px]", pos.side === "long" ? "text-trade-long" : "text-trade-short")}>
                                                {pos.side === "long" ? "LONG" : "SHORT"} {pos.percentage}x
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-right font-mono text-gray-300">{pos.size}</td>
                                <td className="px-4 py-3 text-right font-mono text-white">{pos.entry_price}</td>
                                <td className="px-4 py-3 text-right font-mono text-white">{pos.mark_price}</td>
                                <td className="px-4 py-3 text-right font-mono">
                                    <div className={cn(pos.unrealized_pnl >= 0 ? "text-trade-long" : "text-trade-short")}>
                                        {pos.unrealized_pnl >= 0 ? "+" : ""}{pos.unrealized_pnl} USDT
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-right">
                                    <button
                                        onClick={() => handleClosePosition(pos.symbol)}
                                        className="px-2 py-1 text-[10px] border border-card-border rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                                    >
                                        Close
                                    </button>
                                </td>
                            </tr>
                        ))}

                        {/* Open Orders Rows */}
                        {activeTab === "open" && openOrders.map((order, i) => (
                            <tr key={i} className="text-xs border-b border-card-border/30 hover:bg-white/5 group">
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <div className={cn("w-1 h-8 rounded-full", order.side === "buy" ? "bg-trade-long" : "bg-trade-short")} />
                                        <div>
                                            <div className="font-bold text-white">{order.symbol}</div>
                                            <div className={cn("text-[10px]", order.side === "buy" ? "text-trade-long" : "text-trade-short")}>
                                                {order.side === "buy" ? "BUY" : "SELL"}
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-right font-mono text-gray-300">{order.quantity}</td>
                                <td className="px-4 py-3 text-right font-mono text-white">{order.price || "Market"}</td>
                                <td className="px-4 py-3 text-right font-mono text-gray-400">{order.filled_qty || 0}</td>
                                <td className="px-4 py-3 text-right font-mono text-brand">{order.status}</td>
                                <td className="px-4 py-3 text-right">
                                    <button
                                        onClick={() => handleCancelOrder(order.order_id, order.symbol)}
                                        className="px-2 py-1 text-[10px] border border-card-border rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                                    >
                                        Cancel
                                    </button>
                                </td>
                            </tr>
                        ))}

                        {/* Logs Rows */}
                        {activeTab === "logs" && logs.map((log, i) => (
                            <tr key={i} className="text-xs border-b border-card-border/30 hover:bg-white/5 font-mono">
                                <td className="px-4 py-2 text-gray-500">{log.time}</td>
                                <td className="px-4 py-2 text-brand">{log.type}</td>
                                <td className="px-4 py-2 text-gray-300">{log.message}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default PositionsTable;
