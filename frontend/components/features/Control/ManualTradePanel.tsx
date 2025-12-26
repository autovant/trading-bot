"use client";

import React, { useState } from "react";
import { cn } from "@/utils/cn";
import { Zap, TrendingUp, TrendingDown } from "lucide-react";

import { useAccount } from "@/contexts/AccountContext";
import { useMarketData } from "@/contexts/MarketDataContext";

const ManualTradePanel = () => {
    const [side, setSide] = useState<'buy' | 'sell'>('buy');
    const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
    const [size, setSize] = useState("");
    const [price, setPrice] = useState("");

    const { executeOrder, summary } = useAccount();
    const { marketData, lastPrice } = useMarketData();
    const symbol = marketData?.symbol || "BTCUSDT";

    const maxBuySize = (summary?.free_margin && lastPrice) ? (summary.free_margin * 5) / lastPrice : 0;

    const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const pct = parseFloat(e.target.value);
        if (maxBuySize > 0) {
            setSize(((pct / 100) * maxBuySize).toFixed(4));
        }
    };

    const handleExecute = () => {
        if (!size) return;
        executeOrder({
            symbol,
            side,
            type: orderType,
            quantity: parseFloat(size),
            price: price ? parseFloat(price) : undefined
        });
    };

    return (
        <div className="glass-card rounded-xl p-5 relative overflow-hidden group">
            {/* Ambient Background Glow */}
            <div className={cn(
                "absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl opacity-10 blur-3xl rounded-full pointer-events-none transition-colors duration-500",
                side === 'buy' ? "from-trade-long to-transparent" : "from-trade-short to-transparent"
            )} />

            <div className="flex items-center justify-between mb-5 relative z-10">
                <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-brand-secondary" />
                    <h3 className="text-sm font-bold uppercase tracking-widest text-gray-300">Execution</h3>
                </div>
                <span className="text-[10px] font-mono font-bold text-brand-secondary bg-brand-secondary/10 px-2 py-1 rounded border border-brand-secondary/20 shadow-[0_0_10px_rgba(0,224,255,0.1)]">
                    {symbol}
                </span>
            </div>

            {/* Buy/Sell Toggle - Futuristic Segmented Control */}
            <div className="relative flex bg-gray-950 p-1 rounded-lg border border-gray-800 mb-5 shadow-inner">
                <button
                    onClick={() => setSide('buy')}
                    className={cn(
                        "flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded-md transition-all duration-300 uppercase tracking-wide relative overflow-hidden",
                        side === 'buy'
                            ? "bg-trade-long/20 text-trade-long shadow-[0_0_15px_rgba(0,255,157,0.2)] border border-trade-long/30"
                            : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                    )}
                >
                    <TrendingUp className="w-3 h-3" />
                    Long
                </button>
                <div className="w-px bg-gray-800 mx-1"></div>
                <button
                    onClick={() => setSide('sell')}
                    className={cn(
                        "flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded-md transition-all duration-300 uppercase tracking-wide relative overflow-hidden",
                        side === 'sell'
                            ? "bg-trade-short/20 text-trade-short shadow-[0_0_15px_rgba(255,59,48,0.2)] border border-trade-short/30"
                            : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                    )}
                >
                    <TrendingDown className="w-3 h-3" />
                    Short
                </button>
            </div>

            {/* Market/Limit Toggle */}
            <div className="flex gap-2 mb-4">
                {['market', 'limit'].map((type) => (
                    <button
                        key={type}
                        onClick={() => setOrderType(type as 'market' | 'limit')}
                        className={cn(
                            "flex-1 py-1.5 text-[10px] font-bold rounded border transition-all uppercase tracking-wider",
                            orderType === type
                                ? "bg-gray-800 border-gray-600 text-white shadow-lg"
                                : "bg-transparent border-gray-800 text-gray-500 hover:border-gray-700"
                        )}
                    >
                        {type}
                    </button>
                ))}
            </div>

            {/* Size Input & Slider */}
            <div className="mb-5 space-y-3">
                <div className="flex justify-between items-end">
                    <label className="text-[10px] uppercase tracking-wider font-bold text-gray-400">Size (BTC)</label>
                    <span className="text-[10px] font-mono text-brand-secondary">Max: {maxBuySize.toFixed(3)}</span>
                </div>

                <div className="flex items-center gap-3">
                    <div className="relative flex-1 group/slider">
                        <div className="absolute top-1/2 -mt-0.5 w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                            <div className="h-full bg-brand-secondary/50" style={{ width: `${(parseFloat(size) / maxBuySize * 100) || 0}%` }}></div>
                        </div>
                        <input
                            type="range"
                            min="0"
                            max="100"
                            step="1"
                            defaultValue="0"
                            onChange={handleSliderChange}
                            className="absolute top-0 w-full h-full opacity-0 cursor-pointer"
                        />
                        <div
                            className="w-3 h-3 bg-brand-secondary rounded-full shadow-[0_0_10px_rgba(0,224,255,0.8)] absolute top-1/2 -mt-1.5 pointer-events-none transition-all duration-75"
                            style={{ left: `calc(${Math.min(100, (parseFloat(size) / maxBuySize) * 100) || 0}% - 6px)` }}
                        ></div>
                    </div>
                    <input
                        type="text"
                        value={size}
                        onChange={(e) => setSize(e.target.value)}
                        className="w-24 bg-gray-950/50 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-secondary/50 focus:ring-1 focus:ring-brand-secondary/50 font-mono text-right transition-all"
                        placeholder="0.00"
                    />
                </div>
            </div>

            {orderType === 'limit' && (
                <div className="mb-5 animate-in fade-in slide-in-from-top-1 duration-200">
                    <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-400 mb-1.5">Limit Price (USDT)</label>
                    <div className="relative">
                        <span className="absolute left-3 top-2.5 text-gray-600 text-xs">$</span>
                        <input
                            type="text"
                            value={price}
                            onChange={(e) => setPrice(e.target.value)}
                            className="w-full bg-gray-950/50 border border-gray-800 rounded px-3 py-2 pl-6 text-sm text-gray-100 focus:outline-none focus:border-brand-secondary/50 focus:ring-1 focus:ring-brand-secondary/50 font-mono transition-all"
                            placeholder="0.00"
                        />
                    </div>
                </div>
            )}

            {/* Execute Button */}
            <button
                onClick={handleExecute}
                disabled={!size}
                className={cn(
                    "w-full py-3 rounded-lg font-bold text-sm text-black transition-all duration-300 uppercase tracking-wider shadow-lg hover:shadow-xl hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none",
                    side === 'buy'
                        ? "bg-trade-long hover:bg-trade-long/90 shadow-[0_0_20px_rgba(0,255,157,0.3)]"
                        : "bg-trade-short hover:bg-trade-short/90 shadow-[0_0_20px_rgba(255,59,48,0.3)]"
                )}
            >
                {side === 'buy' ? "Execute Long" : "Execute Short"}
            </button>
        </div>
    );
};

export default ManualTradePanel;
