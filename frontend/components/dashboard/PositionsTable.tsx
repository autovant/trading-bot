"use client";

import React, { useState, useEffect, useRef } from "react";
import { cn } from "@/utils/cn";
import { usePositions, useOpenOrders } from "@/contexts/MarketDataContext";
import { api } from "@/utils/api";
import { useVirtualizer } from "@tanstack/react-virtual";
import { PositionResponse, OrderResponse, LogEntry } from "@/types/api";

type ListItem = PositionResponse | OrderResponse | LogEntry;

const PositionsTable = () => {
    const [activeTab, setActiveTab] = useState<"positions" | "open" | "logs">("positions");

    const { data: positionsData } = usePositions();
    const { data: openOrdersData } = useOpenOrders();

    // Ensure data is array
    const positions = positionsData || [];
    const openOrders = openOrdersData || [];

    const [logs, setLogs] = useState<Array<LogEntry>>([]);

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const data = await api.getSystemLogs();
                setLogs(data as LogEntry[]);
            } catch (e) {
                console.error("Failed to fetch logs:", e);
            }
        };

        if (activeTab === "logs") {
            fetchLogs();
            const interval = setInterval(fetchLogs, 2000);
            return () => clearInterval(interval);
        }
    }, [activeTab]);

    const handleClosePosition = async (symbol: string) => {
        if (confirm(`Close position for ${symbol}?`)) {
            try {
                await api.closePosition(symbol);
            } catch (e: unknown) {
                const message = e instanceof Error ? e.message : 'Unknown error';
                alert(`Failed: ${message}`);
            }
        }
    };

    const handleCancelOrder = async (orderId: string, symbol: string) => {
        try {
            await api.cancelOrder(orderId, symbol);
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Unknown error';
            alert(`Failed: ${message}`);
        }
    };

    const tabs = [
        { key: "positions" as const, label: "Positions", count: positions.length },
        { key: "open" as const, label: "Orders", count: openOrders.length },
        { key: "logs" as const, label: "System Logs", count: logs.length },
    ];

    const currentList =
        activeTab === "positions" ? positions :
            activeTab === "open" ? openOrders :
                logs;

    const parentRef = useRef<HTMLDivElement>(null);

    const rowVirtualizer = useVirtualizer({
        count: currentList.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 45,
        overscan: 5,
    });

    return (
        <div className="h-full flex flex-col bg-card/20 backdrop-blur-sm">
            {/* Tab Header with Glass Effect */}
            <div className="flex items-center gap-1 px-4 py-2 border-b border-card-border bg-card/60 relative z-10 box-shadow-[0_2px_10px_rgba(0,0,0,0.1)]">
                {tabs.map((tab) => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={cn(
                            "flex items-center gap-2 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all duration-200",
                            activeTab === tab.key
                                ? "bg-brand-secondary/10 text-brand-secondary border border-brand-secondary/20 shadow-[0_0_10px_rgba(0,224,255,0.1)]"
                                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                        )}
                    >
                        {tab.label}
                        {tab.count > 0 && (
                            <span className={cn(
                                "px-1.5 py-0.5 rounded text-[9px] min-w-[18px] text-center",
                                activeTab === tab.key ? "bg-brand-secondary/20 text-brand-secondary" : "bg-gray-800 text-gray-400"
                            )}>
                                {tab.count}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* Table Content */}
            <div
                ref={parentRef}
                className="flex-1 overflow-auto custom-scrollbar"
                style={{ contain: 'strict' }}
            >
                <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}>
                    <table className="w-full text-left border-collapse absolute top-0 left-0" style={{ transform: `translateY(${rowVirtualizer.getVirtualItems()[0]?.start ?? 0}px)` }}>
                        <thead className="sticky top-0 bg-gray-950/90 backdrop-blur-md border-b border-card-border z-10 text-[10px] uppercase text-gray-500 tracking-wider font-bold h-[40px]">
                            <tr className="bg-gray-900/80">
                                {activeTab === "positions" && (
                                    <>
                                        <th className="px-4 py-3 font-medium">Instrument</th>
                                        <th className="px-4 py-3 font-medium text-right">Size</th>
                                        <th className="px-4 py-3 font-medium text-right">Entry</th>
                                        <th className="px-4 py-3 font-medium text-right">PnL</th>
                                        <th className="px-4 py-3 font-medium text-right">Action</th>
                                    </>
                                )}
                                {activeTab === "open" && (
                                    <>
                                        <th className="px-4 py-3 font-medium">Instrument</th>
                                        <th className="px-4 py-3 font-medium text-right">Volume</th>
                                        <th className="px-4 py-3 font-medium text-right">Price</th>
                                        <th className="px-4 py-3 font-medium text-right">Status</th>
                                        <th className="px-4 py-3 font-medium text-right">Action</th>
                                    </>
                                )}
                                {activeTab === "logs" && (
                                    <>
                                        <th className="px-4 py-3 font-medium w-40">Timestamp</th>
                                        <th className="px-4 py-3 font-medium w-28">Level</th>
                                        <th className="px-4 py-3 font-medium">Message Details</th>
                                    </>
                                )}
                            </tr>
                        </thead>
                        <tbody className="text-xs font-mono">
                            {/* Empty State */}
                            {currentList.length === 0 && (
                                <tr><td colSpan={5} className="py-12 text-center text-gray-600 font-sans text-sm">
                                    {activeTab === "positions" ? "No active positions" : activeTab === "open" ? "No open orders" : "System logs empty"}
                                </td></tr>
                            )}

                            {/* Virtual Rows */}
                            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                                const index = virtualRow.index;
                                const item = currentList[index];

                                return (
                                    <React.Fragment key={virtualRow.key}>
                                        {activeTab === "positions" && (() => {
                                            const pos = item as PositionResponse;
                                            return (
                                                <tr className="border-b border-card-border/50 hover:bg-white/5 transition-colors group h-[45px]">
                                                    <td className="px-4 py-3">
                                                        <div className="flex items-center gap-3">
                                                            <div className={cn("w-1 h-5 rounded-full shadow-[0_0_8px_currentColor]", pos.side === "long" ? "bg-trade-long text-trade-long" : "bg-trade-short text-trade-short")} />
                                                            <div>
                                                                <div className="font-bold text-gray-100">{pos.symbol}</div>
                                                                <div className={cn("text-[10px] font-bold uppercase", pos.side === "long" ? "text-trade-long" : "text-trade-short")}>
                                                                    {pos.side === "long" ? "Long" : "Short"} {pos.percentage}x
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </td>
                                                    <td className="px-4 py-3 text-right text-gray-300 font-bold">{pos.size}</td>
                                                    <td className="px-4 py-3 text-right text-gray-400">{pos.entry_price}</td>
                                                    <td className="px-4 py-3 text-right">
                                                        <span className={cn("font-bold", pos.unrealized_pnl >= 0 ? "text-trade-long text-glow" : "text-trade-short text-glow-red")}>
                                                            {pos.unrealized_pnl >= 0 ? "+" : ""}{pos.unrealized_pnl}
                                                        </span>
                                                    </td>
                                                    <td className="px-4 py-3 text-right">
                                                        <button
                                                            onClick={() => handleClosePosition(pos.symbol)}
                                                            className="px-2 py-1 text-[10px] font-bold uppercase text-gray-500 border border-gray-700 rounded hover:border-trade-short hover:text-trade-short hover:bg-trade-short/10 transition-all"
                                                        >
                                                            Close
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })()}

                                        {activeTab === "open" && (() => {
                                            const order = item as OrderResponse;
                                            return (
                                                <tr className="border-b border-card-border/50 hover:bg-white/5 transition-colors h-[45px]">
                                                    <td className="px-4 py-3">
                                                        <div className="flex items-center gap-3">
                                                            <div className={cn("w-1 h-5 rounded-full", order.side === "buy" ? "bg-trade-long" : "bg-trade-short")} />
                                                            <div>
                                                                <div className="font-bold text-gray-100">{order.symbol}</div>
                                                                <div className={cn("text-[10px] font-bold uppercase", order.side === "buy" ? "text-trade-long" : "text-trade-short")}>
                                                                    {order.side === "buy" ? "Buy" : "Sell"}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </td>
                                                    <td className="px-4 py-3 text-right text-gray-300 font-bold">{order.quantity}</td>
                                                    <td className="px-4 py-3 text-right text-gray-400">{order.price || "Market"}</td>
                                                    <td className="px-4 py-3 text-right text-brand-secondary">{order.status}</td>
                                                    <td className="px-4 py-3 text-right">
                                                        <button
                                                            onClick={() => handleCancelOrder(order.order_id, order.symbol)}
                                                            className="px-2 py-1 text-[10px] font-bold uppercase text-gray-500 border border-gray-700 rounded hover:border-accent-amber hover:text-accent-amber hover:bg-accent-amber/10 transition-all"
                                                        >
                                                            Cancel
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })()}

                                        {activeTab === "logs" && (() => {
                                            const log = item as LogEntry;
                                            return (
                                                <tr className="border-b border-card-border/50 hover:bg-white/5 transition-colors h-[45px]">
                                                    <td className="px-4 py-3 text-gray-500 text-[10px]">{log.timestamp?.split('T')[1]?.split('.')[0] || log.timestamp}</td>
                                                    <td className={cn(
                                                        "px-4 py-3 text-[10px] font-bold uppercase tracking-wider",
                                                        log.level === "ERROR" ? "text-trade-short" :
                                                            log.level === "WARNING" ? "text-accent-amber" : "text-trade-long"
                                                    )}>{log.level}</td>
                                                    <td className="px-4 py-3 text-gray-300">{log.message}</td>
                                                </tr>
                                            );
                                        })()}
                                    </React.Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default PositionsTable;
