#!/usr/bin/env python3
"""Create demo agents with diverse strategies for paper trading validation."""

import json
import os
import sys
import urllib.request
import urllib.error

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")

# Try to load API_KEY from .env if not set
if not API_KEY:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("API_KEY="):
                    API_KEY = line.strip().split("=", 1)[1]
                    break

AGENTS = [
    {
        "name": "ETH Mean Reverter",
        "allocation_usd": 8000,
        "strategy_name": "bollinger-mean-reversion",
        "strategy_params": {"bb_period": 20, "bb_std": 2.0, "rsi_period": 14},
        "config": {
            "name": "ETH Mean Reverter",
            "description": "Bollinger Band mean reversion on ETH — buys oversold, sells overbought",
            "strategy_name": "bollinger-mean-reversion",
            "strategy_params": {"bb_period": 20, "bb_std": 2.0, "rsi_period": 14},
            "target": {"symbols": ["ETHUSDT"], "timeframes": ["1h", "4h"], "exchange": "okx"},
            "risk_guardrails": {
                "max_position_size_usd": 4000, "max_leverage": 2.0,
                "max_drawdown_pct": 0.10, "max_daily_loss_usd": 150, "max_open_positions": 2,
            },
            "backtest_requirements": {
                "min_sharpe": 0.8, "min_profit_factor": 1.1,
                "max_drawdown_pct": 0.18, "min_trades": 20, "min_win_rate": 0.40,
            },
            "paper_requirements": {"min_days": 7, "performance_tolerance_pct": 0.30, "min_trades": 5},
            "schedule": {"rebalance_interval_seconds": 300},
            "allocation_usd": 8000,
        },
    },
    {
        "name": "SOL Breakout Hunter",
        "allocation_usd": 5000,
        "strategy_name": "breakout-volume",
        "strategy_params": {"lookback": 20, "volume_mult": 1.5},
        "config": {
            "name": "SOL Breakout Hunter",
            "description": "Volume-confirmed breakout on SOL — catches momentum moves",
            "strategy_name": "breakout-volume",
            "strategy_params": {"lookback": 20, "volume_mult": 1.5},
            "target": {"symbols": ["SOLUSDT"], "timeframes": ["1h", "4h"], "exchange": "okx"},
            "risk_guardrails": {
                "max_position_size_usd": 2500, "max_leverage": 3.0,
                "max_drawdown_pct": 0.15, "max_daily_loss_usd": 100, "max_open_positions": 2,
            },
            "backtest_requirements": {
                "min_sharpe": 0.7, "min_profit_factor": 1.0,
                "max_drawdown_pct": 0.25, "min_trades": 15, "min_win_rate": 0.30,
            },
            "paper_requirements": {"min_days": 7, "performance_tolerance_pct": 0.35, "min_trades": 5},
            "schedule": {"rebalance_interval_seconds": 300},
            "allocation_usd": 5000,
        },
    },
    {
        "name": "Multi-Asset RSI Adaptive",
        "allocation_usd": 12000,
        "strategy_name": "adaptive-rsi",
        "strategy_params": {"rsi_period": 14, "overbought": 70, "oversold": 30},
        "config": {
            "name": "Multi-Asset RSI Adaptive",
            "description": "Adaptive RSI across BTC+ETH+SOL — regime-aware position sizing",
            "strategy_name": "adaptive-rsi",
            "strategy_params": {"rsi_period": 14, "overbought": 70, "oversold": 30},
            "target": {"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "timeframes": ["1h", "4h", "1d"], "exchange": "okx"},
            "risk_guardrails": {
                "max_position_size_usd": 4000, "max_leverage": 2.0,
                "max_drawdown_pct": 0.12, "max_daily_loss_usd": 250, "max_open_positions": 4,
                "max_correlation": 0.6,
            },
            "backtest_requirements": {
                "min_sharpe": 0.9, "min_profit_factor": 1.2,
                "max_drawdown_pct": 0.15, "min_trades": 25, "min_win_rate": 0.40,
            },
            "paper_requirements": {"min_days": 7, "performance_tolerance_pct": 0.25, "min_trades": 8},
            "schedule": {"rebalance_interval_seconds": 300},
            "allocation_usd": 12000,
        },
    },
]


def api_call(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  HTTP {e.code}: {error_body}")
        return json.loads(error_body) if error_body else {}


def main() -> None:
    print("=== Creating Demo Agents ===\n")

    created_ids: list[int] = []

    # Check for existing agents first
    existing = api_call("GET", "/api/agents")
    existing_names = {a["name"] for a in existing} if isinstance(existing, list) else set()
    existing_ids = {a["name"]: a["id"] for a in existing} if isinstance(existing, list) else {}

    for agent_def in AGENTS:
        name = agent_def["name"]
        if name in existing_names:
            print(f"  [SKIP] '{name}' already exists (id={existing_ids[name]})")
            created_ids.append(existing_ids[name])
            continue

        print(f"  Creating '{name}' ({agent_def['strategy_name']})...")
        result = api_call("POST", "/api/agents", agent_def)
        if "id" in result:
            print(f"  [OK] Created id={result['id']}")
            created_ids.append(result["id"])
        else:
            print(f"  [FAIL] {result}")

    # Also include any pre-existing agents
    for a in (existing if isinstance(existing, list) else []):
        if a["id"] not in created_ids:
            created_ids.append(a["id"])

    print(f"\n=== Starting Agents (→ backtesting) ===\n")

    for agent_id in created_ids:
        print(f"  Starting agent {agent_id}...")
        result = api_call("POST", f"/api/agents/{agent_id}/start")
        if "status" in result:
            print(f"  [OK] Agent {agent_id} → {result['status']}")
        else:
            print(f"  [INFO] {result.get('message', result)}")

    print(f"\n=== Final Agent Status ===\n")
    agents = api_call("GET", "/api/agents")
    if isinstance(agents, list):
        for a in agents:
            print(f"  [{a['id']}] {a['name']:30s} status={a['status']:12s} strategy={a.get('strategy_name', 'N/A')}")
    print("\nDone!")


if __name__ == "__main__":
    main()
