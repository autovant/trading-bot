import { Order } from '@/types';

export interface OrderIdempotencyEntry {
    key: string;
    orderId: string;
    createdAt: number;
    source: 'paper' | 'live';
}

const STORAGE_KEY = 'cupertino_order_idempotency_v1';
const MAX_ENTRIES = 5000;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

let cache: OrderIdempotencyEntry[] | null = null;
let keyCache: Map<string, OrderIdempotencyEntry> | null = null;

const ensureLoaded = () => {
    if (cache && keyCache) return;
    cache = [];
    keyCache = new Map();

    if (typeof window === 'undefined') return;
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw) as OrderIdempotencyEntry[];
        if (Array.isArray(parsed)) {
            cache = parsed;
            keyCache = new Map(parsed.map(entry => [entry.key, entry]));
        }
    } catch (e) {
        cache = [];
        keyCache = new Map();
    }
};

const persist = () => {
    if (typeof window === 'undefined' || !cache) return;
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
    } catch (e) {
        // Ignore persistence failures; idempotency lives in memory for this session.
    }
};

const prune = () => {
    if (!cache || !keyCache) return;
    const now = Date.now();
    cache = cache.filter(entry => now - entry.createdAt <= MAX_AGE_MS);

    if (cache.length > MAX_ENTRIES) {
        cache = cache.slice(cache.length - MAX_ENTRIES);
    }

    keyCache = new Map(cache.map(entry => [entry.key, entry]));
    persist();
};

export const OrderIdempotency = {
    has: (key: string): boolean => {
        ensureLoaded();
        return keyCache?.has(key) ?? false;
    },

    get: (key: string): OrderIdempotencyEntry | null => {
        ensureLoaded();
        return keyCache?.get(key) ?? null;
    },

    record: (entry: OrderIdempotencyEntry): boolean => {
        ensureLoaded();
        if (!cache || !keyCache) return false;
        if (keyCache.has(entry.key)) return false;

        cache.push(entry);
        keyCache.set(entry.key, entry);
        prune();
        return true;
    },

    hydrate: (orders: Order[]): void => {
        ensureLoaded();
        const localCache = cache;
        const localKeyCache = keyCache;
        if (!localCache || !localKeyCache) return;

        orders.forEach(order => {
            const key = order.idempotencyKey || order.id;
            if (!localKeyCache.has(key)) {
                localCache.push({
                    key,
                    orderId: order.id,
                    createdAt: order.timestamp,
                    source: order.isSimulation ? 'paper' : 'live'
                });
                localKeyCache.set(key, localCache[localCache.length - 1]);
            }
        });
        prune();
    },

    clear: () => {
        cache = [];
        keyCache = new Map();
        if (typeof window === 'undefined') return;
        localStorage.removeItem(STORAGE_KEY);
    }
};
