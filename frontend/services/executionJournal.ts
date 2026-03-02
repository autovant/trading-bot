import { ExecutionUpdate } from '@/types';

export interface ExecutionJournalEntry extends ExecutionUpdate {
    recordedAt: number;
}

export const EXECUTION_JOURNAL_KEY = 'cupertino_execution_journal_v1';
const MAX_ENTRIES = 5000;

let cache: ExecutionJournalEntry[] | null = null;
let idCache: Set<string> | null = null;

const ensureLoaded = () => {
    if (cache && idCache) return;
    cache = [];
    idCache = new Set<string>();

    if (typeof window === 'undefined') return;
    try {
        const raw = localStorage.getItem(EXECUTION_JOURNAL_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw) as ExecutionJournalEntry[];
        if (Array.isArray(parsed)) {
            cache = parsed;
            idCache = new Set(parsed.map(entry => entry.eventId));
        }
    } catch (e) {
        cache = [];
        idCache = new Set<string>();
    }
};

const persist = () => {
    if (typeof window === 'undefined' || !cache) return;
    try {
        localStorage.setItem(EXECUTION_JOURNAL_KEY, JSON.stringify(cache));
    } catch (e) {
        // Ignore persistence failures; journal remains in memory.
    }
};

export const ExecutionJournal = {
    hasEvent: (eventId: string): boolean => {
        ensureLoaded();
        return idCache?.has(eventId) ?? false;
    },

    record: (update: ExecutionUpdate): boolean => {
        ensureLoaded();
        if (!cache || !idCache) return false;
        if (idCache.has(update.eventId)) return false;

        const entry: ExecutionJournalEntry = {
            ...update,
            recordedAt: Date.now()
        };

        cache.push(entry);
        idCache.add(entry.eventId);

        if (cache.length > MAX_ENTRIES) {
            const overflow = cache.length - MAX_ENTRIES;
            const removed = cache.splice(0, overflow);
            removed.forEach(item => idCache?.delete(item.eventId));
        }

        persist();
        return true;
    },

    getEntries: (): ExecutionJournalEntry[] => {
        ensureLoaded();
        return cache ? [...cache] : [];
    },

    getOrderEntries: (orderId: string): ExecutionJournalEntry[] => {
        ensureLoaded();
        if (!cache) return [];
        return cache.filter(entry => entry.orderId === orderId);
    },

    getLatestSequence: (orderId: string): number => {
        ensureLoaded();
        if (!cache) return 0;
        return cache.reduce((max, entry) => {
            if (entry.orderId !== orderId) return max;
            return Math.max(max, entry.sequence);
        }, 0);
    },

    clear: () => {
        cache = [];
        idCache = new Set<string>();
        if (typeof window === 'undefined') return;
        localStorage.removeItem(EXECUTION_JOURNAL_KEY);
    }
};
