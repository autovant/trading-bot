
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { AreaChart, Area, Tooltip, ResponsiveContainer } from 'recharts';
import { Activity, Play, Pause, RotateCcw, SkipBack, SkipForward, FastForward, Check, Save } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { BacktestResult } from '@/types';
import { calculateBacktestStats } from '@/services/strategyEngine';
import { cn } from '@/lib/utils';

interface BacktestResultsViewProps {
    result: BacktestResult;
    timeframe: string;
    onSave?: () => void;
    isSaved?: boolean;
    className?: string;
}

export const BacktestResultsView: React.FC<BacktestResultsViewProps> = ({
    result: fullResult,
    timeframe,
    onSave,
    isSaved,
    className
}) => {
    // Playback State
    const [playbackIndex, setPlaybackIndex] = useState(fullResult.equityCurve.length - 1);
    const [isPlaying, setIsPlaying] = useState(false);
    const [playbackSpeed, setPlaybackSpeed] = useState(1);
    const playbackTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Reset playback when result changes
    useEffect(() => {
        setPlaybackIndex(fullResult.equityCurve.length - 1);
        setIsPlaying(false);
    }, [fullResult]);

    // Playback Logic
    useEffect(() => {
        if (isPlaying) {
            playbackTimerRef.current = setInterval(() => {
                setPlaybackIndex(prev => {
                    if (prev >= fullResult.equityCurve.length - 1) {
                        setIsPlaying(false);
                        return prev;
                    }
                    return prev + 1;
                });
            }, 1000 / (10 * playbackSpeed));
        } else {
            if (playbackTimerRef.current) clearInterval(playbackTimerRef.current);
        }
        return () => { if (playbackTimerRef.current) clearInterval(playbackTimerRef.current); };
    }, [isPlaying, fullResult, playbackSpeed]);

    // Computed Result for Frame
    const displayedResult = useMemo(() => {
        const slicedEquity = fullResult.equityCurve.slice(0, playbackIndex + 1);
        const currentCandleIndex = slicedEquity[slicedEquity.length - 1]?.candleIndex || 0;
        const slicedTrades = fullResult.trades.filter(t => t.exitIndex <= currentCandleIndex);

        const stats = calculateBacktestStats(slicedTrades, slicedEquity, timeframe);

        return {
            ...stats,
            equityCurve: slicedEquity,
            trades: slicedTrades
        };
    }, [fullResult, playbackIndex, timeframe]);

    const getMetricColor = (type: string, value: number) => {
        if (type === 'sharpe' || type === 'sortino') {
            if (value >= 1.5) return 'text-accent-success';
            if (value >= 1.0) return 'text-white';
            return 'text-accent-warning';
        }
        if (type === 'drawdown') {
            if (value < 10) return 'text-accent-success';
            if (value < 20) return 'text-accent-warning';
            return 'text-accent-danger';
        }
        return 'text-white';
    };

    return (
        <div className={cn("flex flex-col gap-4 animate-fade-in", className)}>
            {/* Controls Bar */}
            <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-4">
                    <h2 className="font-bold text-lg text-white">Performance Report</h2>
                    {onSave && (
                        <button
                            onClick={onSave}
                            disabled={isSaved}
                            className={cn(
                                "text-xs flex items-center gap-1 px-3 py-1.5 rounded-full transition-all border",
                                isSaved ? 'bg-accent-success/20 border-accent-success text-accent-success' : 'bg-card border-white/5 text-text-secondary hover:text-white hover:border-white/20'
                            )}
                        >
                            {isSaved ? <Check size={12} /> : <Save size={12} />}
                            {isSaved ? 'Result Saved' : 'Save to History'}
                        </button>
                    )}
                </div>

                <div className="flex items-center gap-3 bg-card p-1.5 rounded-lg border border-white/5 shadow-sm">
                    <button onClick={() => setPlaybackIndex(0)} className="p-1.5 hover:bg-white/10 rounded text-text-secondary hover:text-white" title="Reset">
                        <RotateCcw size={14} />
                    </button>
                    <button onClick={() => setPlaybackIndex(Math.max(0, playbackIndex - 1))} className="p-1.5 hover:bg-white/10 rounded text-text-secondary hover:text-white" title="Step Back">
                        <SkipBack size={14} />
                    </button>
                    <button onClick={() => setIsPlaying(!isPlaying)} className={cn("p-2 rounded-full transition-colors", isPlaying ? 'bg-accent-warning text-black' : 'bg-brand text-white')}>
                        {isPlaying ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
                    </button>
                    <button onClick={() => setPlaybackIndex(Math.min(fullResult.equityCurve.length - 1, playbackIndex + 1))} className="p-1.5 hover:bg-white/10 rounded text-text-secondary hover:text-white" title="Step Forward">
                        <SkipForward size={14} />
                    </button>
                    <div className="w-[1px] h-6 bg-white/10 mx-1"></div>
                    <input
                        type="range"
                        min="0"
                        max={fullResult.equityCurve.length - 1}
                        value={playbackIndex}
                        onChange={(e) => { setPlaybackIndex(Number(e.target.value)); setIsPlaying(false); }}
                        className="w-24 md:w-32 h-1.5 bg-background-elevated rounded-lg appearance-none cursor-pointer accent-brand"
                    />
                    <div className="relative group">
                        <button className="p-1.5 hover:bg-white/10 rounded text-xs font-mono text-text-secondary flex items-center gap-1">
                            {playbackSpeed}x <FastForward size={10} />
                        </button>
                        <div className="absolute top-full right-0 mt-2 bg-card border border-white/5 rounded-lg p-1 hidden group-hover:flex flex-col z-20 shadow-xl w-16">
                            {[1, 5, 10, 20].map(s => (
                                <button key={s} onClick={() => setPlaybackSpeed(s)} className={cn("px-2 py-1 text-xs text-left rounded hover:bg-white/10", playbackSpeed === s ? 'text-brand' : 'text-text-secondary')}>
                                    {s}x
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                    { label: 'Total PnL', value: displayedResult.totalPnL, format: 'currency', color: displayedResult.totalPnL >= 0 ? 'text-accent-success' : 'text-accent-danger' },
                    { label: 'Win Rate', value: displayedResult.winRate, format: 'percent' },
                    { label: 'Total Trades', value: displayedResult.totalTrades, format: 'number' },
                    { label: 'Profit Factor', value: displayedResult.profitFactor, format: 'decimal' },
                    { label: 'Sharpe Ratio', value: displayedResult.sharpeRatio, format: 'decimal', color: getMetricColor('sharpe', displayedResult.sharpeRatio) },
                    { label: 'Sortino Ratio', value: displayedResult.sortinoRatio, format: 'decimal', color: getMetricColor('sortino', displayedResult.sortinoRatio) },
                    { label: 'Max Drawdown', value: displayedResult.maxDrawdownPercent, format: 'percent_red', color: getMetricColor('drawdown', displayedResult.maxDrawdownPercent) },
                    { label: 'Expectancy', value: displayedResult.totalTrades > 0 ? displayedResult.totalPnL / displayedResult.totalTrades : 0, format: 'currency' },
                ].map((stat, i) => (
                    <Card key={i} className="p-4 flex flex-col justify-between h-24 relative overflow-hidden group">
                        <div className="text-[10px] text-text-tertiary uppercase font-bold tracking-wider relative z-10">{stat.label}</div>
                        <div className={cn("text-xl md:text-2xl font-mono font-bold relative z-10", stat.color || 'text-white')}>
                            {stat.format === 'currency' && (stat.value > 0 ? '+' : '')}
                            {stat.format === 'currency' ? stat.value.toFixed(0) : ''}
                            {stat.format === 'percent' ? `${stat.value.toFixed(1)}%` : ''}
                            {stat.format === 'percent_red' && stat.value > 0 ? `-${stat.value.toFixed(2)}%` : ''}
                            {stat.format === 'percent_red' && stat.value === 0 ? `0.00%` : ''}
                            {stat.format === 'number' ? stat.value : ''}
                            {stat.format === 'decimal' ? stat.value.toFixed(2) : ''}
                        </div>
                        <div className="absolute right-0 bottom-0 opacity-5 group-hover:opacity-10 transition-opacity transform translate-x-1/4 translate-y-1/4">
                            <Activity size={80} />
                        </div>
                    </Card>
                ))}
            </div>

            {/* Charts & Logs */}
            <div className="grid grid-cols-12 gap-6 min-h-[400px]">
                <div className="col-span-12 lg:col-span-8 h-full min-h-[300px]">
                    <Card className="h-full flex flex-col" noPadding>
                        <div className="p-3 border-b border-white/5 text-xs font-bold text-text-secondary flex justify-between">
                            <span>Equity Curve</span>
                            <span className="font-mono">{displayedResult.equityCurve.length > 0 ? displayedResult.equityCurve[displayedResult.equityCurve.length - 1].time : '--:--'}</span>
                        </div>
                        <div className="flex-1 w-full p-2 min-h-[250px]">
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={displayedResult.equityCurve}>
                                    <defs>
                                        <linearGradient id="colorEq" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor={displayedResult.totalPnL >= 0 ? "#30D158" : "#FF453A"} stopOpacity={0.3} />
                                            <stop offset="95%" stopColor={displayedResult.totalPnL >= 0 ? "#30D158" : "#FF453A"} stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#1C1C1E', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '12px' }}
                                        itemStyle={{ color: '#fff' }}
                                        formatter={(value: number) => [`$${value.toFixed(2)}`, 'Equity']}
                                    />
                                    <Area
                                        type="monotone"
                                        dataKey="value"
                                        stroke={displayedResult.totalPnL >= 0 ? "#30D158" : "#FF453A"}
                                        fill="url(#colorEq)"
                                        strokeWidth={2}
                                        isAnimationActive={false}
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </Card>
                </div>
                <div className="col-span-12 lg:col-span-4 h-full min-h-[300px]">
                    <Card className="h-full flex flex-col" noPadding>
                        <div className="p-3 border-b border-white/5 text-xs font-bold text-text-secondary">Trade Log</div>
                        <div className="flex-1 overflow-y-auto custom-scrollbar p-0 max-h-[400px]">
                            {displayedResult.trades.slice().reverse().map((trade, i) => (
                                <div key={i} className="flex justify-between items-center p-3 border-b border-white/5 hover:bg-white/5 transition-colors group">
                                    <div className="flex items-center gap-3">
                                        <div className={cn("w-1.5 h-1.5 rounded-full", trade.pnl >= 0 ? 'bg-accent-success' : 'bg-accent-danger')}></div>
                                        <div>
                                            <div className="text-xs font-bold text-white uppercase">{trade.side}</div>
                                            <div className="text-[10px] text-text-tertiary">{trade.entryTime}</div>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className={cn("text-xs font-mono font-medium", trade.pnl >= 0 ? 'text-accent-success' : 'text-accent-danger')}>
                                            {trade.pnl > 0 ? '+' : ''}{trade.pnl.toFixed(2)}
                                        </div>
                                        <div className="text-[10px] text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity">
                                            {trade.entryPrice.toFixed(1)} → {trade.exitPrice.toFixed(1)}
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {displayedResult.trades.length === 0 && (
                                <div className="p-4 text-center text-[10px] text-text-tertiary">
                                    No trades executed yet...
                                </div>
                            )}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
};
