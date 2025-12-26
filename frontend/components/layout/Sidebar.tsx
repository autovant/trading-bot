"use client";

import React from "react";
import { LayoutDashboard, Settings, History, Bot, Zap } from "lucide-react";
import { cn } from "@/utils/cn";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface SidebarProps {
    className?: string;
}

const Sidebar: React.FC<SidebarProps> = ({ className }) => {
    const pathname = usePathname();

    const navItems = [
        { icon: LayoutDashboard, label: "Markets", href: "/", active: pathname === "/" },
        { icon: Bot, label: "Strategy", href: "/strategy-studio", active: pathname === "/strategy-studio" },
        { icon: History, label: "Backtest", href: "/strategy-studio", active: false }, // Backtest is inside Strategy Studio for now
        { icon: Settings, label: "Settings", href: "/settings", active: pathname === "/settings" },
    ];

    return (
        <div className={cn("w-16 flex flex-col items-center py-4 bg-card border-r border-card-border h-screen", className)}>
            <div className="mb-8 p-2 bg-brand/10 rounded-lg">
                <Zap className="w-6 h-6 text-brand" />
            </div>

            <nav className="flex-1 flex flex-col gap-6 w-full px-2">
                {navItems.map((item, index) => (
                    <Link
                        key={index}
                        href={item.href}
                        className={cn(
                            "p-3 rounded-xl transition-all duration-200 group relative flex justify-center",
                            item.active
                                ? "bg-brand text-white shadow-[0_0_15px_rgba(0,102,255,0.3)]"
                                : "text-gray-400 hover:text-white hover:bg-white/5"
                        )}
                        title={item.label}
                    >
                        <item.icon className="w-5 h-5" />
                        {item.active && (
                            <div className="absolute -right-1 top-1/2 -translate-y-1/2 w-1 h-8 bg-white rounded-l-full opacity-0" />
                        )}
                    </Link>
                ))}
            </nav>

            <div className="mt-auto flex flex-col gap-4">
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-brand to-accent-cyan flex items-center justify-center text-xs font-bold text-white cursor-pointer hover:opacity-90">
                    AI
                </div>
            </div>
        </div>
    );
};

export default Sidebar;
