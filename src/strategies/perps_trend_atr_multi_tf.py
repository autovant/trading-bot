"""
Multi-timeframe ATR trend strategy signals for perpetual futures.

This module only computes signals and price levels; order placement,
position sizing, and safety gates live elsewhere.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.config import PerpsConfig
from src.ta_indicators.ta_core import ema, atr, rsi_ema


def _default_response() -> Dict[str, Any]:
    nan = float("nan")
    return {
        "long_signal": False,
        "entry_price": nan,
        "stop_price": nan,
        "tp1_price": nan,
        "tp2_price": nan,
        "atr": nan,
        "atr_pct": nan,
        "htf_trend_up": False,
        "ema20": nan,
        "ema50": nan,
        "ema200_htf": nan,
        "rsi": nan,
        "volume_ok": True,
        "rsi_ok": True,
        "pullback_ok": False,
        "max_bars_in_trade": None,
    }


def compute_signals_multi_tf(
    ltf_df: pd.DataFrame,
    htf_df: pd.DataFrame,
    *,
    config: PerpsConfig,
) -> Dict[str, Any]:
    """
    Generate long-side signals using a 5m execution timeframe with a 1h trend filter.

    Returns a dict containing:
        long_signal: bool
        entry_price, stop_price, tp1_price, tp2_price: floats
        atr, atr_pct: floats
        htf_trend_up: bool
        ema20, ema50, ema200_htf: floats
        rsi, volume_ok, rsi_ok, pullback_ok: diagnostics
        max_bars_in_trade: configured bar cap for risk management
    """
    response = _default_response()
    if ltf_df.empty or htf_df.empty:
        return response

    ltf_required = max(config.atrPeriod + 5, 55)
    if len(ltf_df) < ltf_required or len(htf_df) < 200:
        return response

    ltf_closes = ltf_df["close"].astype(float)
    ltf_highs = ltf_df["high"].astype(float)
    ltf_lows = ltf_df["low"].astype(float)
    htf_closes = htf_df["close"].astype(float)

    ema20_series = ema(ltf_closes, 20)
    ema50_series = ema(ltf_closes, 50)
    atr_series = atr(ltf_df, period=config.atrPeriod)
    ema200_htf_series = ema(htf_closes, 200)

    ema20 = float(ema20_series.iloc[-1])
    ema50 = float(ema50_series.iloc[-1])
    ema200_htf = float(ema200_htf_series.iloc[-1])
    atr_value = float(atr_series.iloc[-1])
    close_price = float(ltf_closes.iloc[-1])
    prev_close = float(ltf_closes.iloc[-2])
    last_low = float(ltf_lows.iloc[-1])
    prev_ema20 = float(ema20_series.iloc[-2])
    prev_index = ltf_df.index[-2]

    atr_pct = atr_value / close_price if close_price > 0 else 0.0
    response.update(
        {
            "ema20": ema20,
            "ema50": ema50,
            "ema200_htf": ema200_htf,
            "atr": atr_value,
            "atr_pct": atr_pct,
            "max_bars_in_trade": config.maxBarsInTrade,
        }
    )

    if any(pd.isna(v) for v in (ema20, ema50, ema200_htf, atr_value)):
        return response

    htf_trend_up = htf_closes.iloc[-1] > ema200_htf
    ltf_trend_up = ema20 > ema50

    atr_ok = True
    if config.minAtrPct and atr_pct < config.minAtrPct:
        atr_ok = False
    if config.minAtrUsd is not None and atr_value < config.minAtrUsd:
        atr_ok = False

    pullback_body = prev_close > prev_ema20 and close_price <= ema20
    wick_near_ema = abs(last_low - ema20) <= config.wickAtrBuffer * atr_value
    pullback_ok = pullback_body or wick_near_ema

    rsi_ok = True
    rsi_value = float("nan")
    if config.useRsiFilter:
        rsi_series = rsi_ema(ltf_closes, n=config.rsiPeriod)
        rsi_value = float(rsi_series.iloc[-1])
        rsi_ok = config.rsiMin <= rsi_value <= config.rsiMax

    volume_ok = True
    if config.useVolumeFilter:
        vol_ma = ltf_df["volume"].rolling(config.volumeLookback).mean().iloc[-1]
        volume_ok = vol_ma > 0 and float(ltf_df["volume"].iloc[-1]) >= (
            vol_ma * config.volumeSpikeMultiplier
        )

    not_chasing = close_price <= ema20 + config.maxEmaDistanceAtr * atr_value

    long_signal = all(
        [
            htf_trend_up,
            ltf_trend_up,
            atr_ok,
            pullback_ok,
            rsi_ok,
            volume_ok,
            atr_value > 0,
            not_chasing,
        ]
    )

    stop_distance = max(config.atrStopMultiple * atr_value, close_price * config.hardStopMinPct)
    entry_price = close_price
    stop_price = max(0.0, entry_price - stop_distance)
    tp1_price = entry_price + stop_distance * config.tp1Multiple
    tp2_price = entry_price + stop_distance * config.tp2Multiple

    response.update(
        {
            "long_signal": bool(long_signal),
            "entry_price": entry_price,
            "stop_price": stop_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "htf_trend_up": bool(htf_trend_up),
            "rsi": rsi_value,
            "volume_ok": bool(volume_ok),
            "rsi_ok": bool(rsi_ok),
            "pullback_ok": bool(pullback_ok),
            "prev_index": prev_index,
        }
    )
    return response
