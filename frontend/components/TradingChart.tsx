"use client";

import { createChart, ColorType, IChartApi, ISeriesApi, CrosshairMode, Time } from 'lightweight-charts';
import React, { useEffect, useRef, useState } from 'react';
import { cn } from "@/utils/cn";
import { api } from "@/utils/api";
import { useMarketData } from "@/contexts/MarketDataContext";

interface ChartProps {
    className?: string;
}

export const TradingChart: React.FC<ChartProps> = ({ className }) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const [timeframe, setTimeframe] = useState("15m");
    const [, setIsLoading] = useState(true);

    const { lastPrice, isConnected, marketData } = useMarketData();
    const symbol = marketData?.symbol || "BTCUSDT";

    // Fetch Historical Data
    useEffect(() => {
        const fetchHistory = async () => {
            setIsLoading(true);
            try {
                const data = await api.getKlines(symbol, timeframe, 1000);
                if (seriesRef.current) {
                    seriesRef.current.setData(data);
                }
            } catch (err) {
                console.error("Failed to fetch history:", err);
            } finally {
                setIsLoading(false);
            }
        };

        fetchHistory();
    }, [timeframe, symbol]);

    // Initialize Chart
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const handleResize = () => {
            chartRef.current?.applyOptions({ width: chartContainerRef.current?.clientWidth, height: chartContainerRef.current?.clientHeight });
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#0b1020' },
                textColor: '#9fb3ce',
                fontFamily: 'Space Grotesk, JetBrains Mono, monospace',
            },
            grid: {
                vertLines: { color: '#1c2639' },
                horzLines: { color: '#1c2639' },
            },
            width: chartContainerRef.current.clientWidth,
            height: chartContainerRef.current.clientHeight,
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    color: '#2b3348',
                    width: 1,
                    style: 3,
                    labelBackgroundColor: '#7DF3C6',
                },
                horzLine: {
                    color: '#2b3348',
                    width: 1,
                    style: 3,
                    labelBackgroundColor: '#7DF3C6',
                },
            },
            timeScale: {
                borderColor: '#1c2639',
                timeVisible: true,
            },
            rightPriceScale: {
                borderColor: '#1c2639',
                textColor: '#cbd5e1',
            },
        });

        chartRef.current = chart;

        const newSeries = chart.addCandlestickSeries({
            upColor: '#52E3B8',
            downColor: '#F76668',
            borderVisible: false,
            wickUpColor: '#52E3B8',
            wickDownColor: '#F76668',
        });

        seriesRef.current = newSeries;

        // Initial empty data, will be populated by fetchHistory
        newSeries.setData([]);

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    // Update with Real-time Data
    useEffect(() => {
        if (seriesRef.current && lastPrice > 0) {
            const time = Math.floor(new Date().getTime() / 1000) as Time;
            seriesRef.current.update({
                time: time,
                open: lastPrice,
                high: lastPrice,
                low: lastPrice,
                close: lastPrice
            });
        }
    }, [lastPrice]);

    return (
        <div className={cn("relative w-full h-full overflow-hidden bg-gradient-to-b from-[#0d1324] via-[#0b0f1d] to-[#090d17] group", className)}>
            <div className="absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/5 to-transparent pointer-events-none" />

            {/* Toolbar */}
            <div className="absolute top-3 left-3 z-10 flex flex-wrap items-center gap-2 rounded-full border border-card-border/70 bg-card/80 px-3 py-2 shadow-[0_10px_40px_-24px_rgba(0,0,0,0.8)]">
                <div className="flex items-center gap-2 pr-3 border-r border-card-border/70">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-card-border/60 bg-brand/10 text-brand font-semibold text-xs">
                        {symbol.slice(0, 3)}
                    </div>
                    <div className="leading-tight">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-gray-400">Symbol</div>
                        <div className="text-xs font-semibold text-white">{symbol}</div>
                    </div>
                </div>

                <div className="flex items-center gap-1">
                    {["1m", "5m", "15m", "1H", "4H", "D"].map((tf) => (
                        <button
                            key={tf}
                            onClick={() => setTimeframe(tf)}
                            className={cn(
                                "px-2.5 py-1 text-[11px] font-semibold rounded-full border border-transparent transition-colors",
                                timeframe === tf
                                    ? "bg-brand/20 text-white border-brand/40 shadow-[0_5px_20px_-10px_rgba(125,243,198,0.7)]"
                                    : "text-gray-400 hover:text-white hover:border-card-border/70"
                            )}
                        >
                            {tf}
                        </button>
                    ))}
                </div>

                <div className="hidden sm:flex items-center gap-2 pl-3 ml-1 border-l border-card-border/70 text-[11px] text-gray-400">
                    <div className={cn(
                        "flex items-center gap-1 rounded-full px-2 py-1 border border-card-border/70",
                        isConnected ? "text-trade-long" : "text-trade-short"
                    )}>
                        <span className="inline-block h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: isConnected ? "#52E3B8" : "#F76668" }} />
                        {isConnected ? "Live" : "Reconnecting"}
                    </div>
                    <span className="text-gray-500">Depth limited to top-of-book</span>
                </div>
            </div>

            {/* Loading / Connection State Overlay */}
            {!isConnected && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-gradient-to-b from-[#0a0f1f]/90 to-[#060914]/95 backdrop-blur-sm">
                    <div className="rounded-full border border-card-border/80 px-4 py-2 text-xs text-gray-300 animate-pulse bg-card/70">
                        Connecting to market data...
                    </div>
                </div>
            )}

            <div ref={chartContainerRef} className="w-full h-full" />
        </div>
    );
};
