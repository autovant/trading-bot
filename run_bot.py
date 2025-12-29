#!/usr/bin/env python3
"""
Unified CLI for running the Zoomex perpetual futures trading bot.

Supports three modes:
- paper: Simulated trading (no real orders)
- testnet: Real orders on testnet (fake money)
- live: Real orders on mainnet (real money)

Usage:
    python run_bot.py --mode paper --config configs/zoomex_example.yaml
    python run_bot.py --mode testnet --config configs/zoomex_example.yaml
    python run_bot.py --mode live --config configs/zoomex_example.yaml
"""

import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import aiohttp

from src.app_logging.trade_logger import TradeLogger
from src.config import PerpsConfig, TradingBotConfig, get_config
from src.database import DatabaseManager
from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.risk.risk_manager import RiskManager
from src.services.perps import PerpsService
from src.state.daily_pnl_store import DailyPnlStore
from src.state.symbol_health_store import SymbolHealthStore, _format_iso
from tools.health_check_configs import evaluate_symbols_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/trading.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def load_best_configs(path: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Load best-configs JSON and return a mapping: symbol -> best-config entry.

    Basic validation: schema_version must start with "1." and symbols must be a
    non-empty list.
    """

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("Best-configs JSON must contain an object at the top level.")

    schema_version = str(payload.get("schema_version", ""))
    if not schema_version.startswith("1."):
        raise ValueError(
            f"Unsupported best-configs schema_version '{schema_version}'. Expected '1.x'."
        )

    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Best-configs JSON must include a non-empty 'symbols' list.")

    mapping: Dict[str, Dict[str, Any]] = {}
    for entry in symbols:
        if not isinstance(entry, dict):
            raise ValueError("Each entry in 'symbols' must be an object.")
        symbol = entry.get("symbol")
        if not symbol:
            raise ValueError("Best-config entry missing required 'symbol' field.")
        mapping[str(symbol)] = entry

    meta = {
        "metric": payload.get("metric"),
        "generated_at": payload.get("generated_at"),
        "path": str(path),
    }
    return mapping, meta


def _merge_perps_params(perps_cfg: PerpsConfig, params: Dict[str, Any]) -> PerpsConfig:
    """Return a new PerpsConfig with params merged (params win)."""
    merged = perps_cfg.model_copy(deep=True)

    for key, value in params.items():
        if hasattr(merged, key):
            setattr(merged, key, value)
        else:
            logger.debug("Ignoring unknown best-configs param for perps: %s", key)

    return merged


class RuntimeHealthSettings(TypedDict, total=False):
    enabled: bool
    interval_seconds: int
    window_trades: int
    min_trades: int
    metric: str
    cooldown_minutes: int
    warning_size_multiplier: float
    cooldown_backoff_multiplier: float
    best_configs_path: Optional[str]
    trades_csv: Optional[str]
    store_path: Optional[str]
    skip_if_unchanged_trades: bool


def start_runtime_health_monitor(
    symbols: List[str],
    best_configs_path: str,
    trades_csv_path: str,
    symbol_health_store: SymbolHealthStore,
    interval_seconds: int,
    window_trades: int,
    min_trades: int,
    metric: str,
    cooldown_minutes: int,
    logger: logging.Logger,
    stop_event: Optional[threading.Event] = None,
    skip_if_unchanged_trades: bool = False,
    cooldown_backoff_multiplier: float = 1.0,
) -> threading.Thread:
    """
    Spawn a daemon thread that periodically reevaluates symbol health and updates persistent state.
    """

    symbols_upper = [sym.upper() for sym in symbols]
    interval = max(int(interval_seconds), 1)
    trades_path = Path(trades_csv_path)
    last_trade_signature: Optional[Tuple[float, int]] = None

    def _parse_iso(timestamp: Optional[str]) -> Optional[datetime.datetime]:
        if not timestamp:
            return None
        try:
            cleaned = timestamp.replace("Z", "+00:00")
            return datetime.datetime.fromisoformat(cleaned)
        except Exception:
            return None

    def _evaluate_once() -> None:
        try:
            results, _ = evaluate_symbols_health(
                best_configs_path,
                trades_csv_path,
                symbol_filter=symbols_upper,
                window_trades=window_trades,
                min_trades=min_trades,
                metric=metric,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.error("Runtime health evaluation failed: %s", exc, exc_info=True)
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        for symbol in symbols_upper:
            result = results.get(symbol)
            if not result:
                logger.debug("Runtime health: no result for %s", symbol)
                continue

            status = str(result.get("status") or "UNKNOWN").upper()
            reasons = result.get("reasons") or []
            blocked_until = None

            prior = symbol_health_store.get_symbol_state(symbol)
            prior_status = prior.get("last_status")
            prior_block = prior.get("blocked_until")
            prior_block_dt = _parse_iso(prior_block)
            reasons_text = ", ".join(reasons) or "unspecified"

            if status == "FAILING":
                effective_cooldown: float = float(cooldown_minutes)
                if (
                    cooldown_backoff_multiplier
                    and prior_status == "FAILING"
                    and cooldown_minutes > 0
                ):
                    effective_cooldown *= cooldown_backoff_multiplier
                blocked_dt = now + datetime.timedelta(minutes=effective_cooldown)
                if prior_block_dt and prior_block_dt > blocked_dt:
                    blocked_dt = prior_block_dt
                blocked_until = _format_iso(blocked_dt)

            if blocked_until:
                logger.warning(
                    "Runtime health: %s marked FAILING, blocking new entries until %s (reasons=%s)",
                    symbol,
                    blocked_until,
                    reasons_text,
                )
            elif prior_status and prior_status != status:
                logger.info(
                    "Runtime health: %s status changed %s -> %s (reasons=%s)",
                    symbol,
                    prior_status,
                    status,
                    reasons_text,
                )
            elif prior_block and not blocked_until:
                logger.info("Runtime health: %s cooldown cleared", symbol)

            if (
                status == prior_status
                and blocked_until == prior_block
                and reasons == (prior.get("last_reasons") or [])
            ):
                logger.debug("Runtime health: %s unchanged; skipping persist", symbol)
                continue

            symbol_health_store.update_symbol_state(
                symbol,
                status=status,
                reasons=reasons,
                blocked_until=blocked_until,
                evaluated_at=_format_iso(now),
            )

    def _has_new_trades() -> bool:
        nonlocal last_trade_signature
        if not skip_if_unchanged_trades:
            return True
        try:
            stat = trades_path.stat()
        except FileNotFoundError:
            logger.debug(
                "Runtime health: trades CSV not found at %s; skipping.", trades_path
            )
            return False
        signature = (stat.st_mtime, stat.st_size)
        if last_trade_signature == signature:
            logger.debug(
                "Runtime health: no new trades since last check; skipping evaluation."
            )
            return False
        last_trade_signature = signature
        return True

    def _loop() -> None:
        logger.info(
            "Starting runtime health monitor for symbols=%s interval=%ss window=%s min_trades=%s",
            ",".join(symbols_upper),
            interval,
            window_trades,
            min_trades,
        )
        while True:
            if _has_new_trades():
                _evaluate_once()
            if stop_event:
                if stop_event.wait(interval):
                    logger.info("Runtime health monitor stop requested; exiting thread")
                    return
            else:
                time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True, name="runtime-health-monitor")
    thread.start()
    return thread


class TradingBot:
    def __init__(
        self,
        mode: str,
        config_path: str,
        overrides: dict,
        best_configs_path: Optional[str] = None,
        best_configs_strict: bool = False,
        risk_limits: Optional[dict] = None,
        trade_log_csv: Optional[str] = None,
        health_settings: Optional[dict] = None,
        daily_pnl_store_path: Optional[str] = None,
        runtime_health_settings: Optional[RuntimeHealthSettings] = None,
    ):
        self.mode = mode
        self.config_path = config_path
        self.overrides = overrides
        self.best_configs_path = best_configs_path
        self.best_configs_strict = best_configs_strict
        self.trade_log_csv = trade_log_csv
        self.health_settings = health_settings or {}
        self.runtime_health_settings: RuntimeHealthSettings = (
            runtime_health_settings or {}
        )
        self.risk_limits = risk_limits or {
            "max_account_risk_pct": 0.02,
            "max_open_risk_pct": 0.05,
            "max_symbol_risk_pct": 0.03,
            "max_daily_loss_usd": None,
        }
        self.daily_pnl_store_path = daily_pnl_store_path
        self.config: Optional[TradingBotConfig] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.perps_service: Optional[PerpsService] = None
        self.risk_manager: Optional[RiskManager] = None
        self.trade_logger: Optional[TradeLogger] = None
        self.active_config_id: Optional[str] = Path(config_path).stem
        self.running = False
        self._best_configs_meta: Dict[str, Any] = {}
        self._best_configs: Dict[str, Dict[str, Any]] = {}
        self.symbol_health_store: Optional[SymbolHealthStore] = None
        self.runtime_health_stop_event: Optional[threading.Event] = None
        self.runtime_health_thread: Optional[threading.Thread] = None
        self.database: Optional[DatabaseManager] = None

    def _require_config(self) -> TradingBotConfig:
        if self.config is None:
            raise RuntimeError("TradingBot config not loaded; call initialize() first")
        return self.config

    async def initialize(self):
        logger.info("=" * 60)
        logger.info("Zoomex Perpetual Futures Trading Bot")
        logger.info("=" * 60)
        logger.info(f"Mode: {self.mode.upper()}")
        logger.info(f"Config: {self.config_path}")
        logger.info("=" * 60)

        if not Path(self.config_path).exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        os.environ["CONFIG_PATH"] = self.config_path
        self.config = get_config()

        self._maybe_apply_best_configs()
        self._apply_overrides()
        self._validate_mode()
        self._maybe_run_health_gating()

        self.session = aiohttp.ClientSession()
        trade_log_path = Path(self.trade_log_csv or "results/live_trades.csv")
        self.trade_logger = TradeLogger(trade_log_path)

        self.database = DatabaseManager(self.config.database.url)
        await self.database.initialize()

        if hasattr(self.config, "perps") and self.config.perps.enabled:
            exchange = ZoomexV3Client(
                self.session,
                base_url=self.config.exchange.base_url,
                api_key=self.config.exchange.api_key,
                api_secret=self.config.exchange.secret_key,
                mode_name=self.mode,
                max_requests_per_second=self.config.perps.maxRequestsPerSecond,
                max_requests_per_minute=self.config.perps.maxRequestsPerMinute,
            )
            self.perps_service = PerpsService(
                self.config.perps,
                exchange,
                trading_config=self.config.trading,
                crisis_config=self.config.risk_management.crisis_mode,
                trade_logger=self.trade_logger,
                config_id=self.active_config_id,
                database=self.database,
                mode_name=self.mode,
            )
            await self.perps_service.initialize()
            logger.info("Perps service initialized successfully")
        else:
            raise ValueError("Perps trading is not enabled in configuration")

        starting_equity = self.perps_service.equity_usdt if self.perps_service else 0.0
        if starting_equity <= 0:
            fallback_equity = getattr(self.config.trading, "initial_capital", 0.0)
            logger.warning(
                "RiskManager: wallet equity unavailable; using config.initial_capital=$%.2f",
                fallback_equity,
            )
            starting_equity = fallback_equity

        daily_store = None
        account_id = None
        if self.risk_limits.get("max_daily_loss_usd") and self.daily_pnl_store_path:
            daily_store = DailyPnlStore(self.daily_pnl_store_path)
            account_id = self._derive_account_id()
            today_key = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%d"
            )
            current_pnl = daily_store.get_pnl(account_id, today_key)
            logger.info(
                "DailyPnLStore initialized path=%s account_id=%s today=%s pnl=%.2f",
                self.daily_pnl_store_path,
                account_id,
                today_key,
                current_pnl,
            )

        self.risk_manager = RiskManager(
            starting_equity=starting_equity,
            max_account_risk_pct=self.risk_limits.get("max_account_risk_pct", 0.02),
            max_open_risk_pct=self.risk_limits.get("max_open_risk_pct", 0.05),
            max_symbol_risk_pct=self.risk_limits.get("max_symbol_risk_pct", 0.03),
            max_daily_loss_usd=self.risk_limits.get("max_daily_loss_usd"),
            daily_pnl_store=daily_store,
            account_id=account_id,
        )
        logger.info(
            "RiskManager: start_equity=$%.2f max_account_risk=%.2f%% max_open_risk=%.2f%% "
            "max_symbol_risk=%.2f%% max_daily_loss=%s",
            self.risk_manager.starting_equity,
            self.risk_manager.max_account_risk_pct * 100,
            self.risk_manager.max_open_risk_pct * 100,
            self.risk_manager.max_symbol_risk_pct * 100,
            (
                self.risk_manager.max_daily_loss_usd
                if self.risk_manager.max_daily_loss_usd is not None
                else "None"
            ),
        )
        if self.perps_service:
            self.perps_service.set_risk_manager(self.risk_manager)

        self._attach_symbol_health_store()
        self._maybe_start_runtime_health_monitor()

        logger.info("Bot initialization complete")
        logger.info("=" * 60)

    def _apply_overrides(self):
        if not self.overrides:
            return

        logger.info("Applying configuration overrides:")
        for key, value in self.overrides.items():
            if hasattr(self.config.perps, key):
                old_value = getattr(self.config.perps, key)
                setattr(self.config.perps, key, value)
                logger.info(f"  {key}: {old_value} -> {value}")
            else:
                logger.warning(f"  Unknown override key: {key}")

    def _derive_account_id(self) -> str:
        config = self._require_config()
        exchange = getattr(config.perps, "exchange", "unknown")
        return f"{exchange}-{self.mode}"

    def _health_status_allows(self, status: str, min_status: str) -> bool:
        order = {"OK": 2, "WARNING": 1, "FAILING": 0, "INSUFFICIENT_DATA": -1}
        min_required = order.get(min_status.upper(), 1)
        return order.get(status.upper(), -1) >= min_required

    def _default_runtime_health_store_path(self) -> str:
        configured = self.runtime_health_settings.get("store_path")
        if configured:
            return str(configured)
        base_dir = (
            Path(self.daily_pnl_store_path).parent
            if self.daily_pnl_store_path
            else Path("state")
        )
        return str(base_dir / "symbol_health.json")

    def _resolve_runtime_health_sources(self) -> Tuple[Optional[str], Optional[str]]:
        settings = self.runtime_health_settings or {}
        best_path = settings.get("best_configs_path") or self.best_configs_path
        trades_path = settings.get("trades_csv")
        if not trades_path and self.trade_logger:
            trades_path = str(
                getattr(self.trade_logger, "csv_path", self.trade_log_csv)
            )
        if not trades_path:
            trades_path = self.trade_log_csv
        return best_path, trades_path

    def _attach_symbol_health_store(self) -> None:
        if not self.runtime_health_settings.get("enabled"):
            return

        store_path = self._default_runtime_health_store_path()
        self.symbol_health_store = SymbolHealthStore(store_path)
        logger.info("Runtime symbol health store attached at %s", store_path)

        if self.perps_service:
            self.perps_service.set_symbol_health_store(
                self.symbol_health_store,
                warning_size_multiplier=self.runtime_health_settings.get(
                    "warning_size_multiplier", 1.0
                ),
            )

    def _maybe_start_runtime_health_monitor(self) -> None:
        settings = self.runtime_health_settings or {}
        if not settings.get("enabled"):
            return
        if not self.perps_service:
            logger.warning(
                "Runtime health enabled but perps service unavailable; skipping monitor."
            )
            return

        best_path, trades_path = self._resolve_runtime_health_sources()
        if not best_path or not trades_path:
            logger.warning(
                "Runtime health requested but missing best-configs or trades CSV path; monitor not started."
            )
            return

        if not self.symbol_health_store:
            self._attach_symbol_health_store()
        if not self.symbol_health_store:
            return

        interval_seconds = settings.get("interval_seconds", 300)
        window_trades = settings.get("window_trades", 100)
        min_trades = settings.get("min_trades", 30)
        metric = settings.get("metric", "pnl_pct")
        cooldown_minutes = settings.get("cooldown_minutes", 60)
        skip_if_unchanged_trades = settings.get("skip_if_unchanged_trades", False)
        cooldown_backoff_multiplier = settings.get("cooldown_backoff_multiplier", 1.0)

        self.runtime_health_stop_event = threading.Event()
        self.runtime_health_thread = start_runtime_health_monitor(
            [self.perps_service.config.symbol],
            str(best_path),
            str(trades_path),
            self.symbol_health_store,
            interval_seconds,
            window_trades,
            min_trades,
            metric,
            cooldown_minutes,
            logger,
            stop_event=self.runtime_health_stop_event,
            skip_if_unchanged_trades=skip_if_unchanged_trades,
            cooldown_backoff_multiplier=cooldown_backoff_multiplier,
        )

    def _maybe_run_health_gating(self) -> None:
        settings = self.health_settings or {}
        if not settings.get("enabled"):
            return

        best_path = settings.get("best_configs_path") or self.best_configs_path
        trades_path = settings.get("trades_csv") or self.trade_log_csv
        if not best_path or not trades_path:
            logger.warning(
                "Health gating requested but missing paths (best_configs_json or trades_csv). Skipping."
            )
            return

        config = self._require_config()
        symbol = self.overrides.get("symbol") or getattr(config.perps, "symbol", None)
        if not symbol:
            logger.warning("Health gating skipped: no symbol configured.")
            return

        logger.info(
            "Running health check for symbol %s (min_status=%s, window=%s, min_trades=%s)",
            symbol,
            settings.get("min_status"),
            settings.get("window_trades"),
            settings.get("min_trades"),
        )

        try:
            results, _ = evaluate_symbols_health(
                best_path,
                trades_path,
                symbol_filter=[symbol],
                window_trades=settings.get("window_trades", 100),
                min_trades=settings.get("min_trades", 30),
                metric=settings.get("metric", "pnl_pct"),
            )
        except Exception as exc:
            logger.error("Health check failed; proceeding without gating: %s", exc)
            return

        result = results.get(symbol.upper())
        if not result:
            logger.warning(
                "Health check produced no result for %s; skipping gating.", symbol
            )
            return

        min_status = settings.get("min_status", "WARNING")
        strict = settings.get("strict", False)

        if self._health_status_allows(result["status"], min_status):
            logger.info(
                "Health check OK for %s (status=%s)",
                symbol,
                result.get("status", "UNKNOWN"),
            )
            return

        reasons = result.get("reasons", [])
        logger_method = logger.error if strict else logger.warning
        logger_method(
            "Health gate blocked symbol %s (status=%s, reasons=%s)",
            symbol,
            result.get("status"),
            ", ".join(reasons) or "unknown",
        )

        exit_code = 1 if strict else 0
        raise SystemExit(exit_code)

    def _maybe_apply_best_configs(self) -> None:
        if not self.best_configs_path:
            return

        config = self._require_config()
        mapping, meta = load_best_configs(self.best_configs_path)
        self._best_configs = mapping
        self._best_configs_meta = meta

        logger.info(
            "Using best-configs JSON from: %s, metric=%s, generated_at=%s",
            meta.get("path"),
            meta.get("metric"),
            meta.get("generated_at"),
        )

        requested_symbol = self.overrides.get("symbol") or config.perps.symbol
        entry = mapping.get(requested_symbol)

        if not entry:
            message = (
                f"Symbol={requested_symbol}: no best-config entry found in "
                f"{self.best_configs_path}, falling back to existing config behavior"
            )
            if self.best_configs_strict:
                raise ValueError(message)
            logger.warning(message)
            return

        logger.info(
            "Symbol=%s: using config_id=%s, metric_mean=%s, metric_max=%s, "
            "num_runs=%s, total_trades=%s",
            requested_symbol,
            entry.get("config_id"),
            entry.get("metric_mean"),
            entry.get("metric_max"),
            entry.get("num_runs"),
            entry.get("total_trades"),
        )
        if entry.get("config_id"):
            self.active_config_id = str(entry.get("config_id"))

        params = entry.get("params") or {}
        config.perps = _merge_perps_params(config.perps, params)

    def _validate_mode(self):
        if self.mode == "paper":
            logger.info("Running in PAPER mode (simulated trading)")
            logger.info("  - No real orders will be placed")
            logger.info("  - All signals and decisions will be logged")
        elif self.mode == "testnet":
            if hasattr(self.config, "exchange") and not self.config.exchange.testnet:
                logger.warning(
                    "Mode is 'testnet' but exchange config has testnet=false"
                )
                self.config.exchange.testnet = True
            if not self.config.perps.useTestnet:
                logger.warning("Mode is 'testnet' but config has useTestnet=false")
                logger.warning("Forcing useTestnet=true for safety")
                self.config.perps.useTestnet = True
            logger.info("Running in TESTNET mode (real orders, fake money)")
            logger.info("  - Orders will be placed on testnet")
            logger.info("  - Using testnet API keys")
        elif self.mode == "live":
            if hasattr(self.config, "exchange") and self.config.exchange.testnet:
                logger.error("Mode is 'live' but exchange config has testnet=true")
                raise ValueError(
                    "Configuration mismatch: live mode requires exchange.testnet=false"
                )
            if self.config.perps.useTestnet:
                logger.error("Mode is 'live' but config has useTestnet=true")
                logger.error("This would place orders on testnet, not mainnet")
                raise ValueError(
                    "Configuration mismatch: live mode requires useTestnet=false"
                )
            logger.warning("=" * 60)
            logger.warning("⚠️  RUNNING IN LIVE MODE - REAL MONEY AT RISK  ⚠️")
            logger.warning("=" * 60)
            logger.warning("  - Real orders will be placed on mainnet")
            logger.warning("  - Real funds will be used")
            logger.warning("  - Real profit/loss will occur")
            logger.warning("=" * 60)

            response = input("Type 'I UNDERSTAND THE RISKS' to continue: ")
            if response != "I UNDERSTAND THE RISKS":
                logger.error("Live trading cancelled by user")
                sys.exit(0)

        api_key = os.getenv("ZOOMEX_API_KEY")
        api_secret = os.getenv("ZOOMEX_API_SECRET")
        if not api_key or not api_secret:
            raise ValueError(
                "ZOOMEX_API_KEY and ZOOMEX_API_SECRET environment variables must be set"
            )

        logger.info(f"Symbol: {self.config.perps.symbol}")
        logger.info(f"Interval: {self.config.perps.interval}m")
        logger.info(f"Leverage: {self.config.perps.leverage}x")
        logger.info(f"Risk per trade: {self.config.perps.riskPct * 100:.2f}%")
        logger.info(f"Stop-loss: {self.config.perps.stopLossPct * 100:.2f}%")
        logger.info(f"Take-profit: {self.config.perps.takeProfitPct * 100:.2f}%")
        logger.info(
            f"Circuit breaker: {self.config.perps.consecutiveLossLimit or 'disabled'}"
        )

    async def run(self):
        self.running = True
        logger.info("Starting trading loop...")
        logger.info("Press Ctrl+C to stop")

        cycle_count = 0
        try:
            while self.running:
                cycle_count += 1
                logger.debug(f"Cycle {cycle_count}")

                # Unified cycle: PerpsService now handles Paper/Shadow mode internally
                await self.perps_service.run_cycle()

                await asyncio.sleep(60)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Trading loop error: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def _run_paper_cycle(self):
        if not self.perps_service:
            return

        try:
            df = await self.perps_service.client.get_klines(
                symbol=self.perps_service.config.symbol,
                interval=self.perps_service.config.interval,
                limit=100,
            )

            if df.empty or len(df) < 35:
                logger.debug("Insufficient klines data")
                return

            closed_df = self.perps_service._closed_candle_view(df)
            if len(closed_df) < 35:
                logger.debug("Waiting for full indicator warmup")
                return

            last_closed_time = closed_df.index[-1]
            if self.perps_service.last_candle_time == last_closed_time:
                return

            from src.strategies.perps_trend_vwap import compute_signals

            signals = compute_signals(closed_df)
            self.perps_service.last_candle_time = last_closed_time

            if signals["long_signal"]:
                logger.info("=" * 60)
                logger.info("📈 LONG SIGNAL DETECTED (PAPER MODE)")
                logger.info("=" * 60)
                logger.info(f"Price: {signals['price']:.4f}")
                logger.info(f"Fast MA: {signals['fast']:.4f}")
                logger.info(f"Slow MA: {signals['slow']:.4f}")
                logger.info(f"VWAP: {signals['vwap']:.4f}")
                logger.info(f"RSI: {signals['rsi']:.2f}")
                logger.info("=" * 60)
                logger.info("⚠️  No order placed (paper mode)")
                logger.info("=" * 60)
            else:
                logger.debug(
                    f"No signal: price={signals['price']:.4f} "
                    f"fast={signals['fast']:.4f} slow={signals['slow']:.4f} "
                    f"rsi={signals['rsi']:.2f}"
                )

        except Exception as e:
            logger.error(f"Paper cycle error: {e}", exc_info=True)

    async def shutdown(self):
        logger.info("Shutting down bot...")
        self.running = False

        if self.runtime_health_stop_event:
            self.runtime_health_stop_event.set()
        if self.runtime_health_thread:
            self.runtime_health_thread.join(timeout=5)

        if self.session:
            await self.session.close()
            logger.info("HTTP session closed")

        if self.database:
            await self.database.close()
            logger.info("Database connection closed")

        logger.info("Shutdown complete")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Zoomex Perpetual Futures Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Paper trading (simulated)
  python run_bot.py --mode paper --config configs/zoomex_example.yaml

  # Testnet trading (real orders, fake money)
  python run_bot.py --mode testnet --config configs/zoomex_example.yaml

  # Live trading (real money)
  python run_bot.py --mode live --config configs/zoomex_example.yaml

  # Override parameters
  python run_bot.py --mode testnet --symbol BTCUSDT --leverage 2

  # Dry run (validate config only)
  python run_bot.py --mode paper --config configs/zoomex_example.yaml --dry-run
        """,
    )

    parser.add_argument(
        "--mode",
        type=str,
        required=True,
        choices=["paper", "testnet", "live"],
        help="Trading mode: paper (simulated), testnet (fake money), live (real money)",
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy.yaml",
        help="Path to configuration file (default: config/strategy.yaml)",
    )

    parser.add_argument(
        "--symbol",
        type=str,
        help="Override trading symbol (e.g., BTCUSDT)",
    )

    parser.add_argument(
        "--interval",
        type=str,
        help="Override candle interval (e.g., 5 for 5 minutes)",
    )

    parser.add_argument(
        "--leverage",
        type=int,
        help="Override leverage (1-10)",
    )

    parser.add_argument(
        "--risk-pct",
        type=float,
        help="Override risk percentage per trade (e.g., 0.005 for 0.5%%)",
    )

    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        help="Override stop-loss percentage (e.g., 0.01 for 1%%)",
    )

    parser.add_argument(
        "--take-profit-pct",
        type=float,
        help="Override take-profit percentage (e.g., 0.03 for 3%%)",
    )

    parser.add_argument(
        "--max-account-risk-pct",
        type=float,
        default=2.0,
        help="Max realized account loss in %% before blocking new entries (default: 2.0)",
    )

    parser.add_argument(
        "--max-open-risk-pct",
        type=float,
        default=5.0,
        help="Max open exposure as %% of equity (default: 5.0)",
    )

    parser.add_argument(
        "--max-symbol-risk-pct",
        type=float,
        default=3.0,
        help="Max open exposure per symbol as %% of equity (default: 3.0)",
    )

    parser.add_argument(
        "--max-daily-loss-usd",
        type=float,
        default=None,
        help="Optional hard daily loss stop in USD (default: disabled)",
    )

    parser.add_argument(
        "--best-configs-json",
        type=str,
        help="Path to best_configs.json produced by tools/analyze_sweeps.py",
    )

    parser.add_argument(
        "--best-configs-strict",
        action="store_true",
        help="Abort if a requested symbol is missing from the best-configs JSON "
        "(default is warn and fall back).",
    )

    parser.add_argument(
        "--trade-log-csv",
        type=str,
        default="results/live_trades.csv",
        help="Path to CSV file for logging completed trades (default: results/live_trades.csv)",
    )

    parser.add_argument(
        "--health-check-best-configs-json",
        type=str,
        help="Optional best-configs JSON path for health check gating (defaults to --best-configs-json).",
    )
    parser.add_argument(
        "--health-check-trades-csv",
        type=str,
        help="Optional trades CSV path for health check gating (defaults to --trade-log-csv).",
    )
    parser.add_argument(
        "--health-window-trades",
        type=int,
        default=100,
        help="Number of recent trades to include in health check (default: 100).",
    )
    parser.add_argument(
        "--health-min-trades",
        type=int,
        default=30,
        help="Minimum trades required per symbol for health check (default: 30).",
    )
    parser.add_argument(
        "--health-min-status",
        type=str,
        choices=["OK", "WARNING", "FAILING"],
        help="Minimum acceptable health status (default: WARNING).",
    )
    parser.add_argument(
        "--health-strict",
        action="store_true",
        help="If set, abort startup when any configured symbol fails health gating.",
    )

    parser.add_argument(
        "--runtime-health-enabled",
        action="store_true",
        help="Enable runtime symbol health monitoring and adaptive controls (default: disabled).",
    )
    parser.add_argument(
        "--runtime-health",
        dest="runtime_health_enabled",
        action="store_true",
        help="Alias for --runtime-health-enabled.",
    )
    parser.add_argument(
        "--runtime-health-interval-seconds",
        type=int,
        default=300,
        help="Seconds between runtime health evaluations (default: 300).",
    )
    parser.add_argument(
        "--runtime-health-window-trades",
        type=int,
        default=100,
        help="Number of recent trades to include in runtime health (default: 100).",
    )
    parser.add_argument(
        "--runtime-health-min-trades",
        type=int,
        default=30,
        help="Minimum trades required per symbol for runtime health (default: 30).",
    )
    parser.add_argument(
        "--runtime-health-metric",
        type=str,
        default="pnl_pct",
        help="Metric used for runtime health evaluation (default: pnl_pct).",
    )
    parser.add_argument(
        "--runtime-health-cooldown-minutes",
        type=int,
        default=60,
        help="Cooldown minutes applied when a symbol is marked FAILING (default: 60).",
    )
    parser.add_argument(
        "--runtime-health-cooldown-backoff-multiplier",
        type=float,
        default=1.0,
        help="When consecutive FAILING statuses occur, multiply cooldown minutes by this factor (default: 1.0).",
    )
    parser.add_argument(
        "--runtime-health-warning-size-multiplier",
        type=float,
        default=0.5,
        help="Position size multiplier when a symbol is in WARNING state (default: 0.5).",
    )
    parser.add_argument(
        "--runtime-health-store-json",
        type=str,
        help="Optional path to runtime symbol health store (default: state/symbol_health.json).",
    )
    parser.add_argument(
        "--runtime-health-skip-unchanged-trades",
        dest="runtime_health_skip_unchanged_trades",
        action="store_true",
        default=True,
        help="Skip runtime health evaluation when the trade log has not changed since the last check (default: enabled).",
    )
    parser.add_argument(
        "--runtime-health-keep-evaluating",
        dest="runtime_health_skip_unchanged_trades",
        action="store_false",
        help="Force runtime health evaluation every interval even if no new trades are present.",
    )

    parser.add_argument(
        "--daily-pnl-store-json",
        type=str,
        default="state/daily_pnl.json",
        help="Path to JSON file for persisting daily PnL (used with --max-daily-loss-usd).",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without starting bot",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    Path("logs").mkdir(exist_ok=True)

    overrides = {}
    if args.symbol:
        overrides["symbol"] = args.symbol
    if args.interval:
        overrides["interval"] = args.interval
    if args.leverage:
        overrides["leverage"] = args.leverage
    if args.risk_pct:
        overrides["riskPct"] = args.risk_pct
    if args.stop_loss_pct:
        overrides["stopLossPct"] = args.stop_loss_pct
    if args.take_profit_pct:
        overrides["takeProfitPct"] = args.take_profit_pct

    risk_limits = {
        "max_account_risk_pct": (args.max_account_risk_pct or 0) / 100.0,
        "max_open_risk_pct": (args.max_open_risk_pct or 0) / 100.0,
        "max_symbol_risk_pct": (args.max_symbol_risk_pct or 0) / 100.0,
        "max_daily_loss_usd": args.max_daily_loss_usd,
    }

    health_enabled = bool(
        args.health_check_best_configs_json
        or args.health_check_trades_csv
        or args.health_min_status is not None
        or args.health_strict
    )
    health_min_status = args.health_min_status or "WARNING"
    health_settings = {
        "enabled": health_enabled,
        "best_configs_path": args.health_check_best_configs_json
        or args.best_configs_json,
        "trades_csv": args.health_check_trades_csv or args.trade_log_csv,
        "window_trades": args.health_window_trades,
        "min_trades": args.health_min_trades,
        "metric": "pnl_pct",
        "min_status": health_min_status,
        "strict": args.health_strict,
    }

    default_health_store_dir = (
        Path(args.daily_pnl_store_json).parent
        if args.daily_pnl_store_json
        else Path("state")
    )
    runtime_health_store = args.runtime_health_store_json or str(
        default_health_store_dir / "symbol_health.json"
    )
    runtime_health_settings = {
        "enabled": args.runtime_health_enabled,
        "interval_seconds": args.runtime_health_interval_seconds,
        "window_trades": args.runtime_health_window_trades,
        "min_trades": args.runtime_health_min_trades,
        "metric": args.runtime_health_metric,
        "cooldown_minutes": args.runtime_health_cooldown_minutes,
        "warning_size_multiplier": args.runtime_health_warning_size_multiplier,
        "cooldown_backoff_multiplier": args.runtime_health_cooldown_backoff_multiplier,
        "best_configs_path": args.health_check_best_configs_json
        or args.best_configs_json,
        "trades_csv": args.trade_log_csv,
        "store_path": runtime_health_store,
        "skip_if_unchanged_trades": args.runtime_health_skip_unchanged_trades,
    }

    bot = TradingBot(
        args.mode,
        args.config,
        overrides,
        best_configs_path=args.best_configs_json,
        best_configs_strict=args.best_configs_strict,
        risk_limits=risk_limits,
        trade_log_csv=args.trade_log_csv,
        health_settings=health_settings,
        daily_pnl_store_path=args.daily_pnl_store_json
        if args.max_daily_loss_usd
        else None,
        runtime_health_settings=runtime_health_settings,
    )

    try:
        await bot.initialize()

        if args.dry_run:
            logger.info("=" * 60)
            logger.info("✅ Configuration validated successfully")
            logger.info("=" * 60)
            logger.info("Dry run complete - bot not started")
            return

        await bot.run()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown complete")
