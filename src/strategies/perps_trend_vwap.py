"""
Perps trend-following + VWAP strategy signals
"""
from typing import Dict
import pandas as pd
from src.ta_indicators.ta_core import sma, rsi_ema, vwap

def compute_signals(df: pd.DataFrame) -> Dict[str, float | bool]:
    if len(df) < 35:
        return {
            "long_signal": False,
            "price": float("nan"),
            "fast": float("nan"),
            "slow": float("nan"),
            "vwap": float("nan"),
            "rsi": float("nan"),
        }
    closes = df["close"].astype(float)
    fast = sma(closes, 10)
    slow = sma(closes, 30)
    vwap_series = vwap(df)
    rsi_series = rsi_ema(closes, 14)
    current = df.iloc[-1]
    prev_idx = df.index[-2]
    long_signal = (
        fast.iloc[-2] < slow.iloc[-2]
        and fast.iloc[-1] > slow.iloc[-1]
        and current["close"] > vwap_series.iloc[-1]
        and 30 < rsi_series.iloc[-1] < 65
    )
    return {
        "long_signal": bool(long_signal),
        "price": float(current["close"]),
        "fast": float(fast.iloc[-1]),
        "slow": float(slow.iloc[-1]),
        "vwap": float(vwap_series.iloc[-1]),
        "rsi": float(rsi_series.iloc[-1]),
        "prev_fast": float(fast.loc[prev_idx]),
        "prev_slow": float(slow.loc[prev_idx]),
    }
