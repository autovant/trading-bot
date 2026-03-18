"""Tests for configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import AppConfig, CopyConfig, RiskConfig, load_config


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.dry_run is True
        assert cfg.poll_interval_seconds == 15
        assert cfg.source_wallets == []
        assert cfg.copy.sizing_mode == "proportional"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xtest")
        monkeypatch.setenv("POLYMARKET_CHAIN_ID", "80001")
        monkeypatch.setenv("SOURCE_WALLETS", "0xwallet1,0xwallet2")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        cfg = AppConfig()
        assert cfg.polymarket.private_key == "0xtest"
        assert cfg.polymarket.chain_id == 80001
        assert cfg.source_wallets == ["0xwallet1", "0xwallet2"]
        assert cfg.logging.level == "DEBUG"

    def test_invalid_sizing_mode(self):
        with pytest.raises(Exception):
            CopyConfig(sizing_mode="invalid")

    def test_risk_bounds(self):
        cfg = RiskConfig(max_price=0.99, min_price=0.01)
        assert cfg.max_price == 0.99
        assert cfg.min_price == 0.01

    def test_load_config_default(self, tmp_path):
        yaml_content = """
dry_run: false
poll_interval_seconds: 10
source_wallets:
  - "0xtest1"
copy:
  sizing_mode: fixed
  fixed_size_usdc: 25.0
risk:
  max_position_size_usdc: 50.0
"""
        config_file = tmp_path / "test.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))
        assert cfg.dry_run is False
        assert cfg.poll_interval_seconds == 10
        assert cfg.source_wallets == ["0xtest1"]
        assert cfg.copy.sizing_mode == "fixed"
        assert cfg.copy.fixed_size_usdc == 25.0
        assert cfg.risk.max_position_size_usdc == 50.0

    def test_load_config_missing_file(self, tmp_path):
        """Loading a missing config file returns defaults."""
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.dry_run is True
        assert cfg.source_wallets == []
