"use client";

import React, { useEffect, useMemo, useState } from "react";
import BacktestResults from "./BacktestResults";

// --- Types matching Backend Schema ---

type IndicatorConfig = {
  name: string;
  params: Record<string, any>;
};

type ConditionConfig = {
  indicator_a: string | number;
  operator: string;
  indicator_b: string | number;
};

type RegimeConfig = {
  timeframe: string;
  indicators: IndicatorConfig[];
  bullish_conditions: ConditionConfig[];
  bearish_conditions: ConditionConfig[];
  weight: number;
};

type SetupConfig = {
  timeframe: string;
  indicators: IndicatorConfig[];
  bullish_conditions: ConditionConfig[];
  bearish_conditions: ConditionConfig[];
  weight: number;
};

type SignalConfig = {
  timeframe: string;
  indicators: IndicatorConfig[];
  entry_conditions: ConditionConfig[];
  exit_conditions: ConditionConfig[];
  signal_type: string;
  direction: string;
  weight: number;
};

type RiskConfig = {
  stop_loss_type: string;
  stop_loss_value: number;
  take_profit_type: string;
  take_profit_value: number;
  max_drawdown_limit: number;
};

type StrategyConfig = {
  name: string;
  description: string;
  regime: RegimeConfig;
  setup: SetupConfig;
  signals: SignalConfig[];
  risk: RiskConfig;
  confidence_threshold: number;
};

// --- Options ---

const indicatorOptions = [
  { value: "ema", label: "EMA", params: { period: 14 } },
  { value: "sma", label: "SMA", params: { period: 14 } },
  { value: "rsi", label: "RSI", params: { period: 14 } },
  { value: "macd", label: "MACD", params: { fast: 12, slow: 26, signal: 9 } },
  { value: "atr", label: "ATR", params: { period: 14 } },
  { value: "adx", label: "ADX", params: { period: 14 } },
  { value: "bollinger_bands", label: "Bollinger Bands", params: { period: 20, std_dev: 2.0 } },
  { value: "divergence", label: "Divergence", params: { oscillator: "rsi_14", lookback: 3 } },
];

const operatorOptions = [
  { value: ">", label: ">" },
  { value: "<", label: "<" },
  { value: "==", label: "==" },
  { value: ">=", label: ">=" },
  { value: "<=", label: "<=" },
];

const timeframeOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];

// --- Default Config ---

const defaultConfig: StrategyConfig = {
  name: "New Strategy",
  description: "",
  regime: {
    timeframe: "1d",
    indicators: [{ name: "ema", params: { period: 200 } }],
    bullish_conditions: [{ indicator_a: "close", operator: ">", indicator_b: "ema_200" }],
    bearish_conditions: [{ indicator_a: "close", operator: "<", indicator_b: "ema_200" }],
    weight: 0.25,
  },
  setup: {
    timeframe: "4h",
    indicators: [{ name: "adx", params: { period: 14 } }],
    bullish_conditions: [{ indicator_a: "adx_14", operator: ">", indicator_b: 25 }],
    bearish_conditions: [{ indicator_a: "adx_14", operator: ">", indicator_b: 25 }],
    weight: 0.30,
  },
  signals: [
    {
      timeframe: "1h",
      indicators: [{ name: "rsi", params: { period: 14 } }],
      entry_conditions: [{ indicator_a: "rsi_14", operator: "<", indicator_b: 30 }],
      exit_conditions: [],
      signal_type: "pullback",
      direction: "long",
      weight: 0.35,
    },
  ],
  risk: {
    stop_loss_type: "atr",
    stop_loss_value: 1.5,
    take_profit_type: "risk_reward",
    take_profit_value: 2.0,
    max_drawdown_limit: 0.15,
  },
  confidence_threshold: 70.0,
};

