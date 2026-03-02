
import { StrategyConfig, BacktestRecord } from '@/types';

const STRATEGIES_KEY = 'cupertino_strategies';
const HISTORY_KEY = 'cupertino_backtest_history';

export const DEFAULT_STRATEGY: StrategyConfig = {
    id: 'default_template',
    name: 'RSI Mean Reversion',
    description: 'Basic mean reversion strategy using RSI overbought/oversold levels.',
    updatedAt: Date.now(),
    symbol: 'BTC-PERP',
    exchange: 'ZOOMEX',
    timeframe: '15m',
    direction: 'LONG',
    fee: 0.06,
    indicators: [
        { id: 'ind_rsi', type: 'RSI', period: 14, color: '#A855F7' },
        { id: 'ind_sma', type: 'SMA', period: 200, color: '#3B82F6' }
    ],
    entryRules: [
        { id: 'rule_entry_1', left: 'ind_rsi', operator: '<', right: '30' }
    ],
    exitRules: [
        { id: 'rule_exit_1', left: 'ind_rsi', operator: '>', right: '70' }
    ]
};

export const getStrategies = (): StrategyConfig[] => {
    if (typeof window === 'undefined') return [DEFAULT_STRATEGY];
    try {
        const stored = localStorage.getItem(STRATEGIES_KEY);
        // Ensure loaded strategies have the new fields if they were saved before schema update
        const strategies = stored ? JSON.parse(stored) : [DEFAULT_STRATEGY];
        return strategies.map((s: any) => ({
            ...s,
            direction: s.direction || 'LONG',
            fee: s.fee !== undefined ? s.fee : 0.06,
            exchange: s.exchange || 'ZOOMEX'
        }));
    } catch (e) {
        console.error("Failed to load strategies", e);
        return [DEFAULT_STRATEGY];
    }
};

export const saveStrategy = (strategy: StrategyConfig): void => {
    const strategies = getStrategies();
    const index = strategies.findIndex(s => s.id === strategy.id);

    // Update timestamp
    const strategyToSave = { ...strategy, updatedAt: Date.now() };

    if (index >= 0) {
        strategies[index] = strategyToSave;
    } else {
        strategies.push(strategyToSave);
    }
    localStorage.setItem(STRATEGIES_KEY, JSON.stringify(strategies));
};

export const deleteStrategy = (id: string): void => {
    const strategies = getStrategies().filter(s => s.id !== id);
    localStorage.setItem(STRATEGIES_KEY, JSON.stringify(strategies));
};

export const createNewStrategy = (): StrategyConfig => {
    return {
        id: `strat_${Date.now()}`,
        name: 'Untitled Strategy',
        description: 'New custom strategy',
        updatedAt: Date.now(),
        symbol: 'BTC-PERP',
        exchange: 'ZOOMEX',
        timeframe: '15m',
        direction: 'LONG',
        fee: 0.06,
        indicators: [],
        entryRules: [],
        exitRules: []
    };
};

// --- Backtest History Storage ---

export const getBacktestHistory = (): BacktestRecord[] => {
    if (typeof window === 'undefined') return [];
    try {
        const stored = localStorage.getItem(HISTORY_KEY);
        return stored ? JSON.parse(stored) : [];
    } catch (e) {
        return [];
    }
};

export const saveBacktestResult = (record: BacktestRecord): void => {
    const history = getBacktestHistory();
    // Keep last 50 runs to avoid overflow
    const newHistory = [record, ...history].slice(0, 50);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(newHistory));
};

export const deleteBacktestRecord = (id: string): void => {
    const history = getBacktestHistory().filter(h => h.id !== id);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
};

export const clearBacktestHistory = (): void => {
    localStorage.removeItem(HISTORY_KEY);
};
