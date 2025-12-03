"use client";

import React, { useState } from "react";
import { cn } from "@/utils/cn";

import { useAccount } from "@/contexts/AccountContext";
import { useMarketData } from "@/contexts/MarketDataContext";

const ManualTradePanel = () => {
    const [side, setSide] = useState<'buy' | 'sell'>('buy');
    const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
    const [size, setSize] = useState("");
    const [price, setPrice] = useState("");

    const { executeOrder } = useAccount();
    const { marketData } = useMarketData();
    const symbol = marketData?.symbol || "BTCUSDT";

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
        <div className="bg-card p-3 flex flex-col gap-3 flex-1">
            <div className="flex items-center justify-between">
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">Manual Overrides</h3>
            </div>

            {/* Side Selector */}
            <div className="flex bg-black/20 p-1 rounded-lg">
                <button
                    onClick={() => setSide('buy')}
                    className={cn(
                        "flex-1 py-1.5 text-xs font-medium rounded transition-all",
                        side === 'buy' ? "bg-trade-long text-white shadow-lg" : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    Buy / Long
                </button>
                <button
                    onClick={() => setSide('sell')}
                    className={cn(
                        "flex-1 py-1.5 text-xs font-medium rounded transition-all",
                        side === 'sell' ? "bg-trade-short text-white shadow-lg" : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    Sell / Short
                </button>
            </div>

            {/* Order Type */}
            <div className="flex gap-2 text-[10px]">
                <button
                    onClick={() => setOrderType('market')}
                    className={cn(
                        "px-3 py-1 rounded border transition-colors",
                        orderType === 'market' ? "border-brand text-brand bg-brand/10" : "border-card-border text-gray-500 hover:border-gray-600"
                    )}
                >
                    Market
                </button>
                <button
                    onClick={() => setOrderType('limit')}
                    className={cn(
                        "px-3 py-1 rounded border transition-colors",
                        orderType === 'limit' ? "border-brand text-brand bg-brand/10" : "border-card-border text-gray-500 hover:border-gray-600"
                    )}
                >
                    Limit
                </button>
            </div>

            {/* Inputs */}
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <label className="text-[10px] text-gray-500">Size (BTC)</label>
                    <input
                        type="text"
                        value={size}
                        onChange={(e) => setSize(e.target.value)}
                        className="bg-black/20 border border-card-border rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-brand font-mono"
                        placeholder="0.00"
                    />
                </div>
                {orderType === 'limit' && (
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-gray-500">Price (USDT)</label>
                        <input
                            type="text"
                            value={price}
                            onChange={(e) => setPrice(e.target.value)}
                            className="bg-black/20 border border-card-border rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-brand font-mono"
                            placeholder="0.00"
                        />
                    </div>
                )}
            </div>

            {/* Action Button */}
            <button
                onClick={handleExecute}
                className={cn(
                    "mt-auto w-full py-2.5 rounded font-bold text-xs text-white transition-transform active:scale-95",
                    side === 'buy' ? "bg-trade-long hover:bg-trade-long/90" : "bg-trade-short hover:bg-trade-short/90"
                )}
            >
                {side === 'buy' ? "Buy / Long" : "Sell / Short"} BTC
            </button>
        </div>
    );
};

export default ManualTradePanel;
