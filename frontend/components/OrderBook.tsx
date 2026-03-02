
import React from 'react';
import { OrderBookItem } from '@/types';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { cn } from '@/lib/utils';

interface OrderBookProps {
    bids: OrderBookItem[];
    asks: OrderBookItem[];
    currentPrice: number;
    className?: string; // Add className prop for flexibility
}

const DepthRow: React.FC<{ item: OrderBookItem; type: 'bid' | 'ask' }> = ({ item, type }) => {
    const bgClass = type === 'bid' ? 'bg-accent-success' : 'bg-accent-danger';
    const textClass = type === 'bid' ? 'text-accent-success' : 'text-accent-danger';

    return (
        <div className="relative flex items-center justify-between py-0.5 px-3 text-xs font-mono group hover:bg-white/5 cursor-pointer">
            {/* Depth Bar */}
            <div
                className={cn(
                    `absolute top-0 right-0 bottom-0 opacity-10 transition-all duration-300`,
                    bgClass
                )}
                style={{ width: `${item.percent}%` }}
            />

            <span className={cn(textClass, "relative z-10")}>
                {item.price.toFixed(1)}
            </span>
            <span className="text-text-primary relative z-10">
                {item.size.toFixed(3)}
            </span>
            <span className="text-text-tertiary relative z-10 text-right w-12">
                {item.total.toFixed(2)}
            </span>
        </div>
    );
};

export const OrderBook: React.FC<OrderBookProps> = ({ bids, asks, currentPrice, className }) => {
    // Take top 14 of each
    const visibleAsks = asks.slice(0, 14);
    // Reverse asks to show lowest ask at bottom of the ask stack (closest to spread)
    const displayAsks = [...visibleAsks].reverse();

    const visibleBids = bids.slice(0, 14);

    return (
        <div className={cn("flex flex-col h-full", className)}>
            <div className="px-3 py-2.5 border-b border-white/5 flex justify-between items-center gap-4">
                <span className="text-sm font-medium text-text-secondary shrink-0">Order Book</span>
                <div className="flex items-center gap-1.5 text-[10px] text-text-tertiary shrink-0">
                    <span>Spread:</span>
                    <span className="text-text-primary font-mono">0.5</span>
                </div>
            </div>

            {/* Header */}
            <div className="flex justify-between px-3 py-2 text-[10px] text-text-tertiary uppercase tracking-wider">
                <span>Price (USDT)</span>
                <span>Size (BTC)</span>
                <span>Total</span>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col min-h-0">
                {/* Asks (Red) */}
                <div className="flex flex-col justify-end">
                    {displayAsks.map((ask, i) => (
                        <DepthRow key={`ask-${i}`} item={ask} type="ask" />
                    ))}
                </div>

                {/* Current Price Banner */}
                <div className="py-2 my-1 border-y border-white/5 bg-black/30 flex items-center justify-center gap-2 backdrop-blur-sm sticky top-0 bottom-0 z-20">
                    <span className={cn(
                        "text-lg font-mono font-medium",
                        "text-accent-success" // Dynamic color based on tick would be better but random for now matching studio
                    )}>
                        {currentPrice.toFixed(1)}
                    </span>
                    <ArrowUp size={14} className="text-accent-success" />
                </div>

                {/* Bids (Green) */}
                <div>
                    {visibleBids.map((bid, i) => (
                        <DepthRow key={`bid-${i}`} item={bid} type="bid" />
                    ))}
                </div>
            </div>

            {/* OBI Indicator */}
            <div className="p-3 border-t border-white/5">
                <div className="flex justify-between text-[10px] text-text-tertiary mb-1">
                    <span>Bearish</span>
                    <span>Neutral</span>
                    <span>Bullish</span>
                </div>
                <div className="h-1.5 w-full bg-card rounded-full overflow-hidden flex">
                    <div className="h-full bg-accent-danger w-[40%]"></div>
                    <div className="h-full bg-accent-warning w-[10%]"></div>
                    <div className="h-full bg-accent-success w-[50%]"></div>
                </div>
            </div>
        </div>
    );
};
