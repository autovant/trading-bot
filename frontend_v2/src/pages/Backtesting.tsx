import { GlassCard } from '../components/ui/GlassCard';
import { Box, Play, FileText } from 'lucide-react';
import useSWR from 'swr';

const fetcher = (url: string) => fetch(url).then(res => res.json());

export const Backtesting = () => {
    const { data: backtests } = useSWR('http://localhost:8080/api/backtests', fetcher, { refreshInterval: 10000 });

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-4 border-b border-white/5">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
                        <Box className="text-purple-400" />
                        Backtesting Engine
                    </h2>
                    <p className="text-slate-400 mt-1">Run historical sims and view progress</p>
                </div>
                <button className="neon-button px-6 py-2.5 flex items-center gap-2">
                    <Play size={18} /> New Backtest
                </button>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <GlassCard>
                    <h3 className="text-lg font-bold text-white mb-4">Recent Runs</h3>
                    {(!backtests || backtests.length === 0) ? (
                        <div className="p-12 text-center text-slate-500 border border-dashed border-white/10 rounded-xl bg-white/5">
                            <FileText size={48} className="mx-auto mb-4 opacity-50" />
                            <p>No backtest history found.</p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {backtests.map((run: any, i: number) => (
                                <div key={i} className="p-4 border border-white/10 rounded-xl bg-white/5 flex justify-between items-center hover:bg-white/10 transition-colors cursor-pointer">
                                    <div>
                                        <p className="font-semibold text-white">{run.run_id || 'Unknown Run'}</p>
                                        <p className="text-sm text-slate-400">{run.date_range || 'All Time'}</p>
                                    </div>
                                    <div className="text-right">
                                        <p className={`font-bold ${parseFloat(run.net_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            ${parseFloat(run.net_pnl || 0).toFixed(2)}
                                        </p>
                                        <span className="text-xs text-slate-500 uppercase">Net PnL</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </GlassCard>
            </div>
        </div>
    );
};
