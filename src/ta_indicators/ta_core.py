from typing import Any, cast

import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(window=n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average with non-adjusted weights."""
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi_ema(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    delta_any = cast(Any, delta)
    gain = delta_any.where(delta_any > 0, 0.0)
    loss = -delta_any.where(delta_any < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_volume = df["volume"].cumsum()
    return cumulative_tp_vol / cumulative_volume


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - prev_close).abs()
    low_close = (df["low"] - prev_close).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing via EMA."""
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
