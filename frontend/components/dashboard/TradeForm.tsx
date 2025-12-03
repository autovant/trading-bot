"use client";

import React, { useState, useEffect } from "react";
import { cn } from "@/utils/cn";
import { Wallet, Settings2, ArrowRightLeft, Loader2 } from "lucide-react";
import { api } from "@/utils/api";
import { useMarketData } from "@/contexts/MarketDataContext";
import { useAccount } from "@/contexts/AccountContext";

const TradeForm = () => {
    const { marketData, lastPrice } = useMarketData();
    const { summary } = useAccount();
    const [side, setSide] = useState<"long" | "short">("long");
    const [orderType, setOrderType] = useState("limit");
    const [leverage, setLeverage] = useState(20);
    const [price, setPrice] = useState("");
    const [size, setSize] = useState("0.001");
    const [loading, setLoading] = useState(false);

    const symbol = marketData?.symbol || "BTC-PERP";

    useEffect(() => {
        if (lastPrice && !price) {
            setPrice(lastPrice.toString());
        }
    }, [lastPrice]);

    const handleSubmit = async () => {
        setLoading(true);
        try {
            await api.placeOrder({
                symbol: symbol,
                side: side === "long" ? "buy" : "sell",
                type: orderType as "limit" | "market",
                quantity: parseFloat(size),
                price: orderType === "limit" ? parseFloat(price) : undefined
            });
            alert("Order submitted successfully!");
        } catch (e: any) {
            alert(`Failed to place order: ${e.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-full bg-card border border-card-border rounded-lg overflow-hidden">
            {/* Header */}
            <div className="flex border-b border-card-border">
                <button
                    onClick={() => setSide("long")}
                    className={cn(
                        "flex-1 py-3 text-sm font-medium transition-colors relative",
                        side === "long" ? "text-white bg-card-hover" : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    Buy / Long
                    {side === "long" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-trade-long" />}
                </button>
                <button
                    onClick={() => setSide("short")}
                    className={cn(
                        "flex-1 py-3 text-sm font-medium transition-colors relative",
                        side === "short" ? "text-white bg-card-hover" : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    Sell / Short
                    {side === "short" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-trade-short" />}
                </button>
            </div>

            <div className="p-4 flex flex-col gap-4 flex-1 overflow-y-auto">
                <div className="flex justify-between items-center text-xs text-gray-400">
                    <span className="flex items-center gap-1"><Wallet className="w-3 h-3" /> Avail</span>
                    <span className="text-white font-mono">{summary?.equity ? `$${summary.equity.toLocaleString()}` : "Loading..."}</span>
                </div>

                {/* Order Type */}
                <div className="flex flex-col gap-1.5">
                    <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Order Type</label>
                    <div className="relative">
                        <select
                            value={orderType}
                            onChange={(e) => setOrderType(e.target.value)}
                            className="w-full bg-black/20 border border-card-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brand appearance-none"
                        >
                            <option value="limit">Limit Order</option>
                            <option value="market">Market Order</option>
                            <option value="stop">Stop Limit</option>
                        </select>
                        <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-500">
                            ▼
                        </div>
                    </div>
                </div>

                {/* Inputs */}
                <div className="flex flex-col gap-3">
                    <div className="relative group">
                        <label className="absolute left-3 top-2 text-[10px] text-gray-500 group-focus-within:text-brand transition-colors">Price</label>
                        <input
                            type="text"
                            value={price}
                            onChange={(e) => setPrice(e.target.value)}
                            disabled={orderType === "market"}
                            className={cn(
                                "w-full bg-black/20 border border-card-border rounded px-3 pt-5 pb-2 text-right text-sm font-mono text-white focus:outline-none focus:border-brand transition-colors",
                                orderType === "market" && "opacity-50 cursor-not-allowed"
                            )}
                            placeholder={orderType === "market" ? "Market Price" : "0.00"}
                        />
                        <span className="absolute right-3 top-1/2 -translate-y-1/2 mt-1.5 text-xs text-gray-600">USDT</span>
                    </div>

                    <div className="relative group">
                        <label className="absolute left-3 top-2 text-[10px] text-gray-500 group-focus-within:text-brand transition-colors">Size</label>
                        <input
                            type="text"
                            value={size}
                            onChange={(e) => setSize(e.target.value)}
                            className="w-full bg-black/20 border border-card-border rounded px-3 pt-5 pb-2 text-right text-sm font-mono text-white focus:outline-none focus:border-brand transition-colors"
                        />
                        <span className="absolute right-3 top-1/2 -translate-y-1/2 mt-1.5 text-xs text-gray-600">BTC</span>
                    </div>
                </div>

                {/* Slider */}
                <div className="py-2">
                    <div className="flex justify-between mb-2">
                        <span className="text-[10px] text-gray-500">Leverage</span>
                        <span className="text-xs font-mono text-brand">{leverage}x</span>
                    </div>
                    <input
                        type="range"
                        min="1"
                        max="100"
                        value={leverage}
                        onChange={(e) => setLeverage(parseInt(e.target.value))}
                        className="w-full h-1 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-brand"
                    />
                    <div className="flex justify-between mt-1 text-[10px] text-gray-600 font-mono">
                        <span>1x</span>
                        <span>25x</span>
                        <span>50x</span>
                        <span>75x</span>
                        <span>100x</span>
                    </div>
                </div>

                {/* Summary */}
                <div className="mt-auto space-y-2 p-3 bg-black/20 rounded border border-card-border/50">
                    <div className="flex justify-between text-xs">
                        <span className="text-gray-500">Cost</span>
                        <span className="text-white font-mono">{(parseFloat(price || "0") * parseFloat(size || "0") / leverage).toFixed(2)} USDT</span>
                    </div>
                    <div className="flex justify-between text-xs">
                        <span className="text-gray-500">Fee</span>
                        <span className="text-white font-mono">{(parseFloat(price || "0") * parseFloat(size || "0") * 0.0006).toFixed(2)} USDT</span>
                    </div>
                </div>

                <button
                    onClick={handleSubmit}
                    disabled={loading}
                    className={cn(
                        "w-full py-3 rounded font-bold text-white shadow-lg transition-all active:scale-[0.98] flex items-center justify-center gap-2",
                        side === "long"
                            ? "bg-trade-long hover:bg-trade-long/90 shadow-trade-long/20"
                            : "bg-trade-short hover:bg-trade-short/90 shadow-trade-short/20",
                        loading && "opacity-70 cursor-not-allowed"
                    )}
                >
                    {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                    {side === "long" ? `Buy / Long ${symbol.split("-")[0]}` : `Sell / Short ${symbol.split("-")[0]}`}
                </button>
            </div>
        </div>
    );
};

export default TradeForm;
