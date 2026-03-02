
import { BacktestResult, BacktestStats, BacktestTrade, Candle, EquityPoint, RuleCondition, Side, StrategyConfig } from "@/types";

// --- Math Helpers ---

const calculateSMA = (data: number[], period: number): number[] => {
    const results = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            results.push(NaN);
            continue;
        }
        const slice = data.slice(i - period + 1, i + 1);
        const sum = slice.reduce((a, b) => a + b, 0);
        results.push(sum / period);
    }
    return results;
};

const calculateEMA = (data: number[], period: number): number[] => {
    const results = [];
    const k = 2 / (period + 1);
    let ema = data[0];
    results.push(ema);

    for (let i = 1; i < data.length; i++) {
        ema = data[i] * k + ema * (1 - k);
        results.push(ema);
    }
    return results;
};

const calculateRSI = (data: number[], period: number): number[] => {
    const results = [];
    let gains = 0;
    let losses = 0;

    // First RSI
    for (let i = 1; i <= period; i++) {
        const diff = data[i] - data[i - 1];
        if (diff >= 0) gains += diff;
        else losses -= diff;
    }

    let avgGain = gains / period;
    let avgLoss = losses / period;
    results[period] = 100 - (100 / (1 + avgGain / avgLoss));

    // Subsequent RSIs
    for (let i = period + 1; i < data.length; i++) {
        const diff = data[i] - data[i - 1];
        const gain = diff >= 0 ? diff : 0;
        const loss = diff < 0 ? -diff : 0;

        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;

        if (avgLoss === 0) results.push(100);
        else {
            const rs = avgGain / avgLoss;
            results.push(100 - (100 / (1 + rs)));
        }
    }

    // Fill initial NaNs
    const padded = new Array(period).fill(NaN).concat(results.slice(period));
    while (padded.length < data.length) padded.unshift(NaN);
    return padded.slice(0, data.length);
};

// --- Statistics Calculation Helper ---

export const calculateBacktestStats = (
    trades: BacktestTrade[],
    equityCurve: EquityPoint[],
    timeframe: string
): BacktestStats => {
    const initialEquity = equityCurve.length > 0 ? equityCurve[0].value : 10000;
    const finalEquity = equityCurve.length > 0 ? equityCurve[equityCurve.length - 1].value : initialEquity;

    const totalPnL = finalEquity - initialEquity;

    const winningTrades = trades.filter(t => t.pnl > 0);
    const losingTrades = trades.filter(t => t.pnl <= 0);
    const winRate = trades.length > 0 ? (winningTrades.length / trades.length) * 100 : 0;

    const grossProfit = winningTrades.reduce((acc, t) => acc + t.pnl, 0);
    const grossLoss = Math.abs(losingTrades.reduce((acc, t) => acc + t.pnl, 0));
    const profitFactor = grossLoss === 0 ? grossProfit : grossProfit / grossLoss;

    // Max Drawdown Calculation
    let peakEquity = -Infinity;
    let maxDrawdownValue = 0;
    let maxDrawdownPercent = 0;
    const returns: number[] = [];

    for (let i = 0; i < equityCurve.length; i++) {
        const val = equityCurve[i].value;
        if (val > peakEquity) peakEquity = val;

        const dd = peakEquity - val;
        const ddPercent = peakEquity > 0 ? dd / peakEquity : 0;

        if (ddPercent > maxDrawdownPercent) {
            maxDrawdownPercent = ddPercent;
            maxDrawdownValue = dd;
        }

        // Returns for Sharpe (using log returns or simple returns)
        // Ensure we handle the first point correctly
        if (i > 0) {
            const prev = equityCurve[i - 1].value;
            if (prev !== 0) {
                returns.push((val - prev) / prev);
            } else {
                returns.push(0);
            }
        }
    }

    // Advanced Metrics: Sharpe & Sortino
    let periodsPerYear = 525600; // 1m default
    if (timeframe === '5m') periodsPerYear = 105120;
    if (timeframe === '15m') periodsPerYear = 35040;
    if (timeframe === '1h') periodsPerYear = 8760;
    if (timeframe === '4h') periodsPerYear = 2190;
    if (timeframe === '1d') periodsPerYear = 365;

    const annualizedFactor = Math.sqrt(periodsPerYear);
    const avgReturn = returns.reduce((sum, r) => sum + r, 0) / (returns.length || 1);

    const variance = returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / (returns.length || 1);
    const stdDev = Math.sqrt(variance);

    const downsideVariance = returns.reduce((sum, r) => {
        const rDown = Math.min(r, 0);
        return sum + Math.pow(rDown, 2);
    }, 0) / (returns.length || 1);
    const downsideDev = Math.sqrt(downsideVariance);

    const sharpeRatio = stdDev < 0.0000001 ? 0 : (avgReturn / stdDev) * annualizedFactor;
    const sortinoRatio = downsideDev < 0.0000001 ? 0 : (avgReturn / downsideDev) * annualizedFactor;

    return {
        totalTrades: trades.length,
        winRate,
        profitFactor,
        totalPnL,
        maxDrawdown: maxDrawdownValue,
        maxDrawdownPercent: maxDrawdownPercent * 100,
        sharpeRatio,
        sortinoRatio
    };
};


// --- Backtest Engine ---

