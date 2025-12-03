import { useEffect, useRef, useState, useCallback } from 'react';

interface UseWebSocketOptions<T> {
    onOpen?: () => void;
    onClose?: () => void;
    onError?: (event: Event) => void;
    onMessage?: (data: T) => void;
    shouldConnect?: boolean;
    reconnectInterval?: number;
    validator?: (data: unknown) => data is T;
}

export function useWebSocket<T>(url: string, options: UseWebSocketOptions<T> = {}) {
    const {
        onOpen,
        onClose,
        onError,
        onMessage,
        shouldConnect = true,
        reconnectInterval = 3000,
        validator
    } = options;

    const [lastMessage, setLastMessage] = useState<T | null>(null);
    const [isConnected, setIsConnected] = useState(false);

    const ws = useRef<WebSocket | null>(null);
    const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);
    const isMounted = useRef(true);

    // Stable handlers to avoid effect re-triggering
    const handlersRef = useRef({ onOpen, onClose, onError, onMessage, validator });
    useEffect(() => {
        handlersRef.current = { onOpen, onClose, onError, onMessage, validator };
    }, [onOpen, onClose, onError, onMessage, validator]);

    const connect = useCallback(() => {
        if (!shouldConnect) return;
        if (ws.current?.readyState === WebSocket.OPEN || ws.current?.readyState === WebSocket.CONNECTING) return;

        // Clear any pending reconnect
        if (reconnectTimeout.current) {
            clearTimeout(reconnectTimeout.current);
            reconnectTimeout.current = null;
        }

        try {
            const socket = new WebSocket(url);
            ws.current = socket;

            socket.onopen = () => {
                if (!isMounted.current) {
                    socket.close();
                    return;
                }
                console.log(`[WS] Connected to ${url}`);
                setIsConnected(true);
                handlersRef.current.onOpen?.();
            };

            socket.onmessage = (event) => {
                if (!isMounted.current) return;
                try {
                    const parsed = JSON.parse(event.data);
                    const isValid = handlersRef.current.validator ? handlersRef.current.validator(parsed) : true;

                    if (isValid) {
                        setLastMessage(parsed);
                        handlersRef.current.onMessage?.(parsed);
                    } else {
                        console.warn(`[WS] Invalid message format from ${url}`, parsed);
                    }
                } catch (e) {
                    console.error(`[WS] Failed to parse message from ${url}:`, e);
                }
            };

            socket.onclose = () => {
                if (!isMounted.current) return;
                console.log(`[WS] Disconnected from ${url}`);
                setIsConnected(false);
                ws.current = null;
                handlersRef.current.onClose?.();

                // Schedule reconnect
                if (shouldConnect) {
                    reconnectTimeout.current = setTimeout(connect, reconnectInterval);
                }
            };

            socket.onerror = (event) => {
                if (!isMounted.current) return;
                console.error(`[WS] Error on ${url}:`, event);
                handlersRef.current.onError?.(event);
                // Close will trigger onclose, which handles reconnect
                socket.close();
            };

        } catch (e) {
            console.error(`[WS] Connection failed to ${url}:`, e);
            if (shouldConnect && isMounted.current) {
                reconnectTimeout.current = setTimeout(connect, reconnectInterval);
            }
        }
    }, [url, shouldConnect, reconnectInterval]);

    useEffect(() => {
        isMounted.current = true;
        connect();

        return () => {
            isMounted.current = false;
            if (ws.current) {
                ws.current.close();
                ws.current = null;
            }
            if (reconnectTimeout.current) {
                clearTimeout(reconnectTimeout.current);
                reconnectTimeout.current = null;
            }
        };
    }, [connect]);

    return { lastMessage, isConnected };
}
