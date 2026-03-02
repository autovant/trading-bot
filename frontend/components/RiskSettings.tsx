
import React, { useEffect, useState } from 'react';
import { backendApi } from '@/services/backend';
import { Card } from '@/components/ui/Card';
import { AlertTriangle, Shield, Activity, Power } from 'lucide-react';
import { cn } from '@/lib/utils';

export const RiskSettings: React.FC = () => {
    const [config, setConfig] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadConfig();
    }, []);

    const loadConfig = async () => {
        try {
            const data = await backendApi.getRiskConfig();
            setConfig(data);
        } catch (e) {
            console.error("Failed to load risk config", e);
            // Mock config for if backend fails (dev mode)
            setConfig({ killSwitch: false, maxNotional: 10000, dailyLossLimit: 500 });
        } finally {
            setLoading(false);
        }
    };

    const updateField = async (field: string, value: any) => {
        const newConfig = { ...config, [field]: value };
        setConfig(newConfig);
        try {
            await backendApi.updateRiskConfig(newConfig);
        } catch (e) {
            console.error("Failed to update risk config", e);
        }
    };

    if (loading || !config) return <div className="p-4 text-white">Loading Risk Engine...</div>;

    const killSwitchActive = config.killSwitch;

    return (
        <Card className={cn("max-w-md mx-auto p-6", killSwitchActive ? 'border-accent-danger' : 'border-white/10')}>
            <div className="flex items-center gap-3 mb-6 border-b border-white/10 pb-4">
                <Shield size={24} className={killSwitchActive ? 'text-accent-danger' : 'text-accent-success'} />
                <div>
                    <h2 className="text-xl font-bold text-white">Risk Controls</h2>
                    <p className="text-xs text-text-tertiary">Global Execution Parameters</p>
                </div>
            </div>

            <div className="space-y-6">

                {/* Kill Switch */}
                <div className={cn("p-4 rounded-xl border", killSwitchActive ? 'bg-accent-danger/10 border-accent-danger' : 'bg-background-secondary border-white/5')}>
                    <div className="flex justify-between items-center mb-2">
                        <div className="flex items-center gap-2">
                            <Power size={18} className={killSwitchActive ? 'text-accent-danger' : 'text-text-secondary'} />
                            <span className="font-bold text-white">Global Kill Switch</span>
                        </div>
                        <button
                            onClick={() => updateField('killSwitch', !killSwitchActive)}
                            className={cn(
                                "px-4 py-1.5 rounded-lg font-bold text-xs transition-all",
                                killSwitchActive
                                    ? 'bg-accent-danger text-white hover:bg-accent-danger/90'
                                    : 'bg-background-elevated text-text-secondary hover:text-white hover:bg-white/10'
                            )}
                        >
                            {killSwitchActive ? 'DEACTIVATE' : 'ACTIVATE'}
                        </button>
                    </div>
                    <p className="text-[10px] text-text-tertiary">
                        {killSwitchActive
                            ? "TRADING DISABLED. System will reject all new order placements."
                            : "System Operational. Trading allowed within limits."}
                    </p>
                </div>

                {/* Limits */}
                <div className="space-y-4">
                    <div>
                        <label className="text-xs text-text-secondary uppercase font-semibold mb-1.5 block">Max Notional Exposure ($)</label>
                        <input
                            type="number"
                            value={config.maxNotional}
                            onChange={(e) => updateField('maxNotional', parseFloat(e.target.value))}
                            className="w-full bg-background-primary border border-white/10 rounded-lg p-3 text-white focus:border-accent-primary focus:outline-none font-mono"
                        />
                    </div>

                    <div>
                        <label className="text-xs text-text-secondary uppercase font-semibold mb-1.5 block">Daily Loss Limit ($)</label>
                        <input
                            type="number"
                            value={config.dailyLossLimit}
                            onChange={(e) => updateField('dailyLossLimit', parseFloat(e.target.value))}
                            className="w-full bg-background-primary border border-white/10 rounded-lg p-3 text-white focus:border-accent-primary focus:outline-none font-mono"
                        />
                    </div>
                </div>

            </div>
        </Card>
    );
};
