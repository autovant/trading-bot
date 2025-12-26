import os
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE_URL = "http://127.0.0.1:8000/api"


def create_strategy():
    strategy_config = {
        "name": "QA_AlwaysLong",
        "description": "Always enters long for QA",
        "regime": {
            "timeframe": "1d",
            "indicators": [],
            "bullish_conditions": [],
            "bearish_conditions": [],
            "weight": 0.0,
        },
        "setup": {
            "timeframe": "4h",
            "indicators": [],
            "bullish_conditions": [],
            "bearish_conditions": [],
            "weight": 0.0,
        },
        "signals": [
            {
                "timeframe": "1h",
                "indicators": [],
                "entry_conditions": [
                    {"indicator_a": 1, "operator": "==", "indicator_b": 1}
                ],
                "signal_type": "always_long",
                "direction": "long",
                "weight": 1.0,
            }
        ],
        "risk": {
            "stop_loss_type": "percent",
            "stop_loss_value": 5.0,
            "take_profit_type": "percent",
            "take_profit_value": 10.0,
            "max_drawdown_limit": 1.0,
        },
        "confidence_threshold": 10.0,
    }

    print("Creating strategy...")
    try:
        # Check if exists first (and delete if so, to be clean)
        requests.delete(f"{BASE_URL}/strategies/QA_AlwaysLong")
    except requests.RequestException:
        pass

    resp = requests.post(
        f"{BASE_URL}/strategies",
        json={"name": "QA_AlwaysLong", "config": strategy_config},
    )
    if resp.status_code != 200:
        print(f"Failed to create strategy: {resp.text}")
        exit(1)
    print("Strategy created.")

    print("Activating strategy...")
    resp = requests.post(f"{BASE_URL}/strategies/QA_AlwaysLong/activate")
    if resp.status_code != 200:
        print(f"Failed to activate strategy: {resp.text}")
        exit(1)
    print("Strategy activated.")


def create_synthetic_data():
    print("Creating synthetic data (300 days)...")
    os.makedirs("data/history", exist_ok=True)

    days = 300
    hours = days * 24

    # 1H Data
    dates_1h = [datetime(2023, 1, 1) + timedelta(hours=i) for i in range(hours)]
    prices_1h = [
        10000 + i * 2 for i in range(hours)
    ]  # Slower growth to keep prices reasonable
    df_1h = pd.DataFrame(
        {
            "timestamp": dates_1h,
            "open": prices_1h,
            "high": [p + 10 for p in prices_1h],
            "low": [p - 10 for p in prices_1h],
            "close": [p + 5 for p in prices_1h],
            "volume": 1000.0,
        }
    )
    df_1h.to_csv("data/history/QA_1h.csv", index=False)
    print("Created data/history/QA_1h.csv")

    # 4H Data
    dates_4h = [
        datetime(2023, 1, 1) + timedelta(hours=i * 4) for i in range(hours // 4)
    ]
    prices_4h = [10000 + i * 8 for i in range(hours // 4)]
    df_4h = pd.DataFrame(
        {
            "timestamp": dates_4h,
            "open": prices_4h,
            "high": [p + 40 for p in prices_4h],
            "low": [p - 40 for p in prices_4h],
            "close": [p + 20 for p in prices_4h],
            "volume": 4000.0,
        }
    )
    df_4h.to_csv("data/history/QA_4h.csv", index=False)
    print("Created data/history/QA_4h.csv")

    # 1D Data
    dates_1d = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(days)]
    prices_1d = [10000 + i * 48 for i in range(days)]
    df_1d = pd.DataFrame(
        {
            "timestamp": dates_1d,
            "open": prices_1d,
            "high": [p + 240 for p in prices_1d],
            "low": [p - 240 for p in prices_1d],
            "close": [p + 120 for p in prices_1d],
            "volume": 24000.0,
        }
    )
    df_1d.to_csv("data/history/QA_1d.csv", index=False)
    print("Created data/history/QA_1d.csv")


if __name__ == "__main__":
    create_strategy()
    create_synthetic_data()