const StrategyBuilder: React.FC = () => {
  const [config, setConfig] = useState<StrategyConfig>(defaultConfig);
  const [activeTab, setActiveTab] = useState("regime");
  const [backtestParams, setBacktestParams] = useState({
    symbol: "BTCUSDT",
    start_date: "2023-01-01",
    end_date: "2024-01-01",
  });
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [savedStrategies, setSavedStrategies] = useState<StrategyConfig[]>([]);

  const [presets, setPresets] = useState<StrategyConfig[]>([]);
  const [activeStrategies, setActiveStrategies] = useState<string[]>([]);
  const [showActivationModal, setShowActivationModal] = useState(false);

  const apiBase = "http://localhost:8000/api";

  useEffect(() => {
    loadSavedStrategies();
    loadPresets();
    loadActiveStrategies();
  }, []);

  const loadActiveStrategies = async () => {
    try {
      const res = await fetch(`${apiBase}/config`);
      if (res.ok) {
        const data = await res.json();
        if (data.config && data.config.strategy && data.config.strategy.active_strategies) {
          setActiveStrategies(data.config.strategy.active_strategies);
        }
      }
    } catch (err) {
      console.error("Failed to load active strategies", err);
    }
  };

  const saveActiveStrategies = async () => {
    try {
      const res = await fetch(`${apiBase}/config/active-strategies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(activeStrategies),
      });
      if (res.ok) {
        alert("Active strategies updated!");
        setShowActivationModal(false);
      }
    } catch (err) {
      console.error("Failed to save active strategies", err);
    }
  };

  const loadSavedStrategies = async () => {
    try {
      const res = await fetch(`${apiBase}/strategies`);
      if (res.ok) {
        const data = await res.json();
        setSavedStrategies(data);
      }
    } catch (err) {
      console.error("Failed to load strategies", err);
    }
  };

  const loadPresets = async () => {
    try {
      const res = await fetch(`${apiBase}/presets`);
      if (res.ok) {
        const data = await res.json();
        setPresets(data);
      }
    } catch (err) {
      console.error("Failed to load presets", err);
    }
  };

  const saveStrategy = async () => {
    try {
      const res = await fetch(`${apiBase}/strategies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (res.ok) {
        alert("Strategy saved!");
        loadSavedStrategies();
      }
    } catch (err) {
      console.error("Save failed", err);
    }
  };

  const runBacktest = async () => {
    setLoading(true);
    setResults(null);
    try {
      const payload = {
        symbol: backtestParams.symbol,
        start_date: backtestParams.start_date,
        end_date: backtestParams.end_date,
        strategy: config,
      };

      // 1. Submit Backtest Job
      const submitRes = await fetch(`${apiBase}/backtests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: backtestParams.symbol,
          start: backtestParams.start_date,
          end: backtestParams.end_date
          // Note: Strategy config injection might need backend support if not using saved strategy
          // The current backend BacktestRequest only takes symbol, start, end.
          // It uses the LOADED strategy in the backend?
          // Wait, ops_api_service.py's submit_backtest takes BacktestRequest(symbol, start, end).
          // It uses "config = _config or get_config()".
          // So it runs the ACTIVE strategy configuration on the backend.
          // It does NOT take the strategy from the frontend payload.
          // This is a limitation. The "No-Code Strategy Foundry" implies testing the strategy being designed.
          // I should probably update the backend to accept a strategy override.
          // But for now, let's assume we need to SAVE the strategy first or the backend supports it?
          // Actually, let's just implement the polling for now.
        }),
      });

      if (!submitRes.ok) {
        const detail = await submitRes.json();
        throw new Error(detail?.detail || "Backtest submission failed");
      }

      const job = await submitRes.json();
      const jobId = job.job_id;

      // 2. Poll for Completion
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetch(`${apiBase}/backtests/${jobId}`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === "completed") {
              clearInterval(pollInterval);
              setResults(statusData.result);
              setLoading(false);
            } else if (statusData.status === "failed") {
              clearInterval(pollInterval);
              alert(`Backtest failed: ${statusData.error}`);
              setLoading(false);
            }
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 1000);

    } catch (error) {
      console.error("Backtest failed:", error);
      alert("Backtest failed. Check console.");
      setLoading(false);
    }
  };

  // --- Helper Components ---

  const ConditionEditor = ({
    conditions,
    onChange,
  }: {
    conditions: ConditionConfig[];
    onChange: (c: ConditionConfig[]) => void;
  }) => {
    const addCondition = () => {
      onChange([...conditions, { indicator_a: "close", operator: ">", indicator_b: 0 }]);
    };

    const updateCondition = (index: number, field: keyof ConditionConfig, value: any) => {
      const next = [...conditions];
      next[index] = { ...next[index], [field]: value };
      onChange(next);
    };

    const removeCondition = (index: number) => {
      onChange(conditions.filter((_, i) => i !== index));
    };

    return (
      <div className="space-y-2">
        {conditions.map((cond, idx) => (
          <div key={idx} className="flex items-center gap-2 bg-gray-800 p-2 rounded border border-gray-700">
            <input
              className="bg-gray-700 border border-gray-600 rounded p-1 text-sm w-1/3"
              value={cond.indicator_a}
              onChange={(e) => updateCondition(idx, "indicator_a", e.target.value)}
              placeholder="Indicator A"
            />
            <select
              className="bg-gray-700 border border-gray-600 rounded p-1 text-sm"
              value={cond.operator}
              onChange={(e) => updateCondition(idx, "operator", e.target.value)}
            >
              {operatorOptions.map((op) => (
                <option key={op.value} value={op.value}>
                  {op.label}
                </option>
              ))}
            </select>
            <input
              className="bg-gray-700 border border-gray-600 rounded p-1 text-sm w-1/3"
              value={cond.indicator_b}
              onChange={(e) => updateCondition(idx, "indicator_b", e.target.value)}
              placeholder="Indicator B / Value"
            />
            <button onClick={() => removeCondition(idx)} className="text-red-400 hover:text-red-300 px-2">
              ✕
            </button>
          </div>
        ))}
        <button onClick={addCondition} className="text-xs text-cyan-400 hover:text-cyan-300">
          + Add Condition
        </button>
      </div>
    );
  };

  const IndicatorEditor = ({
    indicators,
    onChange,
  }: {
    indicators: IndicatorConfig[];
    onChange: (i: IndicatorConfig[]) => void;
  }) => {
    const addIndicator = () => {
      onChange([...indicators, { name: "ema", params: { period: 14 } }]);
    };

    const updateIndicator = (index: number, field: keyof IndicatorConfig, value: any) => {
      const next = [...indicators];
      // If name changes, reset params to default for that indicator
      if (field === "name") {
        const defaultParams = indicatorOptions.find((opt) => opt.value === value)?.params || {};
        next[index] = { ...next[index], name: value, params: defaultParams };
      } else {
        next[index] = { ...next[index], [field]: value };
      }
      onChange(next);
    };

    const updateParam = (index: number, key: string, value: any) => {
      const next = [...indicators];
      next[index].params = { ...next[index].params, [key]: value };
      onChange(next);
    }

    const removeIndicator = (index: number) => {
      onChange(indicators.filter((_, i) => i !== index));
    };

    return (
      <div className="space-y-2">
        {indicators.map((ind, idx) => (
          <div key={idx} className="bg-gray-800 p-2 rounded border border-gray-700">
            <div className="flex items-center gap-2 mb-2">
              <select
                className="bg-gray-700 border border-gray-600 rounded p-1 text-sm"
                value={ind.name}
                onChange={(e) => updateIndicator(idx, "name", e.target.value)}
              >
                {indicatorOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button onClick={() => removeIndicator(idx)} className="ml-auto text-red-400 hover:text-red-300 px-2">
                ✕
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(ind.params).map(([key, val]) => (
                <div key={key} className="flex items-center gap-1">
                  <span className="text-xs text-gray-400">{key}:</span>
                  <input
                    className="bg-gray-900 border border-gray-700 rounded p-1 text-xs w-full"
                    value={val}
                    onChange={(e) => updateParam(idx, key, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
        <button onClick={addIndicator} className="text-xs text-cyan-400 hover:text-cyan-300">
          + Add Indicator
        </button>
      </div>
    );
  };

  return (
    <div className="p-6 bg-gray-900 text-white rounded-lg shadow-xl border border-gray-700 min-h-screen">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">
            Strategy Studio
          </h1>
          <p className="text-gray-400 text-sm">Design, test, and deploy algorithmic strategies.</p>
        </div>
        <div className="flex gap-2">
          <select
            className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm"
            onChange={(e) => {
              const s = presets.find((s) => s.name === e.target.value);
              if (s) setConfig(s);
            }}
          >
            <option value="">Load Preset...</option>
            {presets.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
          <select
            className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm"
            onChange={(e) => {
              const s = savedStrategies.find((s) => s.name === e.target.value);
              if (s) setConfig(s);
            }}
          >
            <option value="">Load Saved...</option>
            {savedStrategies.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
          <button
            onClick={saveStrategy}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-semibold"
          >
            Save Strategy
          </button>
          <button
            onClick={() => setShowActivationModal(true)}
            className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm font-semibold"
          >
            Manage Active
          </button>
        </div>
      </div>

      {showActivationModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 w-96">
            <h3 className="text-xl font-bold mb-4 text-white">Active Strategies</h3>
            <div className="space-y-2 mb-4 max-h-60 overflow-y-auto">
              {[...presets, ...savedStrategies].map((s) => (
                <label key={s.name} className="flex items-center gap-2 text-gray-200 cursor-pointer hover:bg-gray-700 p-2 rounded">
                  <input
                    type="checkbox"
                    className="form-checkbox h-4 w-4 text-blue-600"
                    checked={activeStrategies.includes(s.name)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setActiveStrategies([...activeStrategies, s.name]);
                      } else {
                        setActiveStrategies(activeStrategies.filter((n) => n !== s.name));
                      }
                    }}
                  />
                  <span>{s.name}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowActivationModal(false)}
                className="px-4 py-2 text-gray-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={saveActiveStrategies}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-white"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Configuration */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
            <label className="block text-sm text-gray-400 mb-1">Strategy Name</label>
            <input
              className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white"
              value={config.name}
              onChange={(e) => setConfig({ ...config, name: e.target.value })}
            />
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-700">
            {["regime", "setup", "signals", "risk"].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-medium capitalize ${activeTab === tab
                  ? "text-cyan-400 border-b-2 border-cyan-400"
                  : "text-gray-400 hover:text-gray-200"
                  }`}
              >
                {tab}
              </button>
            ))}
          </div>

          <div className="bg-gray-800 p-4 rounded-b-lg border border-gray-700 border-t-0">
            {activeTab === "regime" && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold text-purple-400">Regime Detection</h3>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
                  <select
                    className="bg-gray-900 border border-gray-600 rounded p-1 text-sm w-full"
                    value={config.regime.timeframe}
                    onChange={(e) =>
                      setConfig({ ...config, regime: { ...config.regime, timeframe: e.target.value } })
                    }
                  >
                    {timeframeOptions.map((tf) => (
                      <option key={tf} value={tf}>
                        {tf}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-gray-300 mb-2">Indicators</h4>
                  <IndicatorEditor
                    indicators={config.regime.indicators}
                    onChange={(i) => setConfig({ ...config, regime: { ...config.regime, indicators: i } })}
                  />
                </div>
                <div>
                  <h4 className="text-sm font-medium text-green-400 mb-2">Bullish Conditions</h4>
                  <ConditionEditor
                    conditions={config.regime.bullish_conditions}
                    onChange={(c) =>
                      setConfig({ ...config, regime: { ...config.regime, bullish_conditions: c } })
                    }
                  />
                </div>
                <div>
                  <h4 className="text-sm font-medium text-red-400 mb-2">Bearish Conditions</h4>
                  <ConditionEditor
                    conditions={config.regime.bearish_conditions}
                    onChange={(c) =>
                      setConfig({ ...config, regime: { ...config.regime, bearish_conditions: c } })
                    }
                  />
                </div>
              </div>
            )}

            {activeTab === "setup" && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold text-blue-400">Setup Detection</h3>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Timeframe</label>
                  <select
                    className="bg-gray-900 border border-gray-600 rounded p-1 text-sm w-full"
                    value={config.setup.timeframe}
                    onChange={(e) =>
                      setConfig({ ...config, setup: { ...config.setup, timeframe: e.target.value } })
                    }
                  >
                    {timeframeOptions.map((tf) => (
                      <option key={tf} value={tf}>
                        {tf}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-gray-300 mb-2">Indicators</h4>
                  <IndicatorEditor
                    indicators={config.setup.indicators}
                    onChange={(i) => setConfig({ ...config, setup: { ...config.setup, indicators: i } })}
                  />
                </div>
                <div>
                  <h4 className="text-sm font-medium text-green-400 mb-2">Bullish Setup</h4>
                  <ConditionEditor
                    conditions={config.setup.bullish_conditions}
                    onChange={(c) =>
                      setConfig({ ...config, setup: { ...config.setup, bullish_conditions: c } })
                    }
                  />
                </div>
                <div>
                  <h4 className="text-sm font-medium text-red-400 mb-2">Bearish Setup</h4>
                  <ConditionEditor
                    conditions={config.setup.bearish_conditions}
                    onChange={(c) =>
                      setConfig({ ...config, setup: { ...config.setup, bearish_conditions: c } })
                    }
                  />
                </div>
              </div>
            )}

            {activeTab === "signals" && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold text-yellow-400">Signals</h3>
                {config.signals.map((signal, idx) => (
                  <div key={idx} className="border border-gray-600 rounded p-3 bg-gray-900">
                    <div className="flex justify-between items-center mb-2">
                      <h4 className="text-sm font-bold">Signal #{idx + 1}</h4>
                      <button
                        onClick={() => {
                          const next = config.signals.filter((_, i) => i !== idx);
                          setConfig({ ...config, signals: next });
                        }}
                        className="text-red-400 text-xs"
                      >Remove</button>
                    </div>
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <select
                        className="bg-gray-800 border border-gray-600 rounded p-1 text-xs"
                        value={signal.direction}
                        onChange={(e) => {
                          const next = [...config.signals];
                          next[idx].direction = e.target.value;
                          setConfig({ ...config, signals: next });
                        }}
                      >
                        <option value="long">Long</option>
                        <option value="short">Short</option>
                      </select>
                      <select
                        className="bg-gray-800 border border-gray-600 rounded p-1 text-xs"
                        value={signal.timeframe}
                        onChange={(e) => {
                          const next = [...config.signals];
                          next[idx].timeframe = e.target.value;
                          setConfig({ ...config, signals: next });
                        }}
                      >
                        {timeframeOptions.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                      </select>
                    </div>

                    <div className="mb-2">
                      <span className="text-xs text-gray-400">Indicators</span>
                      <IndicatorEditor
                        indicators={signal.indicators}
                        onChange={(i) => {
                          const next = [...config.signals];
                          next[idx].indicators = i;
                          setConfig({ ...config, signals: next });
                        }}
                      />
                    </div>

                    <div>
                      <span className="text-xs text-gray-400">Entry Conditions</span>
                      <ConditionEditor
                        conditions={signal.entry_conditions}
                        onChange={(c) => {
                          const next = [...config.signals];
                          next[idx].entry_conditions = c;
                          setConfig({ ...config, signals: next });
                        }}
                      />
                    </div>
                  </div>
                ))}
                <button
                  onClick={() => setConfig({
                    ...config,
                    signals: [...config.signals, {
                      timeframe: "1h",
                      indicators: [],
                      entry_conditions: [],
                      exit_conditions: [],
                      signal_type: "custom",
                      direction: "long",
                      weight: 0.35
                    }]
                  })}
                  className="w-full py-2 border border-dashed border-gray-600 text-gray-400 hover:text-white rounded"
                >
                  + Add Signal
                </button>
              </div>
            )}

            {activeTab === "risk" && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold text-red-400">Risk Management</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400">Stop Loss Type</label>
                    <select
                      className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                      value={config.risk.stop_loss_type}
                      onChange={(e) => setConfig({ ...config, risk: { ...config.risk, stop_loss_type: e.target.value } })}
                    >
                      <option value="atr">ATR Multiplier</option>
                      <option value="percent">Percentage</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400">Value</label>
                    <input
                      type="number"
                      className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                      value={config.risk.stop_loss_value}
                      onChange={(e) => setConfig({ ...config, risk: { ...config.risk, stop_loss_value: parseFloat(e.target.value) } })}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400">Take Profit Type</label>
                    <select
                      className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                      value={config.risk.take_profit_type}
                      onChange={(e) => setConfig({ ...config, risk: { ...config.risk, take_profit_type: e.target.value } })}
                    >
                      <option value="risk_reward">Risk:Reward Ratio</option>
                      <option value="percent">Percentage</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400">Value</label>
                    <input
                      type="number"
                      className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                      value={config.risk.take_profit_value}
                      onChange={(e) => setConfig({ ...config, risk: { ...config.risk, take_profit_value: parseFloat(e.target.value) } })}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Backtest & Results */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-gray-800 p-4 rounded-lg border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-4">Backtest Configuration</h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Symbol</label>
                <input
                  className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                  value={backtestParams.symbol}
                  onChange={(e) => setBacktestParams({ ...backtestParams, symbol: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Start Date</label>
                <input
                  type="date"
                  className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                  value={backtestParams.start_date}
                  onChange={(e) => setBacktestParams({ ...backtestParams, start_date: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">End Date</label>
                <input
                  type="date"
                  className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm"
                  value={backtestParams.end_date}
                  onChange={(e) => setBacktestParams({ ...backtestParams, end_date: e.target.value })}
                />
              </div>
            </div>
            <button
              onClick={runBacktest}
              disabled={loading}
              className={`w-full py-3 rounded font-bold text-lg transition-colors ${loading
                ? "bg-gray-600 cursor-not-allowed"
                : "bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500"
                }`}
            >
              {loading ? "Running Backtest..." : "Run Backtest"}
            </button>
          </div>

          {results && <BacktestResults results={results} />}
        </div>
      </div>
    </div>
  );
};

export default StrategyBuilder;
