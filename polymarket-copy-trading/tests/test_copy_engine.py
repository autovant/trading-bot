"""Tests for the copy engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.config import AppConfig, CopyConfig
from src.copy_engine import CopyEngine
from src.models import SourceTrade, TradeSide


@pytest.fixture
def engine(default_config) -> CopyEngine:
    return CopyEngine(default_config)


class TestCopyEngine:
    def test_proportional_sizing(self, engine, sample_source_trade):
        signal = engine.process(sample_source_trade)
        assert signal is not None
        assert signal.target_size == sample_source_trade.size  # multiplier=1.0
        assert signal.target_side == TradeSide.BUY
        assert signal.target_price == sample_source_trade.price

    def test_fixed_sizing(self, sample_source_trade):
        cfg = AppConfig(
            source_wallets=["0xabc"],
            copy=CopyConfig(sizing_mode="fixed", fixed_size_usdc=20.0),
        )
        engine = CopyEngine(cfg)
        signal = engine.process(sample_source_trade)
        assert signal is not None
        expected = 20.0 / sample_source_trade.price
        assert abs(signal.target_size - round(expected, 6)) < 0.001

    def test_size_multiplier(self, sample_source_trade):
        cfg = AppConfig(
            source_wallets=["0xabc"],
            copy=CopyConfig(sizing_mode="proportional", size_multiplier=0.5),
        )
        engine = CopyEngine(cfg)
        signal = engine.process(sample_source_trade)
        assert signal is not None
        assert signal.target_size == round(sample_source_trade.size * 0.5, 6)

    def test_skip_sells_when_disabled(self, sample_source_trade):
        cfg = AppConfig(
            source_wallets=["0xabc"],
            copy=CopyConfig(copy_sells=False),
        )
        engine = CopyEngine(cfg)
        sell_trade = sample_source_trade.model_copy(update={"side": TradeSide.SELL})
        signal = engine.process(sell_trade)
        assert signal is None

    def test_copy_sells_when_enabled(self, engine, sample_source_trade):
        sell_trade = sample_source_trade.model_copy(update={"side": TradeSide.SELL})
        signal = engine.process(sell_trade)
        assert signal is not None
        assert signal.target_side == TradeSide.SELL

    def test_min_trade_size_filter(self, sample_source_trade):
        cfg = AppConfig(
            source_wallets=["0xabc"],
            copy=CopyConfig(min_trade_size_usdc=1000.0),
        )
        engine = CopyEngine(cfg)
        signal = engine.process(sample_source_trade)
        assert signal is None  # 50 * 0.65 = 32.5 < 1000
