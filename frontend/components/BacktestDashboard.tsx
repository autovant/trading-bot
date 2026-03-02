
import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, Cell, CartesianGrid, XAxis, YAxis, Legend, ResponsiveContainer, Tooltip } from 'recharts';
import { Play, Calendar, History, BarChart2, CheckSquare, Trash2, Search, Filter, ArrowRight, TrendingUp } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { BacktestResultsView } from './BacktestResultsView';
import { getStrategies, getBacktestHistory, saveBacktestResult, deleteBacktestRecord } from '@/services/strategyStorage';
import { generateCandlesInRange } from '@/services/mockData';
import { runBacktest, calculateBacktestStats } from '@/services/strategyEngine';
import { StrategyConfig, BacktestRecord, BacktestResult } from '@/types';
import { cn } from '@/lib/utils';

type ViewMode = 'run' | 'history';

interface BacktestDashboardProps {
    globalSymbol?: string;
    className?: string; // Standardize
}

export const BacktestDashboard: React.FC<BacktestDashboardProps> = ({ globalSymbol, className }) => {
    const [viewMode, setViewMode] = useState<ViewMode>('history');
    const [history, setHistory] = useState<BacktestRecord[]>([]);
    const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
    const [selectedStrategyId, setSelectedStrategyId] = useState<string>('');
    const [comparisonIds, setComparisonIds] = useState<string[]>([]);

    // Simulation Config
    const [startDate, setStartDate] = useState(() => {
        const d = new Date();
        d.setMonth(d.getMonth() - 1);
        return d.toISOString().split('T')[0];
    });
    const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);

    // Result State
    const [isSimulating, setIsSimulating] = useState(false);
    const [activeResult, setActiveResult] = useState<BacktestResult | null>(null);
    const [resultSaved, setResultSaved] = useState(false);

    useEffect(() => {
        setHistory(getBacktestHistory());
        const loadedStrategies = getStrategies();
        setStrategies(loadedStrategies);
        if (loadedStrategies.length > 0) {
            // Prefer strategy matching globalSymbol if exists
            const matching = globalSymbol ? loadedStrategies.find(s => s.symbol === globalSymbol) : null;
            setSelectedStrategyId(matching ? matching.id : loadedStrategies[0].id);
        }
    }, [globalSymbol]);

    const handleRunSimulation = () => {
        const strategy = strategies.find(s => s.id === selectedStrategyId);
        if (!strategy) return;

        setIsSimulating(true);
        setActiveResult(null);
        setResultSaved(false);

        // Defer to allow UI to show spinner
        setTimeout(() => {
            const candles = generateCandlesInRange(strategy.symbol, strategy.timeframe, startDate, endDate);

            if (candles.length < 50) {
                alert("Date range too short. Please increase.");
                setIsSimulating(false);
                return;
            }

            const result = runBacktest(candles, strategy);
            setActiveResult(result);
            setIsSimulating(false);
        }, 300);
    };

    const handleSaveResult = () => {
        if (!activeResult) return;
        const strategy = strategies.find(s => s.id === selectedStrategyId);
        if (!strategy) return;

        const record: BacktestRecord = {
            id: `run_${Date.now()}`,
            strategyId: strategy.id,
            strategyName: strategy.name,
            symbol: strategy.symbol,
            timeframe: strategy.timeframe,
            startDate,
            endDate,
            executedAt: Date.now(),
            stats: calculateBacktestStats(activeResult.trades, activeResult.equityCurve, strategy.timeframe)
        };
        saveBacktestResult(record);
        setHistory(getBacktestHistory());
        setResultSaved(true);
    };

    const handleDeleteRecord = (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        if (window.confirm("Delete this history record?")) {
            deleteBacktestRecord(id);
            setHistory(getBacktestHistory());
            setComparisonIds(prev => prev.filter(cid => cid !== id));
        }
    };

    const toggleComparison = (id: string) => {
        setComparisonIds(prev =>
            prev.includes(id) ? prev.filter(cid => cid !== id) : [...prev, id]
        );
    };

    const comparisonData = useMemo(() => {
        return history.filter(h => comparisonIds.includes(h.id));
    }, [history, comparisonIds]);

    return (
        <div className={cn("h-full flex flex-col p-4 pt-20 max-w-[1600px] mx-auto w-full gap-6", className)}>

            {/* Header */}
            <div className="flex justify-between items-center bg-background-secondary/80 backdrop-blur-md p-4 rounded-2xl border border-white/5 shadow-xl sticky top-20 z-20">
                <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 flex items-center justify-center text-accent-primary border border-white/10">
                        <History size={20} />
                    </div>
                    <div>
                        <h1 className="text-lg font-bold text-white">Backtest Laboratory</h1>
                        <p className="text-xs text-text-tertiary">Analyze historical performance and optimize strategies.</p>
                    </div>
                </div>

                <div className="flex bg-background-elevated p-1 rounded-lg border border-white/5">
                    <button
                        onClick={() => setViewMode('history')}
                        className={cn(
                            "px-4 py-2 rounded-md text-sm font-medium transition-all flex items-center gap-2",
                            viewMode === 'history' ? 'bg-white/10 text-white shadow-sm' : 'text-text-secondary hover:text-white'
                        )}
                    >
                        <BarChart2 size={16} /> Analysis & History
                    </button>
                    <button
                        onClick={() => setViewMode('run')}
                        className={cn(
                            "px-4 py-2 rounded-md text-sm font-medium transition-all flex items-center gap-2",
                            viewMode === 'run' ? 'bg-white/10 text-white shadow-sm' : 'text-text-secondary hover:text-white'
                        )}
                    >
                        <Play size={16} /> New Simulation
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">

                {/* --- HISTORY VIEW --- */}
                {viewMode === 'history' && (
                    <div className="flex flex-col gap-6 animate-fade-in">
                        {/* Comparison Charts */}
                        {comparisonIds.length > 0 && (
                            <div className="grid grid-cols-2 gap-6 h-72">
                                <Card className="p-4 flex flex-col">
                                    <h3 className="text-xs font-bold text-text-secondary uppercase tracking-wider mb-2">Net PnL Comparison</h3>
                                    <div className="flex-1 min-h-0">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <BarChart data={comparisonData}>
                                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                                <Tooltip
                                                    cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                                                    contentStyle={{ backgroundColor: '#1C1C1E', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '12px' }}
                                                    itemStyle={{ color: '#fff' }}
                                                />
                                                <Bar dataKey="stats.totalPnL" name="Net PnL" radius={[4, 4, 0, 0]}>
                                                    {comparisonData.map((entry, index) => (
                                                        <Cell key={`cell-${index}`} fill={entry.stats.totalPnL >= 0 ? '#30D158' : '#FF453A'} />
                                                    ))}
                                                </Bar>
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                </Card>
                                <Card className="p-4 flex flex-col">
                                    <h3 className="text-xs font-bold text-text-secondary uppercase tracking-wider mb-2">Risk-Adjusted Returns</h3>
                                    <div className="flex-1 min-h-0">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <BarChart data={comparisonData}>
                                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                                <Tooltip
                                                    cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                                                    contentStyle={{ backgroundColor: '#1C1C1E', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '12px' }}
                                                    itemStyle={{ color: '#fff' }}
                                                />
                                                <Legend wrapperStyle={{ fontSize: '10px', paddingTop: '10px' }} />
                                                <Bar dataKey="stats.sharpeRatio" name="Sharpe Ratio" fill="#0A84FF" radius={[4, 4, 0, 0]} />
                                                <Bar dataKey="stats.sortinoRatio" name="Sortino Ratio" fill="#A855F7" radius={[4, 4, 0, 0]} />
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                </Card>
                            </div>
                        )}

                        {/* History Table */}
                        <Card className="flex-1" noPadding>
                            <div className="p-4 border-b border-white/5 flex justify-between items-center">
                                <h3 className="font-bold text-sm text-white">Run History</h3>
                                <div className="flex items-center gap-2">
                                    <div className="relative">
                                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
                                        <input type="text" placeholder="Filter..." className="bg-background-secondary border border-white/5 rounded-full pl-9 pr-3 py-1.5 text-xs focus:outline-none focus:border-accent-primary transition-colors" />
                                    </div>
                                </div>
                            </div>
                            <table className="w-full text-left border-collapse">
                                <thead>
                                    <tr className="bg-background-elevated/50 text-text-tertiary text-xs uppercase tracking-wider">
                                        <th className="p-4 w-12 text-center">Compare</th>
                                        <th className="p-4 font-semibold">Strategy</th>
                                        <th className="p-4 font-semibold">Market</th>
                                        <th className="p-4 font-semibold">Period</th>
                                        <th className="p-4 font-semibold text-right">Net PnL</th>
                                        <th className="p-4 font-semibold text-right">Win Rate</th>
                                        <th className="p-4 font-semibold text-right">Sharpe</th>
                                        <th className="p-4 font-semibold text-right">Max DD</th>
                                        <th className="p-4 w-12"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {history.length === 0 && (
                                        <tr>
                                            <td colSpan={9} className="p-12 text-center text-text-tertiary">
                                                No history found. Run a simulation to generate data.
                                            </td>
                                        </tr>
                                    )}
                                    {history.map(run => {
                                        const isSelected = comparisonIds.includes(run.id);
                                        return (
                                            <tr
                                                key={run.id}
                                                onClick={() => toggleComparison(run.id)}
                                                className={cn(
                                                    "border-b border-white/5 cursor-pointer transition-colors",
                                                    isSelected ? 'bg-accent-primary/5 hover:bg-accent-primary/10' : 'hover:bg-white/5'
                                                )}
                                            >
                                                <td className="p-4 text-center">
                                                    <div className={cn(
                                                        "w-4 h-4 rounded border flex items-center justify-center mx-auto transition-colors",
                                                        isSelected ? 'bg-accent-primary border-accent-primary text-white' : 'border-text-tertiary bg-transparent'
                                                    )}>
                                                        {isSelected && <CheckSquare size={10} strokeWidth={3} />}
                                                    </div>
                                                </td>
                                                <td className="p-4 font-bold text-white text-sm">{run.strategyName}</td>
                                                <td className="p-4 text-xs text-text-secondary">{run.symbol} <span className="text-text-tertiary">({run.timeframe})</span></td>
                                                <td className="p-4 text-xs text-text-tertiary font-mono">{run.startDate} → {run.endDate}</td>
                                                <td className={cn(
                                                    "p-4 text-right font-mono text-sm font-bold",
                                                    run.stats.totalPnL >= 0 ? 'text-accent-success' : 'text-accent-danger'
                                                )}>
                                                    {run.stats.totalPnL >= 0 ? '+' : ''}{run.stats.totalPnL.toFixed(0)}
                                                </td>
                                                <td className="p-4 text-right font-mono text-sm text-white">{run.stats.winRate.toFixed(1)}%</td>
                                                <td className={cn(
                                                    "p-4 text-right font-mono text-sm",
                                                    run.stats.sharpeRatio >= 1 ? 'text-accent-success' : 'text-text-secondary'
                                                )}>{run.stats.sharpeRatio.toFixed(2)}</td>
                                                <td className="p-4 text-right font-mono text-sm text-accent-danger">{run.stats.maxDrawdownPercent.toFixed(1)}%</td>
                                                <td className="p-4 text-center">
                                                    <button onClick={(e) => handleDeleteRecord(e, run.id)} className="p-2 hover:bg-accent-danger/20 text-text-tertiary hover:text-accent-danger rounded transition-colors">
                                                        <Trash2 size={14} />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </Card>
                    </div>
                )}

                {/* --- RUNNER VIEW --- */}
                {viewMode === 'run' && (
                    <div className="flex flex-col gap-6 animate-fade-in">
                        {/* Config Panel */}
                        <Card className="p-6">
                            <div className="flex items-center gap-2 mb-6 pb-4 border-b border-white/5 text-text-secondary">
                                <TrendingUp size={20} className="text-accent-primary" />
                                <span className="font-bold text-sm uppercase tracking-wider">Simulation Configuration</span>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
                                <div>
                                    <label className="text-[10px] text-text-tertiary uppercase font-bold mb-2 block">Target Strategy</label>
                                    <select
                                        value={selectedStrategyId}
                                        onChange={(e) => setSelectedStrategyId(e.target.value)}
                                        className="w-full bg-background-secondary border border-white/10 rounded-lg p-3 text-sm focus:outline-none focus:border-accent-primary transition-colors"
                                    >
                                        {strategies.map(s => <option key={s.id} value={s.id}>{s.name} ({s.symbol})</option>)}
                                    </select>
                                </div>

                                <div>
                                    <label className="text-[10px] text-text-tertiary uppercase font-bold mb-2 block">Start Date</label>
                                    <input
                                        type="date"
                                        value={startDate}
                                        onChange={(e) => setStartDate(e.target.value)}
                                        className="w-full bg-background-secondary border border-white/10 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-accent-primary"
                                    />
                                </div>

                                <div>
                                    <label className="text-[10px] text-text-tertiary uppercase font-bold mb-2 block">End Date</label>
                                    <input
                                        type="date"
                                        value={endDate}
                                        onChange={(e) => setEndDate(e.target.value)}
                                        className="w-full bg-background-secondary border border-white/10 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-accent-primary"
                                    />
                                </div>

                                <button
                                    onClick={handleRunSimulation}
                                    disabled={isSimulating || !selectedStrategyId}
                                    className="w-full bg-accent-primary hover:bg-accent-primary/90 text-white font-bold py-3 rounded-lg shadow-lg shadow-accent-primary/20 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                                >
                                    {isSimulating ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> : <Play size={16} fill="currentColor" />}
                                    Run Simulation
                                </button>
                            </div>
                        </Card>

                        {/* Result View */}
                        {activeResult && (
                            <BacktestResultsView
                                result={activeResult}
                                timeframe={strategies.find(s => s.id === selectedStrategyId)?.timeframe || '1h'}
                                onSave={handleSaveResult}
                                isSaved={resultSaved}
                            />
                        )}

                        {!activeResult && !isSimulating && (
                            <div className="flex flex-col items-center justify-center h-64 border-2 border-dashed border-white/5 rounded-2xl text-text-tertiary bg-white/[0.01]">
                                <Play size={48} className="opacity-20 mb-4" />
                                <p className="font-medium">Ready to Simulate</p>
                                <p className="text-xs mt-1">Configure your parameters above and press Run.</p>
                            </div>
                        )}
                    </div>
                )}

            </div>
        </div>
    );
};
