
import { ExchangeApiConfig, ExchangeId } from '@/types';

const STORAGE_KEY = 'cupertino_secure_vault_v1';

/**
 * MOCK ENCRYPTION
 * In a production environment, this would interface with a secure backend vault
 * (e.g., HashiCorp Vault, AWS Secrets Manager) or use WebCrypto API with 
 * a user-derived key that is never stored.
 * 
 * For this demo, we use Base64 + Salt to obfuscate and simulate the architecture.
 */
const SALT = "cupertino_institutional_salt_";

const encrypt = (value: string): string => {
    if (!value) return '';
    try {
        if (typeof window === 'undefined') return value;
        return window.btoa(SALT + value);
    } catch (e) {
        console.error("Encryption failed", e);
        return '';
    }
};

const decrypt = (value: string): string => {
    if (!value) return '';
    try {
        if (typeof window === 'undefined') return value;
        const decoded = window.atob(value);
        if (decoded.startsWith(SALT)) {
            return decoded.substring(SALT.length);
        }
        return ''; // Tampered or invalid
    } catch (e) {
        console.error("Decryption failed", e);
        return '';
    }
};

export const SecureStorage = {
    getAllConfigs: (): ExchangeApiConfig[] => {
        if (typeof window === 'undefined') return [];
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            return JSON.parse(raw);
        } catch (e) {
            console.error("Vault access failed", e);
            return [];
        }
    },

    saveConfig: (config: ExchangeApiConfig): void => {
        const current = SecureStorage.getAllConfigs();
        const existingIndex = current.findIndex(c => c.exchangeId === config.exchangeId);

        // Encrypt secrets before storage
        const securedConfig = {
            ...config,
            apiKey: config.apiKey.startsWith(SALT) ? config.apiKey : encrypt(config.apiKey), // Avoid double encrypting if reading from state
            apiSecret: config.apiSecret.startsWith(SALT) ? config.apiSecret : encrypt(config.apiSecret)
        };

        if (existingIndex >= 0) {
            current[existingIndex] = securedConfig;
        } else {
            current.push(securedConfig);
        }

        localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
    },

    getConfig: (exchangeId: ExchangeId): ExchangeApiConfig | undefined => {
        const configs = SecureStorage.getAllConfigs();
        return configs.find(c => c.exchangeId === exchangeId);
    },

    /**
     * Retrieves DECRYPTED credentials for execution engine.
     * WARNING: Never log the output of this function.
     */
    getCredentials: (exchangeId: ExchangeId): { apiKey: string, apiSecret: string } | null => {
        const config = SecureStorage.getConfig(exchangeId);
        if (!config || !config.isActive) return null;

        // Handle cases where we might have stored plain text in dev vs encrypted
        const rawKey = config.apiKey;
        const rawSecret = config.apiSecret;

        // Try decrypt, fallback to raw if valid (legacy dev support)
        let key = decrypt(rawKey);
        let secret = decrypt(rawSecret);

        if (!key && rawKey) key = rawKey; // Fallback for dev
        if (!secret && rawSecret) secret = rawSecret;

        if (!key || !secret) return null;

        return { apiKey: key, apiSecret: secret };
    }
};
