import { ExchangeId } from '@/types';

export interface ExchangeInfo {
    id: ExchangeId;
    name: string;
    description: string;
    requiresKYC: boolean;
    fees: {
        maker: number;
        taker: number;
    };
    color: string;
}

export const SUPPORTED_EXCHANGES: ExchangeInfo[] = [
    {
        id: 'ZOOMEX',
        name: 'Zoomex',
        description: 'No KYC, High Liquidity',
        requiresKYC: false,
        fees: { maker: 0.02, taker: 0.06 },
        color: '#FFD700' // Gold-ish
    },
    {
        id: 'BYBIT',
        name: 'Bybit',
        description: 'Deep Depth, Top Tier',
        requiresKYC: true,
        fees: { maker: 0.01, taker: 0.06 },
        color: '#F7931A' // Orange
    },
    {
        id: 'MEXC',
        name: 'MEXC',
        description: 'Lowest Fees, No KYC',
        requiresKYC: false,
        fees: { maker: 0.00, taker: 0.01 },
        color: '#22C55E' // Green
    },
    {
        id: 'BINGX',
        name: 'BingX',
        description: 'Social Trading, No KYC',
        requiresKYC: false,
        fees: { maker: 0.02, taker: 0.05 },
        color: '#3B82F6' // Blue
    },
    {
        id: 'PHEMEX',
        name: 'Phemex',
        description: 'Fast Execution, No KYC',
        requiresKYC: false,
        fees: { maker: 0.01, taker: 0.06 },
        color: '#A855F7' // Purple
    }
];

export const getExchange = (id: ExchangeId) => SUPPORTED_EXCHANGES.find(e => e.id === id) || SUPPORTED_EXCHANGES[0];
