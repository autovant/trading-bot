export const generateCandlesInRange = (symbol: string, timeframe: string, startDate: string, endDate: string) => {
    // This is a stub for the mock data generator required by BacktestDashboard
    // In a real integration, we should fetch from backend.
    // However, to satisfy the immediate dependency of BacktestDashboard, 
    // we will return a minimal empty array or implement a basic generator.
    // Given the complexity of porting the full generator, I will check if I can fetch 
    // from the backend backtest endpoint instead in the future.
    // For now, let's create a basic valid mock to prevent crashes.

    const candles = [];
    let current = new Date(startDate).getTime();
    const end = new Date(endDate).getTime();
    let price = 40000;

    // Safety Break
    let iterations = 0;
    while (current < end && iterations < 5000) {
        price = price * (1 + (Math.random() - 0.5) * 0.01);
        const open = price;
        const close = price * (1 + (Math.random() - 0.5) * 0.005);
        const high = Math.max(open, close) * 1.002;
        const low = Math.min(open, close) * 0.998;

        candles.push({
            time: new Date(current).toLocaleTimeString(), // Simplified
            open,
            high,
            low,
            close,
            volume: Math.random() * 100,
            timestamp: current
        });

        current += 3600 * 1000; // 1 hour steps roughly
        iterations++;
    }
    return candles;
};
