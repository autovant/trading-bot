
"use client";

import React from "react";

const Dashboard: React.FC = () => {
    return (
        <div className="p-6 bg-gray-900 text-white rounded-lg shadow-xl border border-gray-700 h-full">
            <h2 className="text-2xl font-bold mb-4 text-cyan-400">Live Dashboard</h2>
            <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-800 p-4 rounded border border-gray-700">
                    <h3 className="text-gray-400 text-sm">Equity</h3>
                    <p className="text-2xl font-mono">$10,000.00</p>
                </div>
                <div className="bg-gray-800 p-4 rounded border border-gray-700">
                    <h3 className="text-gray-400 text-sm">Open PnL</h3>
                    <p className="text-2xl font-mono text-green-400">+$0.00</p>
                </div>
            </div>
            <div className="mt-6 p-4 bg-gray-800 rounded border border-gray-700">
                <p className="text-gray-400 text-center">Chart Placeholder</p>
            </div>
        </div>
    );
};

export default Dashboard;
