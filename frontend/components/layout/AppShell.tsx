"use client";

import React from "react";
import Header from "./Header";

interface AppShellProps {
    children: React.ReactNode;
    sidebar?: React.ReactNode;
    bottomPanel?: React.ReactNode;
}

/**
 * Full-screen dashboard layout with:
 * - Fixed header
 * - Main chart area (flexible)
 * - Right sidebar (fixed width w-80)
 * - Bottom panel for positions
 */
const AppShell: React.FC<AppShellProps> = ({ children, sidebar, bottomPanel }) => {
    return (
        <div className="h-screen w-screen overflow-hidden bg-background text-foreground font-sans grid grid-rows-[auto_1fr]">
            {/* Header - Fixed at top */}
            <Header />

            {/* Main Content Area - Grid with Sidebar */}
            <div className="grid grid-cols-[1fr_340px] overflow-hidden">

                {/* Left Column: Chart + Bottom Panel */}
                <div className="flex flex-col min-w-0 overflow-hidden relative">
                    {/* Main Chart Area */}
                    <main className="flex-1 min-h-0 relative p-3 pb-0">
                        {/* Chart Container */}
                        <div className="h-full w-full rounded-tl-xl rounded-tr-xl border border-card-border bg-card/50 backdrop-blur-sm overflow-hidden relative shadow-2xl">
                            {/* Glossy highlight for premium feel */}
                            <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-white/10 to-transparent z-10 opactiy-50"></div>
                            {children}
                        </div>
                    </main>

                    {/* Bottom Panel - Positions Table */}
                    {bottomPanel && (
                        <section className="h-72 shrink-0 border-t border-card-border bg-card/80 backdrop-blur-md overflow-hidden relative z-20 shadow-[0_-10px_40px_rgba(0,0,0,0.5)]">
                            {bottomPanel}
                        </section>
                    )}
                </div>

                {/* Right Sidebar - Fixed Width */}
                {sidebar && (
                    <aside className="border-l border-card-border bg-background/50 backdrop-blur-sm overflow-y-auto w-[340px] relative z-30 shadow-[-10px_0_30px_rgba(0,0,0,0.5)]">
                        <div className="absolute top-0 left-0 w-[1px] h-full bg-gradient-to-b from-transparent via-white/5 to-transparent z-40"></div>
                        <div className="flex flex-col gap-4 p-4">
                            {sidebar}
                        </div>
                    </aside>
                )}
            </div>
        </div>
    );
};

export default AppShell;
