import useSWR from 'swr';

const fetcher = (url: string) => fetch(url).then(res => res.json());

const API_BASE = 'http://localhost:8080';

export function useMode() {
    const { data, error, mutate } = useSWR(`${API_BASE}/api/mode`, fetcher, { refreshInterval: 5000 });
    return { mode: data, loading: !error && !data, error, mutate };
}

export function usePositions() {
    const { data, error } = useSWR(`${API_BASE}/api/positions?limit=100`, fetcher, { refreshInterval: 2000 });
    return { positions: data, loading: !error && !data, error };
}

export function useTrades() {
    const { data, error } = useSWR(`${API_BASE}/api/trades?limit=50`, fetcher, { refreshInterval: 5000 });
    return { trades: data, loading: !error && !data, error };
}

export function useDailyPnL() {
    const { data, error } = useSWR(`${API_BASE}/api/pnl/daily?days=30`, fetcher, { refreshInterval: 10000 });
    return { pnl: data?.days || [], loading: !error && !data, error };
}
