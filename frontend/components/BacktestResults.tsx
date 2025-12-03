"use client";

import React from "react";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";

type Trade = {
    symbol: string;
    direction: string;
    size: number;
    entry_price: number;
    exit_price: number;
    entry_time: string;
    exit_time: string;
    pnl: number;
    net_pnl: number;
    reason: string;
};

type EquityPoint = {
    timestamp: string;
    equity: number;
    drawdown: number;
};

type BacktestResultsProps = {
    results: {
        total_trades: number;
        winning_trades: number;
        losing_trades: number;
        win_rate: number;
        total_pnl: number;
        profit_factor: number;
        max_drawdown: number;
        sharpe_ratio: number;
        trades: Trade[];
        equity_curve: EquityPoint[];
    };
};

const BacktestResults: React.FC<BacktestResultsProps> = ({ results }) => {
    if (!results) return null;

    const formatCurrency = (val: number) =>
        new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);

    const formatPercent = (val: number) => `${val.toFixed(2)}%`;

    return (
        <div className="space-y-6 animate-fade-in">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
                    <div className="text-gray-400 text-sm">Total PnL</div>
                    <div className={`text-2xl font-mono font-bold ${results.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {formatCurrency(results.total_pnl)}
                    </div>
                </div>
                <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
                    <div className="text-gray-400 text-sm">Win Rate</div>
                    <div className="text-2xl font-mono font-bold text-yellow-400">
                        {formatPercent(results.win_rate)}
                    </div>
                    <div className="text-xs text-gray-500">
                        {results.winning_trades}W - {results.losing_trades}L
                    </div>
                </div>
                <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
                    <div className="text-gray-400 text-sm">Max Drawdown</div>
                    <div className="text-2xl font-mono font-bold text-red-400">
                        {formatPercent(results.max_drawdown)}
                    </div>
                </div>
                <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
                    <div className="text-gray-400 text-sm">Profit Factor</div>
                    <div className="text-2xl font-mono font-bold text-blue-400">
                        {results.profit_factor.toFixed(2)}
                    </div>
                </div>
            </div>

            <div className="bg-gray-800 p-4 rounded-lg border border-gray-700 h-96">
                <h3 className="text-lg font-semibold text-gray-200 mb-4">Equity Curve</h3>
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={results.equity_curve}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                        <XAxis
                            dataKey="timestamp"
                            stroke="#9CA3AF"
                            tickFormatter={(val: string) => new Date(val).toLocaleDateString()}
                        />
                        <YAxis stroke="#9CA3AF" />
                        <Tooltip
                            contentStyle={{ backgroundColor: "#1F2937", borderColor: "#374151" }}
                            labelFormatter={(label: string) => new Date(label).toLocaleString()}
                        />
                        <Line
                            type="monotone"
                            dataKey="equity"
                            stroke="#10B981"
                            strokeWidth={2}
                            dot={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
                <h3 className="text-lg font-semibold text-gray-200 mb-4">Recent Trades</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-gray-400">
                        <thead className="text-xs text-gray-500 uppercase bg-gray-900">
                            <tr>
                                <th className="px-4 py-2">Time</th>
                                <th className="px-4 py-2">Symbol</th>
                                <th className="px-4 py-2">Type</th>
                                <th className="px-4 py-2">Entry</th>
                                <th className="px-4 py-2">Exit</th>
                                <th className="px-4 py-2">PnL</th>
                                <th className="px-4 py-2">Reason</th>
                            </tr>
                        </thead>
                        <tbody>
                            {results.trades.slice(-10).reverse().map((trade, i) => (
                                <tr key={i} className="border-b border-gray-700 hover:bg-gray-700">
                                    <td className="px-4 py-2">{new Date(trade.entry_time).toLocaleString()}</td>
                                    <td className="px-4 py-2">{trade.symbol}</td>
                                    <td className={`px-4 py-2 font-bold ${trade.direction === "long" ? "text-green-400" : "text-red-400"}`}>
                                        {trade.direction.toUpperCase()}
                                    </td>
                                    <td className="px-4 py-2">${trade.entry_price.toFixed(2)}</td>
                                    <td className="px-4 py-2">${trade.exit_price.toFixed(2)}</td>
                                    <td className={`px-4 py-2 font-bold ${trade.net_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                                        {formatCurrency(trade.net_pnl)}
                                    </td>
                                    <td className="px-4 py-2">{trade.reason}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default BacktestResults;
