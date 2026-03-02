
import React, { useState, useEffect } from 'react';
import { Card } from '@/components/ui/Card';
import { Radio, Zap, CheckCircle2, XCircle, Clock, Play, Copy, RefreshCw, Settings2 } from 'lucide-react';
import { cn } from '@/lib/utils';

// Types (Ideally should be in types/index.ts)
interface TradingSignal {
    id: string;
    symbol: string;
    side: 'BUY' | 'SELL';
    orderType: 'MARKET' | 'LIMIT' | 'STOP';
    size: number;
    price?: number;
    source: string;
    message?: string;
    timestamp: number;
    status: 'PENDING' | 'VALIDATED' | 'EXECUTED' | 'REJECTED' | 'EXPIRED';
    orderId?: string;
    error?: string;
}

interface SignalConfig {
    autoExecute: boolean;
    defaultSize: number;
    maxSignalsPerMinute: number;
    webhookSecret?: string;
}

const BACKEND_URL = 'http://localhost:8000'; // Updated to 8000 for FastAPI

export const SignalsPanel: React.FC = () => {
    const [signals, setSignals] = useState<TradingSignal[]>([]);
    const [config, setConfig] = useState<SignalConfig>({
        autoExecute: false,
        defaultSize: 0.01,
        maxSignalsPerMinute: 10
    });
    const [isLoading, setIsLoading] = useState(false);
    const [webhookUrl, setWebhookUrl] = useState('');
    const [copied, setCopied] = useState(false);

    // Generate webhook URL
    useEffect(() => {
        // Fallback or window location
        if (typeof window !== 'undefined') {
            const baseUrl = window.location.origin.replace(':3000', ':8000');
            setWebhookUrl(`${baseUrl}/api/webhook/tradingview`);
        }
    }, []);

    // Fetch signals
    const fetchSignals = async () => {
        try {
            // Mocking for now if endpoint doesn't exist
            // const res = await fetch(`${BACKEND_URL}/api/signals?limit=20`);
            // const data = await res.json();
            // setSignals(data);
            setSignals([]);
        } catch (e) {
            console.error('Failed to fetch signals:', e);
        }
    };

    // Fetch config
    const fetchConfig = async () => {
        try {
            // const res = await fetch(`${BACKEND_URL}/api/signals/config`);
            // const data = await res.json();
            // setConfig(data);
        } catch (e) {
            console.error('Failed to fetch config:', e);
        }
    };

    useEffect(() => {
        fetchSignals();
        fetchConfig();
        const interval = setInterval(fetchSignals, 5000);
        return () => clearInterval(interval);
    }, []);

    const updateConfig = async (updates: Partial<SignalConfig>) => {
        try {
            const newConfig = { ...config, ...updates };
            setConfig(newConfig);
            // await fetch(`${BACKEND_URL}/api/signals/config`, {
            //     method: 'POST',
            //     headers: { 'Content-Type': 'application/json' },
            //     body: JSON.stringify(updates)
            // });
        } catch (e) {
            console.error('Failed to update config:', e);
        }
    };

    const executeSignal = async (signalId: string) => {
        setIsLoading(true);
        try {
            await fetch(`${BACKEND_URL}/api/signals/${signalId}/execute`, {
                method: 'POST'
            });
            await fetchSignals();
        } catch (e) {
            console.error('Failed to execute signal:', e);
        }
        setIsLoading(false);
    };

    const copyWebhookUrl = () => {
        navigator.clipboard.writeText(webhookUrl);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'EXECUTED':
                return <CheckCircle2 size={14} className="text-accent-success" />;
            case 'REJECTED':
            case 'EXPIRED':
                return <XCircle size={14} className="text-accent-danger" />;
            case 'PENDING':
            case 'VALIDATED':
                return <Clock size={14} className="text-accent-warning" />;
            default:
                return <Radio size={14} className="text-text-tertiary" />;
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'EXECUTED': return 'text-accent-success';
            case 'REJECTED':
            case 'EXPIRED': return 'text-accent-danger';
            case 'PENDING':
            case 'VALIDATED': return 'text-accent-warning';
            default: return 'text-text-tertiary';
        }
    };

    return (
        <div className="h-full flex flex-col gap-4 p-4 pt-20 max-w-[1400px] mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center border border-white/10">
                        <Zap size={20} className="text-purple-400" />
                    </div>
                    <div>
                        <h1 className="text-xl font-bold text-white">Trading Signals</h1>
                        <p className="text-xs text-text-tertiary">Webhook integration & signal management</p>
                    </div>
                </div>
                <button
                    onClick={fetchSignals}
                    className="p-2 bg-background-elevated border border-white/10 rounded-lg hover:bg-white/5 transition-colors"
                >
                    <RefreshCw size={16} className="text-text-secondary" />
                </button>
            </div>

            <div className="grid grid-cols-12 gap-4 flex-1 min-h-0">
                {/* Left: Config & Webhook */}
                <div className="col-span-4 flex flex-col gap-4">
                    {/* Webhook URL Card */}
                    <Card className="p-4">
                        <div className="flex items-center gap-2 mb-3">
                            <Radio size={16} className="text-accent-primary" />
                            <span className="text-sm font-bold text-white">Webhook URL</span>
                        </div>
                        <p className="text-xs text-text-tertiary mb-3">
                            Use this URL in TradingView or any external alert system
                        </p>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={webhookUrl}
                                readOnly
                                className="flex-1 bg-background-secondary border border-white/10 rounded-lg px-3 py-2 text-xs font-mono text-text-secondary"
                            />
                            <button
                                onClick={copyWebhookUrl}
                                className={cn(
                                    "px-3 py-2 rounded-lg border transition-all",
                                    copied
                                        ? 'bg-accent-success/20 border-accent-success/30 text-accent-success'
                                        : 'bg-background-elevated border-white/10 text-text-secondary hover:text-white'
                                )}
                            >
                                <Copy size={14} />
                            </button>
                        </div>
                        {copied && (
                            <p className="text-xs text-accent-success mt-2">Copied to clipboard!</p>
                        )}
                    </Card>

                    {/* Configuration */}
                    <Card className="p-4 flex-1">
                        <div className="flex items-center gap-2 mb-4">
                            <Settings2 size={16} className="text-accent-primary" />
                            <span className="text-sm font-bold text-white">Configuration</span>
                        </div>

                        <div className="space-y-4">
                            {/* Auto-Execute Toggle */}
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-sm text-white">Auto-Execute</p>
                                    <p className="text-xs text-text-tertiary">Execute signals automatically</p>
                                </div>
                                <button
                                    onClick={() => updateConfig({ autoExecute: !config.autoExecute })}
                                    className={cn(
                                        "w-12 h-6 rounded-full p-1 transition-colors",
                                        config.autoExecute ? 'bg-accent-success' : 'bg-background-secondary'
                                    )}
                                >
                                    <div
                                        className={cn(
                                            "w-4 h-4 rounded-full bg-white transition-transform",
                                            config.autoExecute ? 'translate-x-6' : 'translate-x-0'
                                        )}
                                    />
                                </button>
                            </div>

                            {/* Default Size */}
                            <div>
                                <label className="text-xs text-text-tertiary block mb-1">Default Size</label>
                                <input
                                    type="number"
                                    step="0.001"
                                    value={config.defaultSize}
                                    onChange={(e) => updateConfig({ defaultSize: parseFloat(e.target.value) || 0.01 })}
                                    className="w-full bg-background-secondary border border-white/10 rounded-lg px-3 py-2 text-sm"
                                />
                            </div>

                            {/* Rate Limit */}
                            <div>
                                <label className="text-xs text-text-tertiary block mb-1">Max Signals/Min</label>
                                <input
                                    type="number"
                                    value={config.maxSignalsPerMinute}
                                    onChange={(e) => updateConfig({ maxSignalsPerMinute: parseInt(e.target.value) || 10 })}
                                    className="w-full bg-background-secondary border border-white/10 rounded-lg px-3 py-2 text-sm"
                                />
                            </div>
                        </div>

                        {/* Webhook Format Example */}
                        <div className="mt-6 pt-4 border-t border-white/5">
                            <p className="text-xs text-text-tertiary mb-2">TradingView Alert Message Format:</p>
                            <pre className="bg-background-secondary p-3 rounded-lg text-[10px] font-mono text-text-secondary overflow-x-auto">
                                {`{
  "ticker": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "qty": {{strategy.order.contracts}},
  "price": {{close}},
  "passphrase": "your_secret"
}`}
                            </pre>
                        </div>
                    </Card>
                </div>

                {/* Right: Signal History */}
                <div className="col-span-8">
                    <Card className="h-full flex flex-col" noPadding>
                        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
                            <span className="text-sm font-bold text-white">Signal History</span>
                            <span className="text-xs text-text-tertiary">{signals.length} signals</span>
                        </div>

                        <div className="flex-1 overflow-y-auto custom-scrollbar">
                            {signals.length === 0 ? (
                                <div className="flex flex-col items-center justify-center h-full text-text-tertiary">
                                    <Radio size={32} className="mb-2 opacity-50" />
                                    <p className="text-sm">No signals received yet</p>
                                    <p className="text-xs mt-1">Configure a webhook to start receiving alerts</p>
                                </div>
                            ) : (
                                <div className="divide-y divide-white/5">
                                    {signals.map((signal) => (
                                        <div
                                            key={signal.id}
                                            className="px-4 py-3 hover:bg-white/5 transition-colors group"
                                        >
                                            <div className="flex items-center justify-between mb-2">
                                                <div className="flex items-center gap-3">
                                                    {getStatusIcon(signal.status)}
                                                    <span className="font-bold text-white">{signal.symbol}</span>
                                                    <span className={cn(
                                                        "text-xs px-2 py-0.5 rounded",
                                                        signal.side === 'BUY'
                                                            ? 'bg-accent-success/20 text-accent-success'
                                                            : 'bg-accent-danger/20 text-accent-danger'
                                                    )}>
                                                        {signal.side}
                                                    </span>
                                                    <span className="text-xs text-text-tertiary bg-background-secondary px-2 py-0.5 rounded">
                                                        {signal.orderType}
                                                    </span>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-xs ${getStatusColor(signal.status)}`}>
                                                        {signal.status}
                                                    </span>
                                                    {(signal.status === 'PENDING' || signal.status === 'VALIDATED') && (
                                                        <button
                                                            onClick={() => executeSignal(signal.id)}
                                                            disabled={isLoading}
                                                            className="opacity-0 group-hover:opacity-100 px-2 py-1 bg-accent-primary text-white text-xs rounded transition-all hover:bg-accent-primary/80"
                                                        >
                                                            <Play size={12} className="inline mr-1" />
                                                            Execute
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-4 text-xs text-text-tertiary">
                                                <span>Size: {signal.size}</span>
                                                {signal.price && <span>Price: {signal.price}</span>}
                                                <span>Source: {signal.source}</span>
                                                <span>{new Date(signal.timestamp).toLocaleTimeString()}</span>
                                            </div>
                                            {signal.error && (
                                                <p className="text-xs text-accent-danger mt-1">{signal.error}</p>
                                            )}
                                            {signal.orderId && (
                                                <p className="text-xs text-accent-success mt-1">Order: {signal.orderId}</p>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
};
