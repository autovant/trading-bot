"use client";

import React from 'react';
import { LayoutGrid, Layers, BarChart2, Settings, Bell, Search, Hexagon, Sparkles } from 'lucide-react';
import { TabType } from '@/types';

interface NavbarProps {
    activeTab: TabType;
    onTabChange: (tab: TabType) => void;
    onToggleAI: () => void;
    isAIActive: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, onTabChange, onToggleAI, isAIActive }) => {
    const navItems: { id: TabType; label: string; icon: React.ReactNode }[] = [
        { id: 'market', label: 'Markets', icon: <BarChart2 size={18} /> },
        { id: 'strategy', label: 'Strategy', icon: <Layers size={18} /> },
        { id: 'backtest', label: 'Backtest', icon: <LayoutGrid size={18} /> },
        { id: 'settings', label: 'Settings', icon: <Settings size={18} /> },
    ];

    return (
        <nav className="h-[60px] fixed top-0 w-full z-50 bg-background-primary/80 backdrop-blur-md border-b border-white/5 flex items-center justify-between px-6 overflow-x-auto">
            <div className="flex items-center gap-2">
                <div className="text-accent-primary">
                    <Hexagon size={24} fill="currentColor" className="opacity-90" />
                </div>
                <span className="font-medium text-lg tracking-tight text-text-primary ml-2">Cupertino Trade</span>
            </div>

            <div className="flex items-center bg-background-secondary/50 rounded-full p-1 border border-white/5">
                {navItems.map((item) => (
                    <button
                        key={item.id}
                        data-testid={`nav-${item.id}`}
                        onClick={() => onTabChange(item.id)}
                        className={`flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-300 ${activeTab === item.id
                            ? 'bg-background-elevated text-white shadow-sm'
                            : 'text-text-secondary hover:text-text-primary'
                            }`}
                    >
                        {item.icon}
                        {item.label}
                    </button>
                ))}
            </div>

            <div className="flex items-center gap-4 text-text-secondary">
                <button
                    onClick={onToggleAI}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all duration-300 ${isAIActive ? 'bg-accent-primary/10 border-accent-primary text-accent-primary' : 'bg-background-elevated/50 border-white/5 hover:border-white/10 text-text-secondary'}`}
                >
                    <Sparkles size={14} fill={isAIActive ? "currentColor" : "none"} />
                    <span className="text-xs font-medium">AI Assistant</span>
                </button>

                <div className="flex items-center gap-2 bg-background-elevated/50 px-3 py-1.5 rounded-lg border border-white/5 group transition-colors hover:border-white/10 cursor-pointer">
                    <Search size={14} />
                    <span className="text-xs font-mono group-hover:text-text-primary">⌘ K</span>
                </div>
                <button className="hover:text-text-primary transition-colors relative">
                    <Bell size={18} />
                    <span className="absolute top-0 right-0 w-2 h-2 bg-accent-danger rounded-full border border-black transform translate-x-1/3 -translate-y-1/3"></span>
                </button>
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-accent-primary to-purple-500 border border-white/10 ring-2 ring-black"></div>
            </div>
        </nav>
    );
};
