"use client";

import React from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";

interface MainLayoutProps {
    children: React.ReactNode;
}

const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
    return (
        <div className="flex h-screen bg-background overflow-hidden font-sans text-foreground selection:bg-brand/30">
            <Sidebar />
            <div className="flex-1 flex flex-col min-w-0">
                <Header />
                <main className="flex-1 overflow-hidden relative">
                    {children}
                </main>
                <footer className="h-6 bg-card border-t border-card-border flex items-center justify-between px-4 text-[10px] text-gray-500 select-none">
                    <div className="flex items-center gap-4">
                        <span className="flex items-center gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                            System Operational
                        </span>
                        <span>v2.4.2 (Build 8920)</span>
                    </div>
                    <div className="flex items-center gap-4">
                        <span>Paper Trading Environment</span>
                        <span>24h Vol: $4.2B</span>
                    </div>
                </footer>
            </div>
        </div>
    );
};

export default MainLayout;
