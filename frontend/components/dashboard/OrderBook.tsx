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
        <div className="flex h-full flex-col overflow-hidden bg-gradient-to-b from-[#0f1423] via-[#0b0f1d] to-[#090d17]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-card-border/70 bg-card/60 backdrop-blur">
                <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-brand animate-pulse" />
                    <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-300">Order Book</h3>
                </div>
                <div className="text-[11px] text-gray-400">
                    Spread <span className="text-gray-100 font-semibold ml-1">{spread}</span>
                </div>
            </div>

            <div className="px-4 py-2 text-[10px] uppercase tracking-[0.16em] text-gray-500 border-b border-card-border/50">
                Top of book feed (Bid / Ask)
            </div>

            <div className="flex-1 overflow-y-auto relative min-h-0">
                <div className="px-4 pt-2 pb-3 space-y-2">
                    <div className="text-[11px] text-gray-500 grid grid-cols-3 mb-1">
                        <span>Price</span>
                        <span className="text-right">Size</span>
                        <span className="text-right">Total</span>
                    </div>

                    <div className="space-y-1.5">
                        {asks.map((ask, i) => (
                            <div key={i} className="relative overflow-hidden rounded-lg border border-card-border/60 bg-trade-short/5 px-3 py-2">
                                <div
                                    className="absolute inset-y-0 right-0 bg-gradient-to-l from-trade-short/15 to-transparent"
                                    style={{ width: `${ask.depth}%` }}
                                />
                                <div className="grid grid-cols-3 text-xs font-mono relative z-10">
                                    <span className="text-trade-short">{ask.price.toFixed(1)}</span>
                                    <span className="text-right text-gray-200">{ask.size}</span>
                                    <span className="text-right text-gray-500">{ask.total}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="sticky top-0 flex items-center justify-center gap-2 px-4 py-3 backdrop-blur bg-card/80 border-y border-card-border/70">
                    <span className={cn("text-xl font-bold font-mono", (lastPrice || 0) >= (marketData?.best_bid || 0) ? "text-trade-long" : "text-trade-short")}>
                        {lastPrice?.toLocaleString() || "---"}
                    </span>
                    <span className="text-xs text-gray-400">USDT</span>
                </div>

                <div className="px-4 pt-3 pb-4 space-y-1.5">
                    {bids.map((bid, i) => (
                        <div key={i} className="relative overflow-hidden rounded-lg border border-card-border/60 bg-trade-long/5 px-3 py-2">
                            <div
                                className="absolute inset-y-0 right-0 bg-gradient-to-l from-trade-long/15 to-transparent"
                                style={{ width: `${bid.depth}%` }}
                            />
                            <div className="grid grid-cols-3 text-xs font-mono relative z-10">
                                <span className="text-trade-long">{bid.price.toFixed(1)}</span>
                                <span className="text-right text-gray-200">{bid.size}</span>
                                <span className="text-right text-gray-500">{bid.total}</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="h-1.5 bg-gray-900/70 flex mt-auto shrink-0">
                <div className="w-[45%] bg-trade-short/80 h-full" />
                <div className="w-[10%] bg-brand/40 h-full" />
                <div className="w-[45%] bg-trade-long/80 h-full" />
            </div>
        </div>
    );
};

export default OrderBook;
