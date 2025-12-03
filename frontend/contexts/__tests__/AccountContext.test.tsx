import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { AccountDataProvider, useAccount } from '../AccountContext';

// Mock useWebSocket
jest.mock('../../hooks/useWebSocket', () => ({
    useWebSocket: () => ({
        isConnected: true
    })
}));

// Mock fetch
global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
            { symbol: 'BTCUSDT', side: 'buy', size: 1, unrealized_pnl: 100 }
        ]),
    })
) as jest.Mock;

const TestComponent = () => {
    const { positions, executeOrder } = useAccount();
    return (
        <div>
            <div data-testid="positions-count">{positions.length}</div>
            <button onClick={() => executeOrder({ symbol: 'BTCUSDT', side: 'buy', type: 'market', quantity: 1 })}>
                Buy
            </button>
        </div>
    );
};

describe('AccountContext', () => {
    it('should fetch positions on mount', async () => {
        await act(async () => {
            render(
                <AccountDataProvider>
                    <TestComponent />
                </AccountDataProvider>
            );
        });

        expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/api/positions'));
        expect(screen.getByTestId('positions-count')).toHaveTextContent('1');
    });

    it('should call executeOrder API', async () => {
        await act(async () => {
            render(
                <AccountDataProvider>
                    <TestComponent />
                </AccountDataProvider>
            );
        });

        const btn = screen.getByText('Buy');
        await act(async () => {
            btn.click();
        });

        expect(global.fetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/orders'),
            expect.objectContaining({
                method: 'POST',
                body: expect.stringContaining('BTCUSDT')
            })
        );
    });
});
