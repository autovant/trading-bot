import pandas as pd
import numpy as np

from src.config import PerpsConfig
from src.strategies.perps_trend_atr_multi_tf import compute_signals_multi_tf
from src.ta_indicators.ta_core import ema


def _build_trending_df(periods: int, freq: str, start: float, slope: float) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=periods, freq=freq, tz="UTC")
    base = start + np.arange(periods) * slope
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base,
            "volume": np.full(periods, 1000.0),
        },
        index=idx,
    )
    return df


def test_long_signal_with_bullish_trend_and_pullback():
    ltf_df = _build_trending_df(260, "5min", start=100, slope=0.08)
    htf_df = _build_trending_df(240, "60min", start=90, slope=0.6)

    ema20 = ema(ltf_df["close"], 20)
    penultimate_close = ema20.iloc[-2] + 1.0
    ltf_df.iloc[-2, ltf_df.columns.get_loc("close")] = penultimate_close
    ltf_df.iloc[-2, ltf_df.columns.get_loc("high")] = penultimate_close + 0.5
    ltf_df.iloc[-2, ltf_df.columns.get_loc("low")] = penultimate_close - 0.5
    ema20 = ema(ltf_df["close"], 20)
    pullback_close = ema20.iloc[-1] - 0.2
    ltf_df.iloc[-1, ltf_df.columns.get_loc("close")] = pullback_close
    ltf_df.iloc[-1, ltf_df.columns.get_loc("high")] = pullback_close + 0.4
    ltf_df.iloc[-1, ltf_df.columns.get_loc("low")] = pullback_close - 0.4

    config = PerpsConfig(minAtrPct=0.001)
    signals = compute_signals_multi_tf(ltf_df, htf_df, config=config)

    assert signals["long_signal"] is True
    assert signals["htf_trend_up"] is True
    assert signals["stop_price"] < signals["entry_price"]
    assert signals["tp2_price"] > signals["tp1_price"]


def test_bearish_htf_blocks_entry():
    ltf_df = _build_trending_df(260, "5min", start=100, slope=0.05)
    htf_df = _build_trending_df(240, "60min", start=200, slope=-0.5)

    config = PerpsConfig(minAtrPct=0.0005)
    signals = compute_signals_multi_tf(ltf_df, htf_df, config=config)

    assert signals["htf_trend_up"] is False
    assert signals["long_signal"] is False


def test_low_atr_filters_out_signal():
    ltf_df = _build_trending_df(260, "5min", start=100, slope=0.001)
    htf_df = _build_trending_df(240, "60min", start=90, slope=0.2)

    config = PerpsConfig(minAtrPct=0.02)
    signals = compute_signals_multi_tf(ltf_df, htf_df, config=config)

    assert signals["long_signal"] is False
    assert signals["atr_pct"] < config.minAtrPct


def test_price_not_chasing_far_above_ema():
    ltf_df = _build_trending_df(260, "5min", start=100, slope=0.05)
    htf_df = _build_trending_df(240, "60min", start=90, slope=0.4)
    config = PerpsConfig(minAtrPct=0.0005, maxEmaDistanceAtr=0.2)
    signals = compute_signals_multi_tf(ltf_df, htf_df, config=config)

    # Force final close far above EMA20/ATR to trip chasing guard
    atr = signals["atr"]
    ema20_value = signals["ema20"]
    exaggerated_close = ema20_value + atr * (config.maxEmaDistanceAtr + 1.0)
    ltf_df.iloc[-1, ltf_df.columns.get_loc("close")] = exaggerated_close
    ltf_df.iloc[-1, ltf_df.columns.get_loc("high")] = exaggerated_close + 0.5
    ltf_df.iloc[-1, ltf_df.columns.get_loc("low")] = exaggerated_close - 0.5

    fresh = compute_signals_multi_tf(ltf_df, htf_df, config=config)
    assert fresh["long_signal"] is False


def test_max_bars_in_trade_propagates():
    ltf_df = _build_trending_df(260, "5min", start=50, slope=0.05)
    htf_df = _build_trending_df(240, "60min", start=40, slope=0.4)
    config = PerpsConfig(maxBarsInTrade=80)
    signals = compute_signals_multi_tf(ltf_df, htf_df, config=config)
    assert signals["max_bars_in_trade"] == config.maxBarsInTrade
