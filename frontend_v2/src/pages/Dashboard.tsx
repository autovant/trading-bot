import { useMemo } from 'react';
import { GlassCard } from '../components/ui/GlassCard';
import { useDailyPnL, useTrades, usePositions } from '../hooks/useApi';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    BarChart, Bar, Cell
} from 'recharts';
import { Activity, TrendingUp, DollarSign, Percent } from 'lucide-react';

export const Dashboard = () => {
    const { pnl, loading: pnlLoading } = useDailyPnL();
    const { trades } = useTrades();
    const { positions } = usePositions();

    const metrics = useMemo(() => {
        let totalPnl = 0;
        let winCount = 0;

        if (trades && trades.length > 0) {
            trades.forEach((t: any) => {
                const rPnl = parseFloat(t.realized_pnl) || 0;
                totalPnl += rPnl;
                if (rPnl > 0) winCount++;
            });
        }

        const winRate = trades?.length > 0 ? (winCount / trades.length) * 100 : 0;
        const activeExposures = positions?.length || 0;

        return {
            netRealized: totalPnl,
            winRate,
            activeExposures,
            totalTrades: trades?.length || 0
        };
    }, [trades, positions]);

    const pnlChartData = useMemo(() => {
        if (!pnl || pnl.length === 0) return [];
        return pnl.map((d: any) => ({
            date: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
            balance: d.balance,
            net: parseFloat(d.net_pnl || 0),
        })).reverse();
    }, [pnl]);

    return (
        <div className="space-y-6 animate-in fade-in duration-500">

            {/* Header */}
            <div className="flex justify-between items-end pb-4 border-b border-white/5">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
                        <Activity className="text-cyan-400" />
                        Command Center
                    </h2>
                    <p className="text-slate-400 mt-1">Real-time performance & open exposures</p>
                </div>
                <div className="flex gap-3">
                    <button className="neon-button px-6 py-2.5">
                        Emergency Halt
                    </button>
                </div>
            </div>

            {/* Top Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <GlassCard hoverEffect className="relative overflow-hidden group">
                    <div className="absolute -right-4 -top-4 w-24 h-24 bg-blue-600/20 rounded-full blur-[20px] group-hover:bg-blue-500/30 transition-all"></div>
                    <div className="flex items-start justify-between">
                        <div>
                            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">30D Net Realized</p>
                            <h3 className={`text-3xl font-bold mt-2 ${metrics.netRealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                ${metrics.netRealized.toFixed(2)}
                            </h3>
                        </div>
                        <div className="p-2 bg-white/5 rounded-lg border border-white/10">
                            <DollarSign size={20} className="text-emerald-400" />
                        </div>
                    </div>
                </GlassCard>

                <GlassCard hoverEffect>
                    <div className="flex items-start justify-between">
                        <div>
                            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Win Rate</p>
                            <h3 className="text-3xl font-bold text-white mt-2">
                                {metrics.winRate.toFixed(1)}%
                            </h3>
                        </div>
                        <div className="p-2 bg-white/5 rounded-lg border border-white/10">
                            <Percent size={20} className="text-cyan-400" />
                        </div>
                    </div>
                </GlassCard>

                <GlassCard hoverEffect>
                    <div className="flex items-start justify-between">
                        <div>
                            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Active Executions</p>
                            <h3 className="text-3xl font-bold text-white mt-2">
                                {metrics.totalTrades} <span className="text-lg font-normal text-slate-500">Fills</span>
                            </h3>
                        </div>
                        <div className="p-2 bg-white/5 rounded-lg border border-white/10">
                            <TrendingUp size={20} className="text-purple-400" />
                        </div>
                    </div>
                </GlassCard>

                <GlassCard hoverEffect>
                    <div className="flex items-start justify-between">
                        <div>
                            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Open Positions</p>
                            <h3 className="text-3xl font-bold text-white mt-2">
                                {metrics.activeExposures}
                            </h3>
                        </div>
                        <div className="p-2 bg-white/5 rounded-lg border border-white/10">
                            <Activity size={20} className="text-amber-400" />
                        </div>
                    </div>
                </GlassCard>
            </div>

            {/* Main Charts area */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <GlassCard className="lg:col-span-2 min-h-[400px]">
                    <h3 className="text-lg font-bold text-white mb-4">Equity Curve</h3>
                    {pnlLoading ? (
                        <div className="flex items-center justify-center h-full text-slate-500 animate-pulse">Loading data...</div>
                    ) : (
                        <div className="h-[320px] w-full mt-4">
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={pnlChartData}>
                                    <defs>
                                        <linearGradient id="colorBalance" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#1bdce2" stopOpacity={0.3} />
                                            <stop offset="95%" stopColor="#1bdce2" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                    <XAxis dataKey="date" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
                                    <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} domain={['auto', 'auto']} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0f1829', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff' }}
                                        itemStyle={{ color: '#1bdce2' }}
                                    />
                                    <Area type="monotone" dataKey="balance" stroke="#1bdce2" strokeWidth={3} fillOpacity={1} fill="url(#colorBalance)" />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </GlassCard>

                <GlassCard>
                    <h3 className="text-lg font-bold text-white mb-4">Daily Net PnL</h3>
                    {pnlLoading ? (
                        <div className="flex items-center justify-center h-full text-slate-500 animate-pulse">Loading data...</div>
                    ) : (
                        <div className="h-[320px] w-full mt-4">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={pnlChartData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                    <XAxis dataKey="date" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
                                    <Tooltip
                                        cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                                        contentStyle={{ backgroundColor: '#0f1829', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff' }}
                                    />
                                    <Bar dataKey="net" radius={[4, 4, 0, 0]}>
                                        {pnlChartData.map((entry: any, index: number) => (
                                            <Cell key={`cell-${index}`} fill={entry.net >= 0 ? '#32d48f' : '#f43f5e'} />
                                        ))}
                                    </Bar>
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </GlassCard>
            </div>

        </div>
    );
};
