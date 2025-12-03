"use client";

import React from "react";
import Header from "./Header";

interface AppShellProps {
    children: React.ReactNode;
    bottomPanel?: React.ReactNode;
    rightPanel?: React.ReactNode;
}

const AppShell: React.FC<AppShellProps> = ({ children, bottomPanel, rightPanel }) => {
    return (
        <div className="flex flex-col h-screen bg-background text-foreground overflow-hidden font-sans selection:bg-brand/30">
            <Header />

            <main className="flex-1 flex min-h-0">
                {/* Main Grid */}
                <div className="flex-1 flex flex-col min-w-0">
                    {/* Top Section (Chart + Right Panel) */}
                    <div className="flex-1 flex min-h-0">
                        {/* Chart Area */}
                        <div className="flex-1 relative border-r border-card-border">
                            {children}
                        </div>

                        {/* Right Panel (Health, Strategy, Manual) */}
                        {rightPanel && (
                            <div className="w-[320px] flex flex-col border-l border-card-border bg-card/50 backdrop-blur-sm">
                                {rightPanel}
                            </div>
                        )}
                    </div>

                    {/* Bottom Panel (Tabs) */}
                    {bottomPanel && (
                        <div className="h-[300px] border-t border-card-border bg-card">
                            {bottomPanel}
                        </div>
                    )}
                </div>
            </main>
        </div>
    );
};

export default AppShell;
