
import React, { useState, useEffect, useRef } from 'react';
import {
  Play, Save, Plus, Trash2, Zap, Box, Activity,
  FolderOpen, FilePlus, ChevronRight, BarChart3,
  X, AlertCircle, RotateCcw, BrainCircuit, Calendar, Percent
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { BacktestResult, BacktestRecord, IndicatorDefinition, RuleCondition, StrategyConfig } from '@/types';
import { runBacktest, calculateBacktestStats } from '@/services/strategyEngine';
import { MarketStream } from '@/services/marketStream';
import { getStrategies, saveStrategy, deleteStrategy, createNewStrategy, DEFAULT_STRATEGY, saveBacktestResult, getBacktestHistory } from '@/services/strategyStorage';
import { SUPPORTED_EXCHANGES, getExchange } from '@/services/exchanges';
import { BacktestResultsView } from './BacktestResultsView';
import { cn } from '@/lib/utils';

interface StrategyBuilderProps {
  globalSymbol?: string;
}

export const StrategyBuilder: React.FC<StrategyBuilderProps> = ({ globalSymbol }) => {
  // --- State ---
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
  const [currentStrategy, setCurrentStrategy] = useState<StrategyConfig>(DEFAULT_STRATEGY);
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);

  // Date State
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 1);
    return d.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);

  // Backtest State
  const [fullResult, setFullResult] = useState<BacktestResult | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [resultSaved, setResultSaved] = useState(false);

  // --- Load Initial ---
  useEffect(() => {
    const loaded = getStrategies();
    setStrategies(loaded);
    if (loaded.length > 0) {
      // Try to find one matching globalSymbol if available
      const matching = globalSymbol ? loaded.find(s => s.symbol === globalSymbol) : null;
      setCurrentStrategy(matching || loaded[0]);
    } else {
      const initial = { ...DEFAULT_STRATEGY };
      if (globalSymbol) initial.symbol = globalSymbol;
      setCurrentStrategy(initial);
    }
  }, [globalSymbol]);

  // --- Helpers ---
  const updateStrategy = (updates: Partial<StrategyConfig>) => {
    setCurrentStrategy(prev => ({ ...prev, ...updates }));
    setHasUnsavedChanges(true);
  };

  const handleSave = () => {
    saveStrategy(currentStrategy);
    setStrategies(getStrategies());
    setHasUnsavedChanges(false);
  };

  const handleLoad = (strategy: StrategyConfig) => {
    if (hasUnsavedChanges && !window.confirm("You have unsaved changes. Discard them?")) return;
    setCurrentStrategy(strategy);
    setFullResult(null);
    setHasUnsavedChanges(false);
    setIsLibraryOpen(false);
  };

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (window.confirm("Are you sure you want to delete this strategy?")) {
      deleteStrategy(id);
      const remaining = getStrategies();
      setStrategies(remaining);
      if (currentStrategy.id === id) {
        const matching = globalSymbol ? remaining.find(s => s.symbol === globalSymbol) : null;
        if (matching) {
          setCurrentStrategy(matching);
        } else {
          const newStrat = createNewStrategy();
          if (globalSymbol) newStrat.symbol = globalSymbol;
          setCurrentStrategy(remaining.length > 0 ? remaining[0] : newStrat);
        }
      }
    }
  };

  const handleNew = () => {
    if (hasUnsavedChanges && !window.confirm("You have unsaved changes. Discard them?")) return;
    const newStrat = createNewStrategy();
    if (globalSymbol) newStrat.symbol = globalSymbol;
    setCurrentStrategy(newStrat);
    setFullResult(null);
    setHasUnsavedChanges(true);
  };

  const handleSaveResult = () => {
    if (!fullResult) return;
    const record: BacktestRecord = {
      id: `run_${Date.now()}`,
      strategyId: currentStrategy.id,
      strategyName: currentStrategy.name,
      symbol: currentStrategy.symbol,
      timeframe: currentStrategy.timeframe,
      startDate,
      endDate,
      executedAt: Date.now(),
      stats: calculateBacktestStats(fullResult.trades, fullResult.equityCurve, currentStrategy.timeframe)
    };
    saveBacktestResult(record);
    setResultSaved(true);
    setTimeout(() => setResultSaved(false), 2000);
  };

  // --- Logic Editing ---

  const addIndicator = () => {
    const id = `ind_${Date.now()}`;
    const newInd: IndicatorDefinition = { id, type: 'SMA', period: 20, color: '#FFFFFF' };
    updateStrategy({ indicators: [...currentStrategy.indicators, newInd] });
  };

  const removeIndicator = (id: string) => {
    updateStrategy({
      indicators: currentStrategy.indicators.filter(i => i.id !== id),
      entryRules: currentStrategy.entryRules.filter(r => r.left !== id && r.right !== id),
      exitRules: currentStrategy.exitRules.filter(r => r.left !== id && r.right !== id)
    });
  };

  const addRule = (type: 'entry' | 'exit') => {
    const newRule: RuleCondition = {
      id: `rule_${Date.now()}`,
      left: 'PRICE',
      operator: '>',
      right: 'PRICE'
    };
    const list = type === 'entry' ? currentStrategy.entryRules : currentStrategy.exitRules;
    updateStrategy(type === 'entry' ? { entryRules: [...list, newRule] } : { exitRules: [...list, newRule] });
  };

  const removeRule = (type: 'entry' | 'exit', id: string) => {
    const list = type === 'entry' ? currentStrategy.entryRules : currentStrategy.exitRules;
    updateStrategy(type === 'entry'
      ? { entryRules: list.filter(r => r.id !== id) }
      : { exitRules: list.filter(r => r.id !== id) }
    );
  };

  const handleRunSimulation = async () => {
    setIsSimulating(true);
    setResultSaved(false);
    setFullResult(null);

    try {
      const startTs = new Date(startDate).getTime();
      const endTs = new Date(endDate).getTime() + 86400000 - 1; // Include full end day

      if (endTs <= startTs) {
        alert("End date must be after start date.");
        setIsSimulating(false);
        return;
      }

      // Fetch Real Data
      const candles = await MarketStream.fetchHistoryRange(
        currentStrategy.symbol,
        currentStrategy.timeframe,
        startTs,
        endTs
      );

      if (candles.length < 50) {
        alert("Insufficient data for this range/timeframe. Try expanding the date range.");
        setIsSimulating(false);
        return;
      }

      const result = runBacktest(candles, currentStrategy);
      setFullResult(result);

      // Auto-save stats to strategy for "History/Library" view
      const stats = calculateBacktestStats(result.trades, result.equityCurve, currentStrategy.timeframe);
      const updatedStrat = { ...currentStrategy, lastStats: stats };
      setCurrentStrategy(updatedStrat);
      saveStrategy(updatedStrat); // Persist to storage
      setStrategies(getStrategies()); // Refresh library text
      setHasUnsavedChanges(false);

    } catch (e) {
      console.error("Backtest Error", e);
      alert("Failed to run backtest. See console for details.");
    } finally {
      setIsSimulating(false);
    }
  };

  // --- Components ---

  const RuleEditor: React.FC<{ rule: RuleCondition, type: 'entry' | 'exit', onDelete: () => void }> = ({ rule, type, onDelete }) => {
    const update = (field: keyof RuleCondition, value: string) => {
      const list = type === 'entry' ? currentStrategy.entryRules : currentStrategy.exitRules;
      const updatedList = list.map(r => r.id === rule.id ? { ...r, [field]: value } : r);
      updateStrategy(type === 'entry' ? { entryRules: updatedList } : { exitRules: updatedList });
    };

    return (
      <div className="flex items-center gap-2 bg-background-elevated p-2 rounded-lg border border-white/5 hover:border-white/20 transition-all group" data-testid={`rule-row-${rule.id}`}>
        <div className="relative flex-1 min-w-[120px]">
          <select
            value={rule.left}
            onChange={(e) => update('left', e.target.value)}
            data-testid={`select-left-${rule.id}`}
            className="w-full appearance-none bg-background-secondary pl-3 pr-8 py-2 rounded text-xs font-medium focus:outline-none border border-transparent focus:border-accent-primary transition-colors cursor-pointer"
          >
            <option value="PRICE">Price Action</option>
            {currentStrategy.indicators.map(i => <option key={i.id} value={i.id}>{i.type} ({i.period})</option>)}
          </select>
          <ChevronRight className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary pointer-events-none" size={12} />
        </div>

        <select
          value={rule.operator}
          onChange={(e) => update('operator', e.target.value as any)}
          data-testid={`select-operator-${rule.id}`}
          className="bg-transparent text-brand font-bold text-sm text-center w-10 focus:outline-none cursor-pointer"
        >
          <option value=">">&gt;</option>
          <option value="<">&lt;</option>
          <option value="==">=</option>
        </select>

        <div className="flex-1 relative min-w-[120px]">
          <input
            type="text"
            value={rule.right}
            onChange={(e) => update('right', e.target.value)}
            placeholder="Value (e.g. 30)"
            data-testid={`input-right-${rule.id}`}
            className="w-full bg-background-secondary px-3 py-2 rounded text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none border border-transparent focus:border-accent-primary transition-colors"
          />
        </div>

        <button onClick={onDelete} data-testid={`btn-delete-rule-${rule.id}`} className="text-text-tertiary hover:text-accent-danger opacity-0 group-hover:opacity-100 transition-opacity p-1.5 hover:bg-white/5 rounded">
          <Trash2 size={14} />
        </button>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col p-4 pt-20 gap-4 max-w-[1600px] mx-auto w-full" data-testid="strategy-builder">

      {/* --- Top Bar --- */}
      <header className="flex justify-between items-center bg-background-secondary/80 backdrop-blur-md p-4 rounded-2xl border border-white/5 shadow-xl z-10 sticky top-20">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center text-brand border border-white/10">
            <BrainCircuit size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={currentStrategy.name}
                onChange={(e) => updateStrategy({ name: e.target.value })}
                className="bg-transparent text-lg font-bold text-text-primary focus:outline-none focus:ring-1 focus:ring-white/20 rounded px-1 -ml-1 transition-all"
                placeholder="Strategy Name"
              />
              {hasUnsavedChanges && (
                <span className="text-[10px] bg-accent-warning/20 text-accent-warning px-2 py-0.5 rounded-full font-medium border border-accent-warning/20">
                  Unsaved
                </span>
              )}
            </div>
            <div className="text-xs text-text-tertiary">
              Last modified: {new Date(currentStrategy.updatedAt).toLocaleTimeString()}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex bg-background-elevated rounded-lg p-1 border border-white/5">
            <button onClick={handleNew} data-testid="btn-new-strategy" className="p-2 hover:bg-white/10 rounded-md text-text-secondary hover:text-white transition-colors tooltip" title="New Strategy">
              <FilePlus size={18} />
            </button>
            <div className="w-[1px] bg-white/10 my-1 mx-1"></div>
            <button onClick={() => setIsLibraryOpen(true)} className="p-2 hover:bg-white/10 rounded-md text-text-secondary hover:text-white transition-colors tooltip" title="Load Strategy">
              <FolderOpen size={18} />
            </button>
          </div>

          <button
            onClick={handleSave}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg border transition-all",
              hasUnsavedChanges ? 'bg-brand text-white border-accent-primary hover:bg-brand/90' : 'bg-background-elevated text-text-secondary border-white/5 hover:bg-white/5 hover:text-white'
            )}
          >
            <Save size={16} />
            <span>Save</span>
          </button>

          <div className="h-8 w-[1px] bg-white/10 mx-1"></div>

          <button
            onClick={handleRunSimulation}
            disabled={isSimulating}
            data-testid="btn-quick-test"
            className="flex items-center gap-2 px-6 py-2 bg-gradient-to-r from-accent-success to-emerald-600 text-white rounded-lg hover:shadow-lg hover:shadow-emerald-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSimulating ? (
              <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></span>
            ) : <Play size={16} fill="currentColor" />}
            <span className="font-medium">Quick Test</span>
          </button>
        </div>
      </header>

      {/* --- Main Content Grid --- */}
      <div className="flex-1 min-h-0 grid grid-cols-12 gap-6 overflow-hidden">

        {/* --- LEFT SIDEBAR: Config --- */}
        <aside className="col-span-3 flex flex-col gap-4 overflow-hidden">
          {/* Asset Settings */}
          <Card className="p-4 flex flex-col gap-4 shrink-0">
            <div className="flex items-center gap-2 text-text-secondary pb-2 border-b border-white/5">
              <BarChart3 size={16} />
              <span className="text-xs font-bold uppercase tracking-wider">Asset Configuration</span>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-[10px] text-text-tertiary mb-1.5 block uppercase tracking-wider font-semibold">Exchange</label>
                <select
                  value={currentStrategy.exchange || 'ZOOMEX'}
                  onChange={(e) => {
                    const newEx = e.target.value as any;
                    const exchangeInfo = getExchange(newEx);
                    updateStrategy({
                      exchange: newEx,
                      fee: exchangeInfo ? exchangeInfo.fees.taker : currentStrategy.fee
                    });
                  }}
                  className="w-full bg-background-secondary border border-white/10 rounded-lg p-2.5 text-sm focus:outline-none focus:border-accent-primary transition-colors"
                >
                  {SUPPORTED_EXCHANGES.map(ex => (
                    <option key={ex.id} value={ex.id}>{ex.name} ({ex.requiresKYC ? 'KYC' : 'No KYC'})</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] text-text-tertiary mb-1.5 block uppercase tracking-wider font-semibold">Instrument</label>
                <select
                  value={currentStrategy.symbol}
                  onChange={(e) => updateStrategy({ symbol: e.target.value })}
                  className="w-full bg-background-secondary border border-white/10 rounded-lg p-2.5 text-sm focus:outline-none focus:border-accent-primary transition-colors"
                >
                  <option value="BTC-PERP">BTC-PERP (Bitcoin)</option>
                  <option value="ETH-PERP">ETH-PERP (Ethereum)</option>
                  <option value="SOL-PERP">SOL-PERP (Solana)</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-text-tertiary mb-1.5 block uppercase tracking-wider font-semibold">Timeframe</label>
                <div className="grid grid-cols-3 gap-2">
                  {['1m', '5m', '15m', '1h', '4h', '1d'].map(tf => (
                    <button
                      key={tf}
                      onClick={() => updateStrategy({ timeframe: tf })}
                      className={cn(
                        "py-2 text-xs font-medium rounded-lg border transition-all",
                        currentStrategy.timeframe === tf ? 'bg-brand text-white border-accent-primary' : 'bg-background-secondary border-transparent text-text-secondary hover:bg-white/5'
                      )}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-text-tertiary mb-1.5 block uppercase tracking-wider font-semibold">Direction</label>
                  <select
                    value={currentStrategy.direction}
                    onChange={(e) => updateStrategy({ direction: e.target.value as any })}
                    className="w-full bg-background-secondary border border-white/10 rounded-lg p-2.5 text-sm focus:outline-none focus:border-accent-primary transition-colors"
                  >
                    <option value="LONG">Long Only</option>
                    <option value="SHORT">Short Only</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-text-tertiary mb-1.5 block uppercase tracking-wider font-semibold">Taker Fee (%)</label>
                  <div className="relative">
                    <input
                      type="number"
                      step="0.01"
                      value={currentStrategy.fee}
                      onChange={(e) => updateStrategy({ fee: parseFloat(e.target.value) })}
                      className="w-full bg-background-secondary border border-white/10 rounded-lg p-2.5 pl-3 pr-6 text-sm focus:outline-none focus:border-accent-primary transition-colors"
                    />
                    <Percent size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary" />
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* Simulation Period */}
          <Card className="p-4 flex flex-col gap-4 shrink-0">
            <div className="flex items-center gap-2 text-text-secondary pb-2 border-b border-white/5">
              <Calendar size={16} />
              <span className="text-xs font-bold uppercase tracking-wider">Quick Test Range</span>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] text-text-tertiary mb-1 block">Start Date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-background-secondary border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-accent-primary"
                />
              </div>
              <div>
                <label className="text-[10px] text-text-tertiary mb-1 block">End Date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-background-secondary border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-accent-primary"
                />
              </div>
            </div>
          </Card>

          {/* Indicators */}
          <Card className="flex-1 flex flex-col min-h-0" noPadding>
            <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.02]">
              <div className="flex items-center gap-2 text-text-secondary">
                <Activity size={16} />
                <span className="text-xs font-bold uppercase tracking-wider">Active Indicators</span>
              </div>
              <button onClick={addIndicator} data-testid="btn-add-indicator" className="p-1.5 bg-brand/10 text-brand hover:bg-brand hover:text-white rounded-md transition-all">
                <Plus size={14} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
              {currentStrategy.indicators.length === 0 && (
                <div className="flex flex-col items-center justify-center h-32 text-center text-text-tertiary opacity-70 border-2 border-dashed border-white/5 rounded-xl">
                  <Activity size={24} className="mb-2" />
                  <span className="text-xs">No indicators added</span>
                </div>
              )}
              {currentStrategy.indicators.map((ind) => (
                <div key={ind.id} className="bg-background-elevated text-foreground border border-white/5 p-3 relative group hover:border-white/10 transition-colors">
                  <div className="flex justify-between items-center mb-3">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full shadow-sm shadow-black/50" style={{ backgroundColor: ind.color }}></div>
                      <span className="font-bold text-sm text-white">{ind.type}</span>
                    </div>
                    <span className="text-[10px] font-mono text-text-tertiary opacity-60">ID: {ind.id.split('_')[1]}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <label className="text-[10px] text-text-secondary uppercase font-semibold">Period</label>
                    <input
                      type="number"
                      value={ind.period}
                      onChange={(e) => {
                        const val = parseInt(e.target.value);
                        const updated = currentStrategy.indicators.map(i => i.id === ind.id ? { ...i, period: val } : i);
                        updateStrategy({ indicators: updated });
                      }}
                      className="w-16 bg-card border border-white/5 rounded px-2 py-1 text-xs focus:outline-none focus:border-accent-primary text-center"
                    />
                    <div className="flex-1"></div>
                    <button
                      onClick={() => removeIndicator(ind.id)}
                      className="text-text-tertiary hover:text-accent-danger hover:bg-accent-danger/10 p-1.5 rounded transition-colors"
                      title="Remove Indicator"
                      data-testid={`btn-remove-indicator-${ind.id}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </aside>

        {/* --- RIGHT CONTENT: Logic & Results --- */}
        <main className="col-span-9 flex flex-col gap-4 overflow-y-auto custom-scrollbar pr-2 pb-4">

          {/* Logic Section */}
          <div className="grid grid-cols-2 gap-4 shrink-0">
            {/* Entry Rules */}
            <Card className="flex flex-col min-h-[320px] border-t-4 border-t-accent-success" noPadding data-testid="panel-entry-strategy">
              <div className="p-4 border-b border-white/5 flex justify-between items-center bg-accent-success/5">
                <div className="flex items-center gap-2">
                  <Zap size={18} className="text-accent-success" />
                  <div>
                    <h3 className="text-sm font-bold text-white">Entry Strategy</h3>
                    <p className="text-[10px] text-accent-success/80 font-medium">Conditions to Open Position ({currentStrategy.direction === 'LONG' ? 'Long' : 'Short'})</p>
                  </div>
                </div>
                <button onClick={() => addRule('entry')} data-testid="btn-add-rule-entry" className="text-xs flex items-center gap-1 px-2 py-1.5 bg-background-elevated hover:bg-white/10 text-white rounded border border-white/10 transition-colors">
                  <Plus size={12} /> Add Rule
                </button>
              </div>
              <div className="flex-1 p-4 space-y-3 bg-background-tertiary/30">
                {currentStrategy.entryRules.length === 0 && (
                  <div className="h-full flex flex-col items-center justify-center text-text-tertiary border-2 border-dashed border-white/5 rounded-xl p-6 text-center">
                    <Zap size={24} className="mb-2 opacity-50" />
                    <p className="text-sm font-medium">Always {currentStrategy.direction === 'LONG' ? 'Buy' : 'Sell'}</p>
                    <p className="text-xs mt-1 max-w-[200px]">Without rules, the strategy will enter a trade immediately on every candle.</p>
                  </div>
                )}
                {currentStrategy.entryRules.map(rule => (
                  <RuleEditor key={rule.id} rule={rule} type="entry" onDelete={() => removeRule('entry', rule.id)} />
                ))}
              </div>
            </Card>

            {/* Exit Rules */}
            <Card className="flex flex-col min-h-[320px] border-t-4 border-t-accent-danger" noPadding>
              <div className="p-4 border-b border-white/5 flex justify-between items-center bg-accent-danger/5">
                <div className="flex items-center gap-2">
                  <Box size={18} className="text-accent-danger" />
                  <div>
                    <h3 className="text-sm font-bold text-white">Exit Strategy</h3>
                    <p className="text-[10px] text-accent-danger/80 font-medium">Conditions to Close Position</p>
                  </div>
                </div>
                <button onClick={() => addRule('exit')} className="text-xs flex items-center gap-1 px-2 py-1.5 bg-background-elevated hover:bg-white/10 text-white rounded border border-white/10 transition-colors">
                  <Plus size={12} /> Add Rule
                </button>
              </div>
              <div className="flex-1 p-4 space-y-3 bg-background-tertiary/30">
                {currentStrategy.exitRules.length === 0 && (
                  <div className="h-full flex flex-col items-center justify-center text-text-tertiary border-2 border-dashed border-white/5 rounded-xl p-6 text-center">
                    <RotateCcw size={24} className="mb-2 opacity-50" />
                    <p className="text-sm font-medium">Manual Close Only</p>
                    <p className="text-xs mt-1 max-w-[200px]">Trades will stay open until equity runs out or manual intervention.</p>
                  </div>
                )}
                {currentStrategy.exitRules.map(rule => (
                  <RuleEditor key={rule.id} rule={rule} type="exit" onDelete={() => removeRule('exit', rule.id)} />
                ))}
              </div>
            </Card>
          </div>

          {/* Results Section */}
          {fullResult ? (
            <BacktestResultsView
              result={fullResult}
              timeframe={currentStrategy.timeframe}
              onSave={handleSaveResult}
              isSaved={resultSaved}
              className="mt-2"
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-text-tertiary border-2 border-dashed border-white/5 rounded-2xl min-h-[300px] gap-4 bg-white/[0.01]">
              <div className="w-16 h-16 rounded-full bg-background-elevated flex items-center justify-center text-text-tertiary shadow-inner">
                <Activity size={32} />
              </div>
              <div className="text-center">
                <h3 className="text-lg font-medium text-text-secondary">Ready to Test</h3>
                <p className="text-sm mt-1 max-w-xs mx-auto">Configure your logic and press "Quick Test" to verify performance.</p>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* --- Library Modal --- */}
      {isLibraryOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center animate-fade-in p-4">
          <Card className="w-full max-w-[600px] max-h-[85vh] flex flex-col shadow-2xl border-white/10" noPadding>
            <div className="p-5 border-b border-white/5 flex justify-between items-center bg-background-elevated">
              <h2 className="font-bold text-xl flex items-center gap-3">
                <FolderOpen size={24} className="text-brand" />
                Strategy Library
              </h2>
              <button onClick={() => setIsLibraryOpen(false)} className="p-2 hover:bg-white/10 rounded-full transition-colors"><X size={20} /></button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar bg-background-secondary">
              {strategies.length === 0 && (
                <div className="text-center py-16 flex flex-col items-center opacity-60">
                  <AlertCircle size={48} className="mb-4 text-text-tertiary" />
                  <p className="text-text-secondary">No saved strategies found.</p>
                  <p className="text-xs text-text-tertiary mt-2">Create a new strategy to get started.</p>
                </div>
              )}
              {strategies.map(strat => (
                <div
                  key={strat.id}
                  onClick={() => handleLoad(strat)}
                  className="group p-4 bg-background-primary rounded-xl border border-white/5 hover:border-accent-primary/50 cursor-pointer transition-all hover:shadow-lg hover:shadow-black/20 hover:-translate-y-0.5 relative overflow-hidden"
                >
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-transparent via-white/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>

                  <div className="flex justify-between items-start mb-3">
                    <div>
                      <div className="font-bold text-lg text-white group-hover:text-brand transition-colors flex items-center gap-2">
                        {strat.name}
                        {strat.lastStats && (
                          <div className={cn("text-[10px] px-1.5 py-0.5 rounded font-mono border", strat.lastStats.totalPnL >= 0 ? 'bg-accent-success/10 border-accent-success/20 text-accent-success' : 'bg-accent-danger/10 border-accent-danger/20 text-accent-danger')}>
                            {strat.lastStats.totalPnL >= 0 ? '+' : ''}{strat.lastStats.winRate.toFixed(0)}% WR
                          </div>
                        )}
                      </div>
                      <div className="text-xs text-text-tertiary mt-0.5 flex items-center gap-2">
                        <span className="bg-white/5 px-1.5 py-0.5 rounded text-[10px]">{strat.symbol}</span>
                        <span className="bg-white/5 px-1.5 py-0.5 rounded text-[10px]">{strat.timeframe}</span>
                        {strat.exchange && (
                          <span className="bg-white/5 px-1.5 py-0.5 rounded text-[10px] flex items-center gap-1">
                            {strat.exchange}
                            {getExchange(strat.exchange).requiresKYC === false && <Activity size={8} className="text-accent-success" />}
                          </span>
                        )}
                        <span>•</span>
                        <span>{new Date(strat.updatedAt).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <button onClick={(e) => handleDelete(e, strat.id)} className="p-2 hover:bg-accent-danger/10 text-text-tertiary hover:text-accent-danger rounded-lg transition-colors z-10">
                      <Trash2 size={16} />
                    </button>
                  </div>

                  <div className="flex gap-2 mt-2">
                    <div className="text-[10px] px-2 py-1 bg-background-elevated rounded border border-white/5 text-text-secondary flex items-center gap-1.5">
                      <Activity size={10} /> {strat.indicators.length} Indicators
                    </div>
                    <div className="text-[10px] px-2 py-1 bg-background-elevated rounded border border-white/5 text-text-secondary flex items-center gap-1.5">
                      <Zap size={10} /> {strat.entryRules.length} Entry Rules
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};
