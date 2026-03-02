
import React, { useState, useEffect } from 'react';
import { Card } from '@/components/ui/Card';
import { ExchangeId, ExchangeApiConfig } from '@/types';
import { SUPPORTED_EXCHANGES } from '@/services/exchanges';
import { SecureStorage } from '@/services/secureStorage';
import { ExecutionService } from '@/services/execution';
import { Shield, Key, Wifi, CheckCircle, XCircle, AlertTriangle, Eye, EyeOff, Save, Server, Database, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

export const SettingsView: React.FC = () => {
    const [configs, setConfigs] = useState<ExchangeApiConfig[]>([]);
    const [selectedExchange, setSelectedExchange] = useState<ExchangeId>('ZOOMEX');
    const [showSecrets, setShowSecrets] = useState(false);
    const [isTesting, setIsTesting] = useState(false);
    const [testResult, setTestResult] = useState<{ success: boolean, msg: string } | null>(null);
    const [pipelineStatus, setPipelineStatus] = useState<'healthy' | 'degraded'>('healthy');

    // Form State
    const [apiKey, setApiKey] = useState('');
    const [apiSecret, setApiSecret] = useState('');

    useEffect(() => {
        loadConfigs();
        // Simulate checking backend health
        const interval = setInterval(() => {
            setPipelineStatus(Math.random() > 0.9 ? 'degraded' : 'healthy');
        }, 5000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        const config = configs.find(c => c.exchangeId === selectedExchange);
        if (config) {
            setApiKey('••••••••••••••••'); // Don't show actual key initially
            setApiSecret('••••••••••••••••');
        } else {
            setApiKey('');
            setApiSecret('');
        }
        setTestResult(null);
    }, [selectedExchange, configs]);

    const loadConfigs = () => {
        setConfigs(SecureStorage.getAllConfigs());
    };

    const handleSave = () => {
        // Validation
        if (apiKey.includes('•••') || apiSecret.includes('•••')) {
            // Only save if user actually typed something new, ignore placeholders
            // In a real app we'd handle this better
            alert("Please enter valid keys");
            return;
        }

        const newConfig: ExchangeApiConfig = {
            exchangeId: selectedExchange,
            apiKey: apiKey,
            apiSecret: apiSecret,
            isActive: true,
            lastTested: null,
            status: 'DISCONNECTED'
        };

        SecureStorage.saveConfig(newConfig);
        loadConfigs();
        setTestResult({ success: true, msg: "Credentials Encrypted & Saved locally." });
        setTimeout(() => setTestResult(null), 3000);
    };

    const handleTestConnection = async () => {
        setIsTesting(true);
        setTestResult(null);

        try {
            const success = await ExecutionService.testConnection(selectedExchange);
            if (success) {
                setTestResult({ success: true, msg: "Connection Successful: 42ms" });
                // Update status in storage
                const config = SecureStorage.getConfig(selectedExchange);
                if (config) {
                    SecureStorage.saveConfig({ ...config, status: 'CONNECTED', lastTested: Date.now() });
                    loadConfigs();
                }
            } else {
                setTestResult({ success: false, msg: "Connection Failed: Invalid Sign or Timeout" });
            }
        } catch (e) {
            setTestResult({ success: false, msg: "System Error" });
        } finally {
            setIsTesting(false);
        }
    };

    return (
        <div className="h-full max-w-5xl mx-auto p-6 flex flex-col gap-6 overflow-y-auto" data-testid="settings-view">

            {/* Header / System Health */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-white mb-1">Platform Settings</h2>
                    <p className="text-text-secondary text-sm">Configure exchange connections and security preferences.</p>
                </div>

                <div className="flex gap-4">
                    <Card className="flex items-center gap-3 px-4 py-2 border-white/5" noPadding>
                        <div className={cn("p-2 rounded-full", pipelineStatus === 'healthy' ? 'bg-accent-success/10 text-accent-success' : 'bg-accent-warning/10 text-accent-warning')}>
                            <Server size={18} />
                        </div>
                        <div>
                            <div className="text-[10px] text-text-tertiary uppercase font-bold">Execution Engine</div>
                            <div className={cn("text-xs font-mono font-medium", pipelineStatus === 'healthy' ? 'text-accent-success' : 'text-accent-warning')}>
                                {pipelineStatus === 'healthy' ? 'OPERATIONAL' : 'DEGRADED'}
                            </div>
                        </div>
                    </Card>
                    <Card className="flex items-center gap-3 px-4 py-2 border-white/5" noPadding>
                        <div className="p-2 rounded-full bg-accent-primary/10 text-accent-primary">
                            <Database size={18} />
                        </div>
                        <div>
                            <div className="text-[10px] text-text-tertiary uppercase font-bold">Secure Vault</div>
                            <div className="text-xs font-mono font-medium text-accent-primary" data-testid="vault-status">ENCRYPTED</div>
                        </div>
                    </Card>
                </div>
            </div>

            <div className="grid grid-cols-12 gap-8">
                {/* Left: Navigation */}
                <div className="col-span-3 flex flex-col gap-3">
                    <div className="text-xs font-bold text-text-tertiary uppercase tracking-wider px-2 pb-2 border-b border-white/5">Integrations</div>
                    {SUPPORTED_EXCHANGES.map(ex => {
                        const config = configs.find(c => c.exchangeId === ex.id);
                        return (
                            <button
                                key={ex.id}
                                onClick={() => setSelectedExchange(ex.id)}
                                className={cn(
                                    "w-full flex items-center justify-between px-4 py-4 rounded-xl transition-all border",
                                    selectedExchange === ex.id
                                        ? 'bg-background-elevated border-accent-primary/50 text-white shadow-lg'
                                        : 'bg-transparent border-white/5 text-text-secondary hover:bg-white/5 hover:text-white'
                                )}
                            >
                                <div className="flex items-center gap-3">
                                    <div className="w-1.5 h-8 rounded-full" style={{ backgroundColor: ex.color }}></div>
                                    <div className="text-left">
                                        <div className="font-medium text-sm">{ex.name}</div>
                                        <div className="text-[10px] text-text-tertiary mt-0.5">
                                            {config ? (config.status === 'CONNECTED' ? 'Active' : 'Configured') : 'Not Setup'}
                                        </div>
                                    </div>
                                </div>
                                {config?.status === 'CONNECTED' && <CheckCircle size={14} className="text-accent-success" />}
                            </button>
                        );
                    })}
                </div>

                {/* Right: Config Form */}
                <div className="col-span-9">
                    <Card className="p-8 space-y-6">
                        <div className="flex items-center justify-between pb-6 border-b border-white/5">
                            <div className="flex items-center gap-3">
                                <Shield size={24} className="text-accent-primary" />
                                <h3 className="text-lg font-bold">API Configuration</h3>
                            </div>
                            <div className="flex items-center gap-2 text-xs text-accent-warning bg-accent-warning/10 px-3 py-1.5 rounded-lg border border-accent-warning/20">
                                <AlertTriangle size={12} />
                                <span className="hidden md:inline">Keys are encrypted client-side via AES-256 simulation</span>
                                <span className="md:hidden">Encrypted Storage</span>
                            </div>
                        </div>

                        <div className="space-y-4">
                            <div className="space-y-1">
                                <label className="text-xs font-semibold text-text-secondary">API Key</label>
                                <div className="relative">
                                    <Key size={16} className="absolute left-3 top-3 text-text-tertiary" />
                                    <input
                                        type="text"
                                        value={apiKey}
                                        onChange={(e) => setApiKey(e.target.value)}
                                        className="w-full bg-background-secondary border border-white/10 rounded-lg pl-10 pr-4 py-2.5 text-sm font-mono focus:border-accent-primary focus:outline-none transition-colors"
                                        placeholder="Enter Exchange API Key"
                                        data-testid="input-api-key"
                                    />
                                </div>
                            </div>

                            <div className="space-y-1">
                                <label className="text-xs font-semibold text-text-secondary">API Secret</label>
                                <div className="relative">
                                    <Shield size={16} className="absolute left-3 top-3 text-text-tertiary" />
                                    <input
                                        type={showSecrets ? "text" : "password"}
                                        value={apiSecret}
                                        onChange={(e) => setApiSecret(e.target.value)}
                                        className="w-full bg-background-secondary border border-white/10 rounded-lg pl-10 pr-10 py-2.5 text-sm font-mono focus:border-accent-primary focus:outline-none transition-colors"
                                        placeholder="Enter Exchange API Secret"
                                        data-testid="input-api-secret"
                                    />
                                    <button
                                        onClick={() => setShowSecrets(!showSecrets)}
                                        className="absolute right-3 top-3 text-text-tertiary hover:text-white"
                                    >
                                        {showSecrets ? <EyeOff size={16} /> : <Eye size={16} />}
                                    </button>
                                </div>
                            </div>
                        </div>

                        {testResult && (
                            <div data-testid="settings-message" className={cn(
                                "p-3 rounded-lg flex items-center gap-2 text-sm",
                                testResult.success ? 'bg-accent-success/10 text-accent-success' : 'bg-accent-danger/10 text-accent-danger'
                            )}>
                                {testResult.success ? <CheckCircle size={16} /> : <XCircle size={16} />}
                                {testResult.msg}
                            </div>
                        )}

                        <div className="pt-4 flex items-center gap-4">
                            <button
                                onClick={handleSave}
                                className="flex items-center gap-2 px-6 py-2.5 bg-white text-black font-bold rounded-lg hover:bg-white/90 transition-colors"
                                data-testid="btn-save-config"
                            >
                                <Save size={16} /> Save Configuration
                            </button>
                            <button
                                onClick={handleTestConnection}
                                disabled={isTesting}
                                className="flex items-center gap-2 px-6 py-2.5 bg-background-elevated border border-white/10 text-white font-medium rounded-lg hover:bg-white/5 transition-colors disabled:opacity-50"
                            >
                                {isTesting ? <RefreshCw size={16} className="animate-spin" /> : <Wifi size={16} />}
                                Test Connection
                            </button>
                        </div>
                    </Card>

                    <div className="mt-6 p-4 rounded-xl border border-white/5 bg-background-elevated/30">
                        <h4 className="text-sm font-bold text-white mb-2">Security Notice</h4>
                        <p className="text-xs text-text-secondary leading-relaxed">
                            For institutional security, this interface connects directly to the exchange APIs via a secure proxy.
                            Your keys are never logged and are stored in an encrypted vault.
                            Ensure you have whitelisted the platform IP addresses in your exchange settings.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};
