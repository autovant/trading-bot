
import { TradeSuggestion, MarketAnalysis } from '@/types';

/**
 * Mocks chatting with AI
 */
export const chatWithAi = async (message: string, context: string): Promise<string> => {
    return new Promise(resolve => {
        setTimeout(() => {
            resolve(`This is a mock AI response to: "${message}". Context: ${context}`);
        }, 800);
    });
};

/**
 * Mocks analyzing market context to return sentiment/levels
 */
export const analyzeMarketContext = async (
    candles: any[],
    positions: any[],
    currentPrice: number,
    orderBook: any
): Promise<MarketAnalysis> => {
    return new Promise(resolve => {
        setTimeout(() => {
            resolve({
                symbol: 'BTC-PERP',
                sentiment: Math.random() > 0.5 ? 'BULLISH' : 'BEARISH',
                summary: "Market is showing consolidation with mild bullish divergence on the 1h timeframe. Order flow indicates buy pressure support at 42000.",
                supportLevel: currentPrice * 0.98,
                resistanceLevel: currentPrice * 1.02,
                signal: Math.random() > 0.5 ? 'LONG' : 'SHORT',
                confidence: 75
            });
        }, 1000);
    });
};

/**
 * Mocks generating a specific trade suggestion
 */
export const generateTradeSuggestion = async (
    candles: any[],
    currentPrice: number,
    orderBook: any
): Promise<TradeSuggestion> => {
    return new Promise(resolve => {
        setTimeout(() => {
            const direction = Math.random() > 0.5 ? 'LONG' : 'SHORT';
            resolve({
                symbol: 'BTC-PERP',
                direction,
                entryPrice: currentPrice,
                takeProfit: direction === 'LONG' ? currentPrice * 1.05 : currentPrice * 0.95,
                stopLoss: direction === 'LONG' ? currentPrice * 0.98 : currentPrice * 1.02,
                confidence: 82,
                reasoning: "Breakout of 20 SMA with volume confirmation."
            });
        }, 1200);
    });
};