interface ActiveTradeState {
    entryTime: string;
    entryPrice: number;
    entryIndex: number;
    side: Side;
    initialCollateral: number; // The cash put into the trade (Balance - Entry Fee)
    positionSize: number; // Units of asset
}

export const runBacktest = (candles: Candle[], strategy: StrategyConfig): BacktestResult => {
    const closes = candles.map(c => c.close);

    // 1. Calculate Indicators
    const indicatorValues: Record<string, number[]> = {};

    strategy.indicators.forEach(ind => {
        if (ind.type === 'SMA') indicatorValues[ind.id] = calculateSMA(closes, ind.period);
        if (ind.type === 'EMA') indicatorValues[ind.id] = calculateEMA(closes, ind.period);
        if (ind.type === 'RSI') indicatorValues[ind.id] = calculateRSI(closes, ind.period);
    });

    // 2. Simulation Loop
    const trades: BacktestTrade[] = [];
    let activeTrade: ActiveTradeState | null = null;
    let balance = 10000; // Cash balance (Realized Equity)
    const feeRate = (strategy.fee || 0.1) / 100; // e.g., 0.1% -> 0.001

    const START_INDEX = 50;

    const equityCurve: EquityPoint[] = [{
        time: candles[START_INDEX - 1].time,
        value: balance,
        candleIndex: START_INDEX - 1
    }];

    for (let i = START_INDEX; i < candles.length; i++) {
        const candle = candles[i];
        const price = candle.close;
        const time = candle.time;

        // Helper to get value
        const getValue = (source: string): number => {
            if (source === 'PRICE') return price;
            if (!isNaN(Number(source))) return Number(source);
            return indicatorValues[source]?.[i] || 0;
        };

        const checkRules = (rules: RuleCondition[]): boolean => {
            if (rules.length === 0) return false;
            return rules.every(rule => {
                const left = getValue(rule.left);
                const right = getValue(rule.right);

                if (isNaN(left) || isNaN(right)) return false;

                if (rule.operator === '>') return left > right;
                if (rule.operator === '<') return left < right;
                if (rule.operator === '==') return Math.abs(left - right) < 0.0001;
                return false;
            });
        };

        let currentEquity = balance;

        if (activeTrade) {
            // --- 1. Calculate Floating Equity (Mark-to-Market) ---

            let unrealizedPnL = 0;
            if (activeTrade.side === Side.BUY) {
                unrealizedPnL = (price - activeTrade.entryPrice) * activeTrade.positionSize;
            } else {
                unrealizedPnL = (activeTrade.entryPrice - price) * activeTrade.positionSize;
            }

            // Equity = Collateral + PnL
            // Note: We don't deduct exit fee here for the visual curve, usually only realized on exit.
            // But strict equity would include "cost to close". Let's stick to Mark-to-Market value.
            currentEquity = activeTrade.initialCollateral + unrealizedPnL;


            // --- 2. Check Exit Rules ---
            if (checkRules(strategy.exitRules)) {
                // Execute Exit
                const exitPrice = price;

                // Calculate Notional Value at Exit
                const exitNotional = activeTrade.positionSize * exitPrice;
                const exitFee = exitNotional * feeRate;

                let tradePnL = 0;
                if (activeTrade.side === Side.BUY) {
                    tradePnL = (exitPrice - activeTrade.entryPrice) * activeTrade.positionSize;
                } else {
                    tradePnL = (activeTrade.entryPrice - exitPrice) * activeTrade.positionSize;
                }

                // Final Balance = Collateral + PnL - Exit Fee
                const netBalance = activeTrade.initialCollateral + tradePnL - exitFee;

                const grossPnL = tradePnL;
                const entryFee = (activeTrade.positionSize * activeTrade.entryPrice) * feeRate;
                const netPnL = grossPnL - entryFee - exitFee;

                // Update Main Balance
                balance = netBalance;
                currentEquity = balance;

                trades.push({
                    id: Math.random().toString(36),
                    entryTime: activeTrade.entryTime,
                    entryPrice: activeTrade.entryPrice,
                    entryIndex: activeTrade.entryIndex,
                    exitTime: time,
                    exitPrice,
                    exitIndex: i,
                    side: activeTrade.side,
                    pnl: netPnL,
                    pnlPercent: (netPnL / (activeTrade.initialCollateral + entryFee)) * 100 // ROI on initial capital
                });

                activeTrade = null;
            }
        } else {
            // --- Check Entry Rules ---
            if (checkRules(strategy.entryRules)) {

                const side = strategy.direction === 'LONG' ? Side.BUY : Side.SELL;

                // Position Sizing: Use 100% of balance (Compounding)
                // Fee is taken from notional.

                const positionSize = balance / (price * (1 + feeRate));
                const entryFee = positionSize * price * feeRate;
                const initialCollateral = balance - entryFee;

                // Immediately update equity to reflect fee
                currentEquity = initialCollateral;

                activeTrade = {
                    entryTime: time,
                    entryPrice: price,
                    entryIndex: i,
                    side: side,
                    initialCollateral: initialCollateral,
                    positionSize: positionSize
                };
            }
        }

        equityCurve.push({ time, value: currentEquity, candleIndex: i });
    }

    const stats = calculateBacktestStats(trades, equityCurve, strategy.timeframe);

    return {
        ...stats,
        equityCurve,
        trades
    };
};
