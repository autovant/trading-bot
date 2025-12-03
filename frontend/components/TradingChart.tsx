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
    const [isLoading, setIsLoading] = useState(true);

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
                background: { type: ColorType.Solid, color: '#0a0a0a' },
                textColor: '#525252',
                fontFamily: 'JetBrains Mono, monospace',
            },
            grid: {
                vertLines: { color: '#1f1f1f' },
                horzLines: { color: '#1f1f1f' },
            },
            width: chartContainerRef.current.clientWidth,
            height: chartContainerRef.current.clientHeight,
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    color: '#333',
                    width: 1,
                    style: 3,
                    labelBackgroundColor: '#0066FF',
                },
                horzLine: {
                    color: '#333',
                    width: 1,
                    style: 3,
                    labelBackgroundColor: '#0066FF',
                },
            },
            timeScale: {
                borderColor: '#1f1f1f',
                timeVisible: true,
            },
            rightPriceScale: {
                borderColor: '#1f1f1f',
            },
        });

        chartRef.current = chart;

        const newSeries = chart.addCandlestickSeries({
            upColor: '#00C853',
            downColor: '#FF3D00',
            borderVisible: false,
            wickUpColor: '#00C853',
            wickDownColor: '#FF3D00',
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
        <div className={cn("relative w-full h-full bg-card overflow-hidden group", className)}>
            {/* Toolbar */}
            <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-card/80 backdrop-blur border border-card-border rounded-lg p-1">
                <div className="flex items-center gap-1 border-r border-card-border pr-2 mr-1">
                    <div className="w-5 h-5 rounded bg-brand/20 flex items-center justify-center text-[10px] font-bold text-brand">B</div>
                    <span className="text-xs font-bold text-white">BTC-PERP</span>
                </div>

                <div className="h-4 w-px bg-gray-800" />

                <div className="flex gap-1">
                    {["1m", "5m", "15m", "1H", "4H", "D"].map((tf) => (
                        <button
                            key={tf}
                            onClick={() => setTimeframe(tf)}
                            className={cn(
                                "px-2 py-1 text-[10px] font-medium rounded transition-colors",
                                timeframe === tf ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                            )}
                        >
                            {tf}
                        </button>
                    ))}
                </div>
            </div>

            {/* Loading / Connection State Overlay */}
            {!isConnected && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                    <div className="text-xs text-gray-400 animate-pulse">Connecting to Market Data...</div>
                </div>
            )}

            <div ref={chartContainerRef} className="w-full h-full" />
        </div>
    );
};
