import { Activity, Settings, TrendingUp, Box } from 'lucide-react';
import { NavLink } from 'react-router-dom';

export const Sidebar = () => {
    return (
        <aside className="fixed left-0 top-0 bottom-0 w-64 glass-panel border-l-0 border-t-0 border-b-0 rounded-none z-10 flex flex-col">
            <div className="p-6 border-b border-white/10 flex items-center gap-3">
                <div className="w-8 h-8 rounded drop-shadow-[0_0_10px_rgba(41,98,255,0.8)] bg-blue-600 flex items-center justify-center">
                    <Activity size={18} className="text-white" />
                </div>
                <div>
                    <h1 className="text-xl font-bold text-glow-blue tracking-tight">TRADING<span className="text-cyan-400">BOT</span></h1>
                    <p className="text-[10px] uppercase text-cyan-500 tracking-widest font-semibold mt-0.5">Pro Max System</p>
                </div>
            </div>

            <nav className="flex-1 p-4 flex flex-col gap-2 relative">
                <NavItem to="/dashboard" icon={<TrendingUp size={18} />} label="Overview" />
                <NavItem to="/config" icon={<Settings size={18} />} label="Bot Configuration" />
                <NavItem to="/backtesting" icon={<Box size={18} />} label="Backtesting" />
            </nav>

            <div className="p-4 border-t border-white/10 m-4 mt-0 glass-panel border border-white/5 bg-opacity-20 flex flex-col gap-2 rounded-xl text-sm justify-end">
                <span className="text-xs text-slate-400 uppercase tracking-widest font-semibold">System Status</span>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_10px_rgba(50,212,143,0.8)] animate-pulse"></div>
                    <span className="font-medium text-slate-200">OPS API Online</span>
                </div>
                <p className="text-xs text-slate-500 font-mono mt-1">ws://localhost:8080</p>
            </div>
        </aside>
    );
};

const NavItem = ({ icon, label, to }: { icon: React.ReactNode, label: string, to: string }) => {
    return (
        <NavLink
            to={to}
            className={({ isActive }) => `w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm transition-all text-left ${isActive
                    ? 'bg-blue-600/20 text-cyan-400 font-medium border border-blue-500/30 shadow-[inset_0_0_20px_rgba(41,98,255,0.1)]'
                    : 'text-slate-400 hover:bg-white/5 hover:text-slate-200 bg-transparent border border-transparent'
                }`}
        >
            {({ isActive }) => (
                <>
                    <span className={isActive ? 'drop-shadow-[0_0_8px_rgba(27,220,226,0.5)]' : ''}>{icon}</span>
                    {label}
                </>
            )}
        </NavLink>
    );
};
