
import React, { useState, useMemo } from 'react';
import {
    ComposedChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine,
    Cell,
    ReferenceArea
} from 'recharts';
import { Candle, TradeSuggestion, ExchangeId } from '@/types';
import { SUPPORTED_EXCHANGES, getExchange } from '@/services/exchanges';
import { Maximize2, Activity, BrainCircuit, AlertTriangle, ChevronDown, Check, Globe } from 'lucide-react';
import { cn } from '@/lib/utils';

// Transform candle data for stacked bar visualization
// The trick: use [min, max] arrays for the Bar range dataKey
const transformCandleData = (candles: Candle[]) => {
    return candles.map(candle => {
        const bodyLow = Math.min(candle.open, candle.close);
        const bodyHigh = Math.max(candle.open, candle.close);
        return {
            ...candle,
            // For ReferenceArea rendering
            bodyRange: [bodyLow, bodyHigh] as [number, number],
            bodyLow,
            bodyHigh,
            bodySize: bodyHigh - bodyLow || 0.01, // Ensure minimum size
            isUp: candle.close >= candle.open,
        };
    });
};

// Custom candlestick shape using properly computed positions from Bar
const CandleShape = (props: any) => {
    const { x, y, width, height, payload } = props;

    if (!payload || !x || !width) return null;

    const { high, low, bodyLow, bodyHigh, isUp } = payload;
    const color = isUp ? '#30D158' : '#FF453A';

    // Calculate wick positions
    // y is top of bar (bodyHigh), y + height is bottom (bodyLow)
    const bodyTop = y;
    const bodyBottom = y + Math.abs(height || 1);

    // If height is negative (inverted), swap
    const actualTop = Math.min(bodyTop, bodyBottom);
    const actualBottom = Math.max(bodyTop, bodyBottom);

    // Calculate price-to-pixel scale
    const bodyRange = bodyHigh - bodyLow || 1;
    const pixelRange = Math.abs(height) || 1;
    const scale = pixelRange / bodyRange;

    // Wick positions
    const wickTopY = actualTop - (high - bodyHigh) * scale;
    const wickBottomY = actualBottom + (bodyLow - low) * scale;

    const candleWidth = Math.max(width * 0.6, 3);
    const xCenter = x + width / 2;

    return (
        <g>
            {/* Upper wick */}
            <line
                x1={xCenter}
                y1={wickTopY}
                x2={xCenter}
                y2={actualTop}
                stroke={color}
                strokeWidth={1}
            />
            {/* Lower wick */}
            <line
                x1={xCenter}
                y1={actualBottom}
                x2={xCenter}
                y2={wickBottomY}
                stroke={color}
                strokeWidth={1}
            />
            {/* Body */}
            <rect
                x={xCenter - candleWidth / 2}
                y={actualTop}
                width={candleWidth}
                height={Math.max(actualBottom - actualTop, 1)}
                fill={color}
                stroke={color}
                rx={1}
            />
        </g>
    );
};

interface ChartWidgetProps {
    data: Candle[];
    tradeSuggestion?: TradeSuggestion | null;
    currentExchange: ExchangeId;
    onExchangeChange: (id: ExchangeId) => void;
    onTimeframeChange?: (tf: string) => void;
    currentTimeframe?: string;
    className?: string; // Standardize
}

