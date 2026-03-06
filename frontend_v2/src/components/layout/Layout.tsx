import React from 'react';
import { Sidebar } from './Sidebar';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    return (
        <div className="min-h-screen flex bg-[#080f1d] overflow-hidden">
            <Sidebar />
            <main className="flex-1 ml-64 p-8 overflow-y-auto w-full h-screen relative">
                {/* Futuristic background ambiance / glow spots */}
                <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none"></div>
                <div className="absolute bottom-[-10%] right-[-10%] w-[30%] h-[50%] bg-cyan-400/10 rounded-full blur-[100px] pointer-events-none"></div>

                <div className="relative z-10 max-w-7xl mx-auto">
                    {children}
                </div>
            </main>
        </div>
    );
};
