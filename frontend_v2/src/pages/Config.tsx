import { GlassCard } from '../components/ui/GlassCard';
import { useMode } from '../hooks/useApi';
import { Settings, Shield, Server } from 'lucide-react';

export const Config = () => {
    const { mode, loading } = useMode();

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-4 border-b border-white/5">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
                        <Settings className="text-blue-400" />
                        Bot Configuration
                    </h2>
                    <p className="text-slate-400 mt-1">Manage modes, risk guardrails, and strategies</p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <GlassCard>
                    <div className="flex items-center gap-3 mb-4">
                        <Server className="text-cyan-400" />
                        <h3 className="text-xl font-bold text-white">Execution Mode</h3>
                    </div>
                    <div className="space-y-4">
                        <div className="p-4 border border-white/10 rounded-xl bg-white/5 flex justify-between items-center">
                            <div>
                                <p className="font-semibold text-white">Current Mode</p>
                                <p className="text-sm text-slate-400">{loading ? 'Loading...' : mode?.mode?.toUpperCase() || 'UNKNOWN'}</p>
                            </div>
                            <div className="flex gap-2">
                                <button className={`px-4 py-2 border rounded-lg transition-all ${mode?.mode === 'paper' ? 'border-cyan-500 text-cyan-400 bg-cyan-900/30 shadow-[0_0_10px_rgba(27,220,226,0.3)]' : 'border-white/10 text-slate-400 hover:text-white'}`}>Paper</button>
                                <button className={`px-4 py-2 border rounded-lg transition-all ${mode?.mode === 'live' ? 'border-red-500 text-red-400 bg-red-900/30' : 'border-white/10 text-slate-400 hover:text-white'}`}>Live</button>
                            </div>
                        </div>
                        <div className="p-4 border border-white/10 rounded-xl bg-white/5 flex justify-between items-center">
                            <div>
                                <p className="font-semibold text-white">Shadow Mode</p>
                                <p className="text-sm text-slate-400">Mirror fills in paper broker</p>
                            </div>
                            <button className={`w-12 h-6 rounded-full transition-colors ${mode?.shadow ? 'bg-cyan-500' : 'bg-slate-700'} relative`}>
                                <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${mode?.shadow ? 'right-1' : 'left-1'}`} />
                            </button>
                        </div>
                    </div>
                </GlassCard>

                <GlassCard>
                    <div className="flex items-center gap-3 mb-4">
                        <Shield className="text-amber-400" />
                        <h3 className="text-xl font-bold text-white">Risk Guardrails</h3>
                    </div>
                    <div className="space-y-4">
                        <div className="p-4 border border-white/10 rounded-xl bg-white/5">
                            <div className="flex justify-between items-center mb-2">
                                <p className="font-semibold text-white">Max Daily Loss (%)</p>
                                <span className="text-amber-400 font-bold">3.0%</span>
                            </div>
                            <input type="range" className="w-full accent-amber-500" min="0.5" max="10" step="0.5" defaultValue="3" />
                        </div>
                        <div className="p-4 border border-white/10 rounded-xl bg-white/5">
                            <div className="flex justify-between items-center mb-2">
                                <p className="font-semibold text-white">Daily Target (%)</p>
                                <span className="text-green-400 font-bold">1.0%</span>
                            </div>
                            <input type="range" className="w-full accent-green-500" min="0.1" max="5" step="0.1" defaultValue="1" />
                        </div>
                        <button className="neon-button w-full mt-2 py-3">Apply Guardrails</button>
                    </div>
                </GlassCard>
            </div>
        </div>
    );
};