export const ChartWidget: React.FC<ChartWidgetProps> = ({
    data,
    tradeSuggestion,
    currentExchange,
    onExchangeChange,
    onTimeframeChange,
    currentTimeframe = '1h',
    className
}) => {
    const [isExchangeMenuOpen, setIsExchangeMenuOpen] = useState(false);

    // Transform data for candlestick rendering
    const chartData = useMemo(() => transformCandleData(data), [data]);

    const currentPrice = data[data.length - 1]?.close || 0;
    const previousPrice = data[0]?.close || 0;
    const isPositive = currentPrice >= previousPrice;

    const activeExchangeInfo = getExchange(currentExchange);
    const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];

    // Calculate domain with padding
    const minPrice = Math.min(...data.map(d => d.low));
    const maxPrice = Math.max(...data.map(d => d.high));
    const priceRange = maxPrice - minPrice;
    const domain = [minPrice - priceRange * 0.1, maxPrice + priceRange * 0.1];

    return (
        <div className={cn("h-full min-h-[300px] flex flex-col relative", className)} onClick={() => isExchangeMenuOpen && setIsExchangeMenuOpen(false)}>
            {/* Chart Header */}
            <div className="flex items-center justify-between p-5 border-b border-white/5 relative z-20">
                <div className="flex items-center gap-6">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-[#F7931A] flex items-center justify-center shadow-lg shadow-orange-500/10">
                            <span className="font-bold text-white text-xs">₿</span>
                        </div>
                        <div>
                            <div className="flex items-center gap-2 cursor-pointer group relative" onClick={(e) => { e.stopPropagation(); setIsExchangeMenuOpen(!isExchangeMenuOpen); }}>
                                <h2 className="text-text-primary font-semibold text-lg leading-tight group-hover:text-white transition-colors">BTC-PERP</h2>
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-text-secondary border border-white/5 group-hover:border-accent-primary/30 transition-colors flex items-center gap-1">
                                    {activeExchangeInfo.name} <ChevronDown size={10} />
                                </span>

                                {/* Exchange Dropdown */}
                                {isExchangeMenuOpen && (
                                    <div className="absolute top-full left-0 mt-2 w-64 bg-background-elevated border border-white/10 rounded-xl shadow-2xl z-[100] overflow-hidden animate-fade-in">
                                        <div className="p-2 border-b border-white/5 text-xs font-medium text-text-tertiary uppercase tracking-wider">Select Exchange</div>
                                        {SUPPORTED_EXCHANGES.map(ex => (
                                            <div
                                                key={ex.id}
                                                onClick={() => onExchangeChange(ex.id)}
                                                className={`px-4 py-3 flex items-center justify-between hover:bg-white/5 cursor-pointer transition-colors ${currentExchange === ex.id ? 'bg-white/5' : ''}`}
                                            >
                                                <div>
                                                    <div className="text-sm font-bold text-white flex items-center gap-2">
                                                        {ex.name}
                                                        {currentExchange === ex.id && <Check size={14} className="text-accent-primary" />}
                                                    </div>
                                                    <div className="text-[10px] text-text-tertiary mt-0.5">{ex.description}</div>
                                                </div>
                                                {!ex.requiresKYC && (
                                                    <div className="flex items-center gap-1 text-[10px] text-accent-success bg-accent-success/10 px-1.5 py-0.5 rounded border border-accent-success/20">
                                                        <Globe size={10} /> No KYC
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <p className="text-text-tertiary text-xs">Bitcoin Perpetual</p>
                        </div>
                    </div>
                    <div className="h-8 w-[1px] bg-white/10 mx-2"></div>
                    <div className="flex flex-col">
                        <span className={cn(
                            "text-xl font-mono font-medium tracking-tight",
                            isPositive ? 'text-accent-success' : 'text-accent-danger'
                        )}>
                            ${currentPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </span>
                        <span className={cn(
                            "text-xs",
                            isPositive ? 'text-accent-success' : 'text-accent-danger'
                        )}>
                            {isPositive ? '+' : ''}{((currentPrice - previousPrice) / previousPrice * 100).toFixed(2)}%
                        </span>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <div className="flex bg-background-secondary rounded-lg p-0.5 border border-white/5">
                        {timeframes.map((tf) => (
                            <button
                                key={tf}
                                onClick={() => onTimeframeChange?.(tf)}
                                className={cn(
                                    "px-3 py-1 text-xs font-medium rounded-md transition-all",
                                    currentTimeframe === tf ? 'bg-background-elevated text-white shadow-sm' : 'text-text-secondary hover:text-white'
                                )}
                            >
                                {tf}
                            </button>
                        ))}
                    </div>
                    <button className="p-2 hover:bg-white/5 rounded-lg text-text-secondary transition-colors">
                        <Activity size={18} />
                    </button>
                    <button className="p-2 hover:bg-white/5 rounded-lg text-text-secondary transition-colors">
                        <Maximize2 size={18} />
                    </button>
                </div>
            </div>

            {/* Chart Canvas */}
            <div className="flex-1 w-full min-h-0 relative z-0">
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                        <XAxis
                            dataKey="time"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: '#6C6C70', fontSize: 11 }}
                            minTickGap={30}
                        />
                        <YAxis
                            domain={domain}
                            orientation="right"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: '#6C6C70', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                            tickFormatter={(val) => val.toFixed(0)}
                        />
                        <Tooltip
                            content={({ active, payload, label }) => {
                                if (!active || !payload || !payload[0]) return null;
                                const d = payload[0].payload;
                                return (
                                    <div className="bg-background-elevated/95 backdrop-blur-md border border-white/10 rounded-lg p-3 text-xs shadow-xl">
                                        <div className="font-bold text-white mb-2">{label}</div>
                                        <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-text-secondary">
                                            <span>Open:</span><span className="text-white">{d.open?.toFixed(2)}</span>
                                            <span>High:</span><span className="text-accent-success">{d.high?.toFixed(2)}</span>
                                            <span>Low:</span><span className="text-accent-danger">{d.low?.toFixed(2)}</span>
                                            <span>Close:</span><span className="text-white">{d.close?.toFixed(2)}</span>
                                        </div>
                                    </div>
                                );
                            }}
                        />

                        {/* Candlestick body using stacked bar with custom shape */}
                        <Bar
                            dataKey="bodyRange"
                            shape={<CandleShape />}
                            isAnimationActive={false}
                        />

                        <ReferenceLine y={currentPrice} stroke="#0A84FF" strokeDasharray="3 3" opacity={0.5} />

                        {/* AI Trade Suggestion Visuals */}
                        {tradeSuggestion && tradeSuggestion.direction !== 'WAIT' && (
                            <>
                                <ReferenceLine
                                    y={tradeSuggestion.entryPrice}
                                    stroke="#FFFFFF"
                                    strokeWidth={1}
                                    strokeDasharray="4 4"
                                    label={{ value: 'ENTRY', fill: '#FFFFFF', fontSize: 10, position: 'insideRight', dy: -10 }}
                                />
                                <ReferenceLine
                                    y={tradeSuggestion.stopLoss}
                                    stroke="#FF453A"
                                    strokeWidth={1}
                                    strokeDasharray="4 4"
                                    label={{ value: 'STOP', fill: '#FF453A', fontSize: 10, position: 'insideRight', dy: -10 }}
                                />
                                <ReferenceLine
                                    y={tradeSuggestion.takeProfit}
                                    stroke="#30D158"
                                    strokeWidth={1}
                                    strokeDasharray="4 4"
                                    label={{ value: 'TARGET', fill: '#30D158', fontSize: 10, position: 'insideRight', dy: -10 }}
                                />
                            </>
                        )}

                    </ComposedChart>
                </ResponsiveContainer>

                {/* Floating Indicator Toggles */}
                <div className="absolute top-4 left-4 flex flex-row gap-4 z-30">
                    {['VWAP', 'EMA 20', 'Bollinger'].map(ind => (
                        <div key={ind} className="px-3 py-1.5 bg-background-elevated/95 backdrop-blur-sm rounded-lg border border-white/15 text-[10px] text-text-secondary cursor-pointer hover:text-white hover:border-white/30 transition-colors whitespace-nowrap shadow-lg">
                            {ind}
                        </div>
                    ))}
                </div>

                {/* AI Insight Overlay */}
                {tradeSuggestion && (
                    <div className="absolute top-16 right-16 bg-background-tertiary/90 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-2xl max-w-[260px] animate-fade-in z-10 hover:border-accent-primary/50 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                                <BrainCircuit size={14} className="text-accent-primary" />
                                <span className="text-xs font-bold text-white uppercase tracking-wider">AI Signal</span>
                            </div>
                            <div className="text-[10px] text-text-tertiary">{tradeSuggestion.confidence}% Conf.</div>
                        </div>

                        {tradeSuggestion.direction === 'WAIT' ? (
                            <div className="flex items-center gap-2 text-accent-warning mb-2">
                                <AlertTriangle size={16} />
                                <span className="font-bold">Wait / No Trade</span>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 mb-2">
                                <div className={cn("w-2 h-2 rounded-full", tradeSuggestion.direction === 'LONG' ? 'bg-accent-success' : 'bg-accent-danger')}></div>
                                <span className={cn("font-bold text-lg", tradeSuggestion.direction === 'LONG' ? 'text-accent-success' : 'text-accent-danger')}>
                                    {tradeSuggestion.direction}
                                </span>
                            </div>
                        )}

                        <p className="text-xs text-text-secondary leading-relaxed border-t border-white/5 pt-2">
                            {tradeSuggestion.reasoning}
                        </p>

                        {tradeSuggestion.direction !== 'WAIT' && (
                            <div className="grid grid-cols-3 gap-2 mt-3 pt-2 border-t border-white/5 text-[10px]">
                                <div>
                                    <span className="text-text-tertiary block">Entry</span>
                                    <span className="text-white font-mono">{tradeSuggestion.entryPrice.toFixed(0)}</span>
                                </div>
                                <div>
                                    <span className="text-text-tertiary block">Target</span>
                                    <span className="text-accent-success font-mono">{tradeSuggestion.takeProfit.toFixed(0)}</span>
                                </div>
                                <div>
                                    <span className="text-text-tertiary block">Stop</span>
                                    <span className="text-accent-danger font-mono">{tradeSuggestion.stopLoss.toFixed(0)}</span>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
