"use client";

import React, { useMemo } from "react";
import { cn } from "@/utils/cn";
import { useMarketData } from "@/contexts/MarketDataContext";

const OrderBook = () => {
    const { marketData, lastPrice, isConnected } = useMarketData();

    // Use real data only. If we only have top-of-book, we only show that.
    const { asks, bids, spread } = useMemo(() => {
        if (!marketData || !marketData.best_bid || !marketData.best_ask) return { asks: [], bids: [], spread: 0 };

        const spreadVal = marketData.best_ask - marketData.best_bid;

        return {
            asks: [{
                price: marketData.best_ask,
                size: marketData.ask_size.toFixed(3),
                total: marketData.ask_size.toFixed(3),
                depth: 100 // Full bar for top of book
            }],
            bids: [{
                price: marketData.best_bid,
                size: marketData.bid_size.toFixed(3),
                total: marketData.bid_size.toFixed(3),
                depth: 100
            }],
            spread: spreadVal.toFixed(1)
        };
    }, [marketData]);

    if (!isConnected && !marketData) {
        return (
            <div className="flex flex-col h-full bg-card border-b border-card-border items-center justify-center text-xs text-gray-500">
                <span className="animate-pulse">Connecting...</span>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-card overflow-hidden">
            <div className="px-3 py-2 border-b border-card-border flex justify-between items-center bg-card-hover shrink-0">
                <h3 className="text-xs font-medium text-gray-400">Order Book</h3>
                <div className="text-[10px] text-gray-500">Spread <span className="text-gray-300">{spread}</span></div>
            </div>

            <div className="flex text-[10px] text-gray-500 px-3 py-1 border-b border-card-border/50 shrink-0">
                <div className="flex-1">PRICE (USDT)</div>
                <div className="flex-1 text-right">SIZE (BTC)</div>
                <div className="flex-1 text-right">TOTAL</div>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-hide relative min-h-0">
                {/* Asks */}
                <div className="flex flex-col justify-end">
                    {asks.map((ask, i) => (
                        <div key={i} className="flex items-center px-3 py-0.5 relative hover:bg-white/5 cursor-pointer group">
                            <div
                                className="absolute right-0 top-0 bottom-0 bg-trade-short/10 transition-all duration-300"
                                style={{ width: `${ask.depth}%` }}
                            />
                            <div className="flex-1 text-trade-short text-xs font-mono z-10">{ask.price.toFixed(1)}</div>
                            <div className="flex-1 text-right text-gray-300 text-xs font-mono z-10">{ask.size}</div>
                            <div className="flex-1 text-right text-gray-500 text-xs font-mono z-10">{ask.total}</div>
                        </div>
                    ))}
                </div>

                {/* Current Price */}
                <div className="py-2 my-1 border-y border-card-border bg-card-hover flex items-center justify-center gap-2 sticky top-0 bottom-0 z-20">
                    <span className={cn("text-lg font-bold font-mono", (lastPrice || 0) >= (marketData?.best_bid || 0) ? "text-trade-long" : "text-trade-short")}>
                        {lastPrice?.toLocaleString() || "---"}
                    </span>
                    <span className="text-xs text-gray-500">USDT</span>
                </div>

                {/* Bids */}
                <div className="flex flex-col">
                    {bids.map((bid, i) => (
                        <div key={i} className="flex items-center px-3 py-0.5 relative hover:bg-white/5 cursor-pointer group">
                            <div
                                className="absolute right-0 top-0 bottom-0 bg-trade-long/10 transition-all duration-300"
                                style={{ width: `${bid.depth}%` }}
                            />
                            <div className="flex-1 text-trade-long text-xs font-mono z-10">{bid.price.toFixed(1)}</div>
                            <div className="flex-1 text-right text-gray-300 text-xs font-mono z-10">{bid.size}</div>
                            <div className="flex-1 text-right text-gray-500 text-xs font-mono z-10">{bid.total}</div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Depth Viz */}
            <div className="h-1 bg-gray-800 flex mt-auto shrink-0">
                <div className="w-[40%] bg-trade-short h-full"></div>
                <div className="w-[20%] bg-gray-700 h-full"></div>
                <div className="w-[40%] bg-trade-long h-full"></div>
            </div>
        </div>
    );
};

export default OrderBook;
