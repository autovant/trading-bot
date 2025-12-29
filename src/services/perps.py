from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.alerts.base import AlertSink
from src.alerts.manager import AlertManager
from src.app_logging.trade_logger import TradeLogger
from src.config import CrisisModeConfig, PerpsConfig, TradingConfig
from src.database import DatabaseManager, OrderIntent
from src.engine.order_id_generator import generate_order_id
from src.engine.order_intent_ledger import OrderIntentLedger
from src.engine.perps_executor import (
    early_exit_reduce_only,
    enter_long_with_brackets,
    risk_position_size,
    round_quantity,
)
from src.engine.pnl_tracker import PnLTracker
from src.exchange import ExchangeClient
from src.exchanges.zoomex_v3 import ZoomexError
from src.risk.risk_manager import RiskManager
from src.state.perps_state_store import (
    load_perps_state,
    save_perps_state,
)
from src.state.symbol_health_store import SymbolHealthStore
from src.strategies.perps_trend_atr_multi_tf import compute_signals_multi_tf
from src.strategies.perps_trend_vwap import compute_signals

logger = logging.getLogger(__name__)


class PerpsService:
    def __init__(
        self,
        config: PerpsConfig,
        exchange: ExchangeClient,
        trading_config: Optional[TradingConfig] = None,
        crisis_config: Optional[CrisisModeConfig] = None,
        alert_sink: Optional[AlertSink] = None,
        risk_manager: Optional[RiskManager] = None,
        trade_logger: Optional[TradeLogger] = None,
        config_id: Optional[str] = None,
        symbol_health_store: Optional[SymbolHealthStore] = None,
        warning_size_multiplier: float = 1.0,
        database: Optional[DatabaseManager] = None,
        mode_name: Optional[str] = None,
    ):
        self.config = config
        self.exchange = exchange
        self.equity_usdt = 0.0
        self.last_candle_time: Optional[datetime] = None
        self.current_position_qty = 0.0
        self.leverage_set = False
        self.interval_delta = self._resolve_interval_delta(config.interval)
        self.pnl_tracker = PnLTracker()
        self.entry_bar_time: Optional[datetime] = None
        self.last_position_check_time: Optional[datetime] = None
        self.reconciliation_block_active = False
        self.session_start_time: Optional[datetime] = None
        self.session_trades: int = 0
        self.trading_config = trading_config
        self.crisis_config = crisis_config
        self.alert_sink: AlertSink = alert_sink or AlertManager()
        self.risk_manager = risk_manager
        self.trade_logger = trade_logger
        self.config_id = config_id
        self.symbol_health_store = symbol_health_store
        self.warning_size_multiplier = warning_size_multiplier
        self.strategy_name = (
            "perps_trend_atr_multi_tf"
            if self.config.useMultiTfAtrStrategy
            else "perps_trend_vwap"
        )
        self.last_entry_time: Optional[datetime] = None
        self.last_entry_price: Optional[float] = None
        self.last_entry_qty: Optional[float] = None
        self.entry_equity: Optional[float] = None
        self.last_risk_blocked: Optional[bool] = None
        self.max_daily_loss_pct = (
            trading_config.max_daily_risk if trading_config else 0.05
        )
        self.drawdown_threshold = (
            crisis_config.drawdown_threshold if crisis_config else 0.10
        )
        self.database = database
        self.mode_name = mode_name or ("paper" if self.config.useTestnet else "live")
        self.intent_ledger = (
            OrderIntentLedger(
                database=self.database,
                mode="paper" if self.mode_name == "paper" else "live",
                run_id=self.config_id or "perps",
            )
            if self.database
            else None
        )
        self.data_stale_block_active = False
        self._last_reconcile_at: Optional[datetime] = None
        self._last_time_sync_at: Optional[datetime] = None
        state_file = self.config.stateFile or "data/perps_state.json"
        self.state_path = Path(state_file)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def set_risk_manager(self, risk_manager: RiskManager) -> None:
        """Attach a RiskManager instance after construction."""
        self.risk_manager = risk_manager
        if self.risk_manager and self.equity_usdt > 0:
            self.risk_manager.update_equity(self.equity_usdt)

    def set_symbol_health_store(
        self,
        symbol_health_store: Optional[SymbolHealthStore],
        warning_size_multiplier: Optional[float] = None,
    ) -> None:
        """Attach or update the runtime symbol health store."""
        self.symbol_health_store = symbol_health_store
        if warning_size_multiplier is not None:
            self.warning_size_multiplier = warning_size_multiplier

    async def initialize(self):
        if not self.config.enabled:
            logger.info("Perps trading disabled")
            return

        if self.mode_name == "live" and not self.database:
            raise ValueError("PerpsService requires a database for live trading.")

        # Initialize exchange client (it might already be initialized by main, but safe to call again)
        if hasattr(self.exchange, "initialize"):
            await self.exchange.initialize()

        await self._sync_time_or_halt()

        await self._refresh_account_state()

        if self.risk_manager:
            self.risk_manager.update_equity(self.equity_usdt)

        await self._reconcile_positions()
        await self._reconcile_open_orders(reason="startup")
        self._load_persisted_state()
        self.session_start_time = datetime.now(timezone.utc)

        logger.info(
            "Perps service initialized: symbol=%s mode=%s testnet=%s equity=$%.2f",
            self.config.symbol,
            self.config.mode,
            self.config.useTestnet,
            self.equity_usdt,
        )

    async def run_cycle(self):
        if not self.config.enabled or not self.exchange:
            return

        try:
            await self._sync_time_or_halt(periodic=True)
            await self._refresh_account_state()
            await self._check_position_pnl()

            if not await self._check_risk_limits():
                return

            if not await self._check_session_limits():
                return

            await self._reconcile_open_orders(reason="periodic")

            ltf_limit = 100
            if self.config.useMultiTfAtrStrategy:
                ltf_limit = max(
                    200, self.config.maxBarsInTrade + self.config.atrPeriod * 4
                )

            tasks = [
                self.exchange.get_historical_data(
                    symbol=self.config.symbol,
                    timeframe=self.config.interval,
                    limit=ltf_limit,
                )
            ]
            htf_interval_delta: Optional[timedelta] = None

            if self.config.useMultiTfAtrStrategy:
                htf_interval_delta = self._resolve_interval_delta(
                    self.config.htfInterval
                )
                tasks.append(
                    self.exchange.get_historical_data(
                        symbol=self.config.symbol,
                        timeframe=self.config.htfInterval,
                        limit=260,
                    )
                )

            results = await asyncio.gather(*tasks)
            df = results[0]
            htf_df = results[1] if len(results) > 1 else None

            if df is None or df.empty or len(df) < 35:
                logger.warning("Insufficient klines data")
                return

            closed_df = self._closed_candle_view(df)
            if len(closed_df) < 35:
                logger.debug("Waiting for full indicator warmup on closed candles")
                return

            if self._handle_stale_data(closed_df, self.interval_delta, label="LTF"):
                return

            closed_htf = None
            if self.config.useMultiTfAtrStrategy:
                if htf_df is None or htf_df.empty or len(htf_df) < 200:
                    logger.warning("Insufficient HTF klines data for trend filter")
                    return
                closed_htf = self._closed_candle_view(htf_df, delta=htf_interval_delta)
                if closed_htf is not None and self._handle_stale_data(
                    closed_htf, htf_interval_delta, label="HTF"
                ):
                    return

            last_closed_time = closed_df.index[-1]
            if self.last_candle_time == last_closed_time:
                return

            if self.config.useMultiTfAtrStrategy:
                signals = compute_signals_multi_tf(
                    closed_df,
                    closed_htf,
                    config=self.config,
                )
            else:
                signals = compute_signals(closed_df)

            self.last_candle_time = last_closed_time

            if self.config.useMultiTfAtrStrategy and self.current_position_qty > 0:
                if await self._manage_open_position_strategy(closed_df, signals):
                    return
                if self.current_position_qty > 0:
                    logger.info("Already in position, skipping entry")
                    return

            if not signals["long_signal"]:
                if (
                    not self.config.useMultiTfAtrStrategy
                    and self.config.earlyExitOnCross
                    and self.current_position_qty > 0
                ):
                    await self._check_early_exit(signals)
                return

            if self.current_position_qty > 0:
                logger.info("Already in position, skipping entry")
                return

            if self.config.useMultiTfAtrStrategy:
                entry_price = signals.get("entry_price")
                stop_price = signals.get("stop_price")
                tp_price = signals.get("tp2_price")

                if entry_price is None or pd.isna(entry_price):
                    logger.debug("Entry price unavailable; skipping entry")
                    return

                stop_loss_pct = None
                if stop_price and entry_price:
                    stop_loss_pct = (entry_price - stop_price) / entry_price

                risk_pct = self.config.riskPct
                atr_pct = signals.get("atr_pct")
                if (
                    self.config.atrRiskScaling
                    and isinstance(atr_pct, (float, int))
                    and atr_pct > self.config.atrRiskScalingThreshold
                ):
                    risk_pct *= self.config.atrRiskScalingFactor

                await self._enter_long(
                    float(entry_price),
                    stop_price=float(stop_price) if stop_price else None,
                    take_profit_price=float(tp_price) if tp_price else None,
                    stop_loss_pct=stop_loss_pct,
                    risk_pct=risk_pct,
                    entry_bar_time=last_closed_time.to_pydatetime(),
                )
            else:
                await self._enter_long(
                    signals["price"],
                    stop_price=signals["price"] * (1 - self.config.stopLossPct),
                    take_profit_price=signals["price"]
                    * (1 + self.config.takeProfitPct),
                    stop_loss_pct=self.config.stopLossPct,
                    risk_pct=self.config.riskPct,
                    entry_bar_time=last_closed_time.to_pydatetime(),
                )

        except ZoomexError as e:
            logger.error("Zoomex API error: %s", e)
            await self.alert_sink.send_alert(
                "runtime_error",
                f"Zoomex API error: {e}",
                {"symbol": self.config.symbol},
            )
        except Exception as e:
            logger.error("Perps cycle error: %s", e, exc_info=True)
            await self.alert_sink.send_alert(
                "runtime_error",
                f"Perps cycle error: {e}",
                {"symbol": self.config.symbol},
            )

    async def _check_early_exit(self, signals: dict):
        if (
            signals.get("prev_fast", 0) > signals.get("prev_slow", 0)
            and signals["fast"] < signals["slow"]
        ):
            logger.info(
                "Bear cross detected, initiating reduce-only exit for %s qty=%.6f",
                self.config.symbol,
                self.current_position_qty,
            )
            order_link_id = generate_order_id(
                symbol=self.config.symbol,
                side="Sell",
                timestamp=datetime.now(timezone.utc),
            )
            await early_exit_reduce_only(
                self.exchange,
                symbol=self.config.symbol,
                qty=self.current_position_qty,
                position_idx=self.config.positionIdx,
                order_link_id=order_link_id,
            )
            self.current_position_qty = 0.0
            self.entry_bar_time = None
            if self.risk_manager:
                self.risk_manager.register_close_position(self.config.symbol, 0.0)

    async def _manage_open_position_strategy(
        self, ltf_df: pd.DataFrame, signals: dict
    ) -> bool:
        """Strategy-level exits that sit above the safety harness."""
        if self.current_position_qty <= 0:
            return False

        exit_reason: Optional[str] = None

        if self.config.exitOnTrendFlip and not signals.get("htf_trend_up", False):
            exit_reason = "trend_filter_flip"

        bars_in_trade = 0
        if self.entry_bar_time:
            bars_in_trade = int((ltf_df.index > self.entry_bar_time).sum())
            if not exit_reason and bars_in_trade >= self.config.maxBarsInTrade:
                exit_reason = "max_bars_in_trade"

        if exit_reason:
            logger.info(
                "Strategy-managed exit (%s) for %s qty=%.6f after %d bars",
                exit_reason,
                self.config.symbol,
                self.current_position_qty,
                bars_in_trade,
            )
            order_link_id = generate_order_id(
                symbol=self.config.symbol,
                side="Sell",
                timestamp=datetime.now(timezone.utc),
            )
            await early_exit_reduce_only(
                self.exchange,
                symbol=self.config.symbol,
                qty=self.current_position_qty,
                position_idx=self.config.positionIdx,
                order_link_id=order_link_id,
            )
            self.current_position_qty = 0.0
            self.entry_bar_time = None
            if self.risk_manager:
                self.risk_manager.register_close_position(self.config.symbol, 0.0)
            await self.alert_sink.send_alert(
                "strategy_exit",
                f"Exited position due to {exit_reason}",
                {"symbol": self.config.symbol, "bars_in_trade": bars_in_trade},
            )
            return True

        return False

    async def halt(self) -> None:
        """Emergency halt: Cancel all orders and close positions."""
        logger.warning("EMERGENCY HALT TRIGGERED")
        if not self.exchange:
            return

        # 1. Cancel all open orders
        try:
            await self.exchange.cancel_all_orders(self.config.symbol)
            logger.info("Cancelled all open orders for %s", self.config.symbol)
        except Exception as e:
            logger.error("Failed to cancel orders during halt: %s", e)

        # 2. Close position if exists
        if self.current_position_qty > 0:
            try:
                order_link_id = generate_order_id(
                    symbol=self.config.symbol,
                    side="Sell",
                    timestamp=datetime.now(timezone.utc),
                )
                await early_exit_reduce_only(
                    self.exchange,
                    symbol=self.config.symbol,
                    qty=self.current_position_qty,
                    position_idx=self.config.positionIdx,
                    order_link_id=order_link_id,
                )
                logger.info(
                    "Submitted reduce-only exit for %s qty=%.6f",
                    self.config.symbol,
                    self.current_position_qty,
                )
            except Exception as e:
                logger.error("Failed to close position during halt: %s", e)

        # 3. Reset state
        self.current_position_qty = 0.0
        self.entry_bar_time = None
        self.reconciliation_block_active = True  # Block new entries until manual reset

        await self.alert_sink.send_alert(
            "emergency_halt",
            "Bot halted. Orders cancelled and positions closed.",
            {"symbol": self.config.symbol},
        )

    def _resolve_interval_delta(self, interval: str) -> timedelta:
        try:
            minutes = max(int(interval), 1)
        except ValueError:
            minutes = 5
            logger.warning(
                "Invalid perps interval '%s', defaulting to 5 minutes", interval
            )
        return timedelta(minutes=minutes)

    def _closed_candle_view(
        self, df: pd.DataFrame, delta: Optional[timedelta] = None
    ) -> pd.DataFrame:
        if df.empty:
            return df
        now = datetime.now(timezone.utc)
        last_start = df.index[-1]
        interval_delta = delta or self.interval_delta
        if now < last_start + interval_delta and len(df) > 1:
            return df.iloc[:-1]
        return df

    def _handle_stale_data(
        self, df: pd.DataFrame, interval_delta: Optional[timedelta], *, label: str
    ) -> bool:
        if df.empty:
            return False
        interval = interval_delta or self.interval_delta
        last_ts = df.index[-1]
        now = datetime.now(timezone.utc)
        staleness = (now - last_ts).total_seconds()
        if staleness > self.config.maxDataStalenessSeconds:
            self.data_stale_block_active = True
            logger.warning(
                "SAFETY_STALE_DATA: %s candle stale by %.0fs (limit=%ss)",
                label,
                staleness,
                self.config.maxDataStalenessSeconds,
            )
            asyncio.create_task(
                self.alert_sink.send_alert(
                    "critical_stale_data",
                    f"{label} candle stale by {staleness:.0f}s",
                    {"symbol": self.config.symbol, "staleness_s": staleness},
                )
            )
            return True

        if len(df) >= 2:
            gap = (df.index[-1] - df.index[-2]).total_seconds()
            max_gap = interval.total_seconds() * self.config.maxDataGapMultiplier
            if gap > max_gap:
                self.data_stale_block_active = True
                logger.warning(
                    "SAFETY_DATA_GAP: %s candle gap %.0fs exceeds limit %.0fs",
                    label,
                    gap,
                    max_gap,
                )
                asyncio.create_task(
                    self.alert_sink.send_alert(
                        "critical_stale_data_gap",
                        f"{label} candle gap {gap:.0f}s exceeds {max_gap:.0f}s",
                        {"symbol": self.config.symbol, "gap_s": gap},
                    )
                )
                return True

        self.data_stale_block_active = False
        return False

    async def _sync_time_or_halt(self, periodic: bool = False) -> None:
        if not hasattr(self.exchange, "sync_time"):
            return
        now = datetime.now(timezone.utc)
        if periodic and self._last_time_sync_at:
            elapsed = (now - self._last_time_sync_at).total_seconds()
            if elapsed < self.config.timeSyncIntervalSeconds:
                return
        offset_ms = await self.exchange.sync_time()
        self._last_time_sync_at = now
        if abs(offset_ms) > self.config.timeSyncMaxSkewMs:
            self.reconciliation_block_active = True
            logger.error(
                "SAFETY_TIME_DRIFT: Offset %dms exceeds limit %dms; halting entries",
                offset_ms,
                self.config.timeSyncMaxSkewMs,
            )
            await self.alert_sink.send_alert(
                "critical_time_drift",
                "Server time drift exceeded limit; trading halted.",
                {
                    "symbol": self.config.symbol,
                    "offset_ms": offset_ms,
                    "limit_ms": self.config.timeSyncMaxSkewMs,
                },
            )
            raise ZoomexError("Time drift exceeded maximum threshold")

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_timestamp_value(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return None
        if isinstance(value, (int, float)):
            divisor = 1000 if value > 1e12 else 1
            return datetime.fromtimestamp(value / divisor, tz=timezone.utc)
        return None

    def _build_trade_log_entry(
        self, trade: Dict[str, Any], trade_time: datetime, pnl: float
    ) -> Dict[str, Any]:
        qty = self._safe_float(
            trade.get("qty") or trade.get("size") or trade.get("closedSize")
        )
        if qty is None:
            qty = self.last_entry_qty

        entry_price = self._safe_float(
            trade.get("avgEntryPrice") or trade.get("orderPrice")
        )
        if entry_price is None:
            entry_price = self.last_entry_price

        exit_price = self._safe_float(trade.get("avgExitPrice") or trade.get("price"))

        notional = self._safe_float(trade.get("cumEntryValue"))
        if notional is None and entry_price is not None and qty is not None:
            notional = entry_price * abs(qty)
        if (
            notional is None
            and self.last_entry_price is not None
            and self.last_entry_qty is not None
        ):
            notional = self.last_entry_price * abs(self.last_entry_qty)

        realized_pnl_pct: Optional[float] = None
        if notional is not None and notional != 0:
            realized_pnl_pct = pnl / notional

        timestamp_open = (
            self._parse_timestamp_value(trade.get("entryTime"))
            or self._parse_timestamp_value(trade.get("startTime"))
            or self.last_entry_time
            or trade_time
        )

        fees = self._safe_float(trade.get("fees") or trade.get("fee") or 0.0) or 0.0
        side = trade.get("side") or trade.get("positionSide") or ""

        return {
            "timestamp_open": timestamp_open,
            "timestamp_close": trade_time,
            "symbol": trade.get("symbol", self.config.symbol),
            "side": side.upper() if isinstance(side, str) else side,
            "size": qty,
            "notional": notional,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl": pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "fees": fees,
            "config_id": self.config_id or "",
            "strategy_name": self.strategy_name,
            "account_equity_before": self.entry_equity,
            "account_equity_after": self.equity_usdt,
            "risk_blocked_before_entry": self.last_risk_blocked,
            "extra": trade,
        }

    async def _refresh_account_state(self) -> None:
        balance = None
        if hasattr(self.exchange, "get_account_balance"):
            balance = await self.exchange.get_account_balance()
        elif hasattr(self.exchange, "get_wallet_balance"):
            balance = await self.exchange.get_wallet_balance()
        elif hasattr(self.exchange, "get_balance"):
            balance = await self.exchange.get_balance()
        if balance:
            # Assuming balance structure matches what we expect or we need to adapt it
            # ExchangeClient.get_account_balance returns a dict, likely from CCXT or PaperBroker
            # We need to extract equity.
            # For now, let's assume it returns a standard structure or adapt.
            # Actually, ExchangeClient wraps this.
            # But wait, ExchangeClient.get_account_balance returns raw dict from CCXT/Paper.
            # We should probably add a helper in ExchangeClient or parse it here.
            # PaperBroker returns {'equity': ...}
            # CCXT returns standard structure.

            # Let's try to get equity safely
            # Try to get equity safely
            if "totalMarginBalance" in balance:
                self.equity_usdt = float(balance["totalMarginBalance"])
            elif "totalWalletBalance" in balance:
                self.equity_usdt = float(balance["totalWalletBalance"])
            elif "equity" in balance:
                self.equity_usdt = float(balance["equity"])
            elif "total" in balance:
                self.equity_usdt = float(balance.get("total", {}).get("USDT", 0.0))
            else:
                self.equity_usdt = 0.0

        positions = await self.exchange.get_positions(symbols=[self.config.symbol])
        if positions:
            self.current_position_qty = positions[0].size
        else:
            self.current_position_qty = 0.0

        if self.risk_manager:
            self.risk_manager.update_equity(self.equity_usdt)

    async def _enter_long(
        self,
        price: float,
        *,
        stop_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        risk_pct: Optional[float] = None,
        entry_bar_time: Optional[datetime] = None,
    ):
        self.last_risk_blocked = None
        if self.equity_usdt <= 0:
            logger.warning("Wallet equity unavailable; skipping entry")
            return

        if self.symbol_health_store and self.symbol_health_store.is_blocked(
            self.config.symbol
        ):
            state = self.symbol_health_store.get_symbol_state(self.config.symbol)
            reasons = ", ".join(state.get("last_reasons", [])) or "unspecified"
            logger.warning(
                "RUNTIME_HEALTH_BLOCK: Blocked new entry for %s until %s (status=%s reasons=%s)",
                self.config.symbol,
                state.get("blocked_until"),
                state.get("last_status"),
                reasons,
            )
            return

        margin_info = await self.exchange.get_margin_info(
            symbol=self.config.symbol,
            position_idx=self.config.positionIdx,
        )
        margin_ratio = margin_info.get("marginRatio", 0.0)
        if not margin_info.get("found", True):
            logger.warning(
                "Margin info missing for %s positionIdx=%s; proceeding with ratio=0",
                self.config.symbol,
                self.config.positionIdx,
            )

        if margin_ratio > self.config.maxMarginRatio:
            logger.warning(
                "SAFETY_MARGIN_BLOCK: Margin ratio %.2f%% exceeds limit %.2f%%, skipping entry",
                margin_ratio * 100,
                self.config.maxMarginRatio * 100,
            )
            return

        if not self.leverage_set:
            await self.exchange.set_leverage(
                symbol=self.config.symbol,
                buy=self.config.leverage,
                sell=self.config.leverage,
            )
            self.leverage_set = True
            logger.info("Leverage set to %dx", self.config.leverage)

        precision = await self.exchange.get_precision(self.config.symbol)

        if stop_loss_pct is None or stop_loss_pct <= 0:
            if stop_price and price > 0:
                stop_loss_pct = max((price - stop_price) / price, 0)
            if not stop_loss_pct:
                stop_loss_pct = self.config.stopLossPct
        risk_pct = risk_pct if risk_pct is not None else self.config.riskPct
        effective_stop_price = stop_price if stop_price else price * (1 - stop_loss_pct)

        qty = risk_position_size(
            equity_usdt=self.equity_usdt,
            risk_pct=risk_pct,
            stop_loss_pct=stop_loss_pct,
            price=price,
            cash_cap=self.config.cashDeployCap,
        )

        logger.info(
            "Position sizing: equity=$%.2f risk=%.2f%% stop_loss=%.2f%% price=%.4f => qty=%.6f",
            self.equity_usdt,
            risk_pct * 100,
            stop_loss_pct * 100,
            price,
            qty,
        )

        if self.symbol_health_store:
            multiplier = self.symbol_health_store.get_effective_size_multiplier(
                self.config.symbol, warning_size_multiplier=self.warning_size_multiplier
            )
            if multiplier <= 0:
                state = self.symbol_health_store.get_symbol_state(self.config.symbol)
                reasons = ", ".join(state.get("last_reasons", [])) or "unspecified"
                logger.warning(
                    "RUNTIME_HEALTH_BLOCK: Effective size multiplier blocked entry for %s "
                    "(status=%s reasons=%s)",
                    self.config.symbol,
                    state.get("last_status"),
                    reasons,
                )
                return
            adjusted_qty = qty * multiplier
            if multiplier != 1.0:
                logger.info(
                    "Runtime health multiplier applied: base_qty=%.6f multiplier=%.2f -> qty=%.6f (status=%s)",
                    qty,
                    multiplier,
                    adjusted_qty,
                    self.symbol_health_store.get_symbol_state(self.config.symbol).get(
                        "last_status"
                    ),
                )
            qty = adjusted_qty

        rounded_qty = round_quantity(qty, precision)
        if rounded_qty is None:
            logger.warning(
                "Quantity %.6f below minimum %.6f for %s",
                qty,
                precision.min_qty,
                self.config.symbol,
            )
            return

        proposed_notional = price * rounded_qty
        proposed_risk_value = RiskManager._risk_value(proposed_notional, risk_pct)
        if self.risk_manager:
            allowed, reason = self.risk_manager.can_open_new_position(
                self.config.symbol, proposed_notional, risk_pct
            )
            if not allowed:
                equity = self.risk_manager.current_equity or self.equity_usdt
                open_limit = equity * self.risk_manager.max_open_risk_pct
                symbol_limit = equity * self.risk_manager.max_symbol_risk_pct
                symbol_open = self.risk_manager.open_risk_by_symbol.get(
                    self.config.symbol.upper(), 0.0
                )
                logger.warning(
                    "RISK_BLOCK: Blocked long entry for %s (reason=%s | proposed_risk=$%.2f "
                    "open_risk=$%.2f limit=$%.2f symbol_risk=$%.2f symbol_limit=$%.2f "
                    "realized_pnl=$%.2f)",
                    self.config.symbol,
                    reason,
                    proposed_risk_value,
                    self.risk_manager.total_open_risk,
                    open_limit,
                    symbol_open,
                    symbol_limit,
                    self.risk_manager.realized_pnl,
                )
                self.last_risk_blocked = True
                return

        tp_price = (
            take_profit_price
            if take_profit_price
            else price * (1 + self.config.takeProfitPct)
        )
        sl_price = effective_stop_price
        risk_reward = (
            (tp_price - price) / (price - sl_price) if price != sl_price else 0
        )

        logger.info(
            "Entry plan: qty=%.6f entry=%.4f tp=%.4f sl=%.4f R:R=%.2f",
            rounded_qty,
            price,
            tp_price,
            sl_price,
            risk_reward,
        )

        entry_timestamp = datetime.now(timezone.utc)
        order_link_id = generate_order_id(
            symbol=self.config.symbol,
            side="Buy",
            timestamp=entry_timestamp,
        )

        if self.intent_ledger:
            idempotency_key = self.intent_ledger.build_idempotency_key(
                {
                    "symbol": self.config.symbol,
                    "side": "buy",
                    "order_type": "market",
                    "quantity": round(rounded_qty, 8),
                    "price": round(price, 8),
                    "stop_price": round(sl_price, 8),
                    "take_profit": round(tp_price, 8),
                    "order_link_id": order_link_id,
                    "timestamp": entry_timestamp.isoformat(),
                }
            )
            intent, created = await self.intent_ledger.get_or_create_intent(
                idempotency_key=idempotency_key,
                client_id=order_link_id,
                symbol=self.config.symbol,
                side="buy",
                order_type="market",
                quantity=rounded_qty,
                price=price,
                stop_price=sl_price,
                reduce_only=False,
            )
            if not created and not OrderIntentLedger.is_terminal(intent.status):
                logger.warning(
                    "Order intent already exists (%s); skipping duplicate submit",
                    intent.idempotency_key,
                )
                await self._reconcile_open_orders(reason="duplicate_intent")
                return
        elif self.mode_name == "live":
            logger.error(
                "SAFETY_RECON_BLOCK: Order intent ledger missing for live trading."
            )
            self.reconciliation_block_active = True
            return

        result = await enter_long_with_brackets(
            self.exchange,
            symbol=self.config.symbol,
            qty=rounded_qty,
            take_profit=tp_price,
            stop_loss=sl_price,
            position_idx=self.config.positionIdx,
            trigger_by=self.config.triggerBy,
            order_link_id=order_link_id,
        )

        if self.intent_ledger and isinstance(result, dict):
            order_id = result.get("orderId") or result.get("order_id")
            await self.intent_ledger.update_intent_status(
                intent,
                status="acked",
                order_id=order_id,
            )

        self.current_position_qty = rounded_qty
        self.entry_equity = self.equity_usdt
        self.last_entry_time = entry_timestamp
        self.last_entry_price = price
        self.last_entry_qty = rounded_qty
        self.last_risk_blocked = False
        self.session_trades += 1
        self.entry_bar_time = entry_bar_time
        logger.info(
            "Order placed: %s (order_link_id=%s)",
            result.get("orderId", "N/A"),
            order_link_id,
        )
        if self.risk_manager:
            self.risk_manager.register_open_position(
                self.config.symbol, proposed_notional, risk_pct
            )
        await self._refresh_account_state()

    async def _reconcile_positions(self) -> None:
        if not self.exchange:
            return

        try:
            positions_data: Any = await self.exchange.get_positions(
                symbols=[self.config.symbol]
            )
            if isinstance(positions_data, dict):
                positions = positions_data.get("list") or []
            else:
                positions = positions_data or []

            if not positions:
                logger.info("No existing positions found for %s", self.config.symbol)
                return

            selected = None
            for pos in positions:
                pos_idx = (
                    pos.get("positionIdx")
                    if isinstance(pos, dict)
                    else getattr(pos, "positionIdx", None)
                )
                if pos_idx is not None and pos_idx != self.config.positionIdx:
                    continue

                side_value = (
                    (pos.get("side") or pos.get("positionSide") or "")
                    if isinstance(pos, dict)
                    else (getattr(pos, "side", "") or "")
                )
                side_norm = str(side_value).lower()
                if self.config.positionIdx == 1 and side_norm not in ("buy", "long"):
                    continue
                if self.config.positionIdx == 2 and side_norm not in ("sell", "short"):
                    continue

                size_value = (
                    pos.get("size", "0")
                    if isinstance(pos, dict)
                    else getattr(pos, "size", 0.0)
                )
                size = abs(float(size_value or 0.0))
                if size <= 0:
                    continue

                selected = pos
                break

            if selected is None:
                logger.info(
                    "No open position found for %s during reconciliation",
                    self.config.symbol,
                )
                return

            self.current_position_qty = size
            entry_price = (
                float(selected.get("avgPrice", "0"))
                if isinstance(selected, dict)
                else float(selected.entry_price)
            )
            unrealized_pnl = (
                float(selected.get("unrealisedPnl", "0"))
                if isinstance(selected, dict)
                else float(selected.unrealized_pnl)
            )
            side = (
                str(selected.get("side") or selected.get("positionSide") or "UNKNOWN")
                if isinstance(selected, dict)
                else str(selected.side or "UNKNOWN")
            )

            logger.warning(
                "SAFETY_RECON_ADOPT: Adopted existing position for %s | "
                "Qty=%.6f | Entry=$%.4f | Unrealized PnL=$%.2f | Side=%s",
                self.config.symbol,
                size,
                entry_price,
                unrealized_pnl,
                side,
            )
            logger.warning(
                "SAFETY_RECON_ADOPT: Existing open position detected on startup; PnL tracking may be inaccurate "
                "until the exchange position is closed."
            )
            if self.risk_manager:
                adopted_notional = entry_price * size if entry_price else size
                self.risk_manager.register_open_position(
                    self.config.symbol, adopted_notional, self.config.riskPct
                )
                self.risk_manager.update_equity(self.equity_usdt)
            normalized_side = side.lower()
            if normalized_side in ("sell", "short"):
                self.reconciliation_block_active = True
                logger.warning(
                    "SAFETY_RECON_BLOCK: Reconciliation guard activated due to %s exposure. "
                    "New entries will be blocked until manual intervention.",
                    side,
                )
                await self.alert_sink.send_alert(
                    "safety_reconciliation",
                    f"Exchange reported {side} exposure; guard enabled.",
                    {
                        "symbol": self.config.symbol,
                        "exposure_side": side,
                        "quantity": size,
                    },
                )
            return
        except Exception as e:
            logger.error("Position reconciliation failed: %s", e, exc_info=True)

    async def _reconcile_open_orders(self, *, reason: str) -> None:
        if not hasattr(self.exchange, "get_open_orders"):
            return
        now = datetime.now(timezone.utc)
        if reason == "periodic" and self._last_reconcile_at:
            elapsed = (now - self._last_reconcile_at).total_seconds()
            if elapsed < 30:
                return
        self._last_reconcile_at = now
        try:
            response = await self.exchange.get_open_orders(self.config.symbol)
            open_orders = response.get("list", []) if isinstance(response, dict) else []
            if not open_orders:
                return

            if not self.intent_ledger or not self.database:
                self.reconciliation_block_active = True
                logger.error(
                    "SAFETY_RECON_BLOCK: Open orders detected but intent ledger unavailable."
                )
                await self.alert_sink.send_alert(
                    "critical_reconciliation",
                    "Open orders found but no intent ledger configured.",
                    {"symbol": self.config.symbol, "reason": reason},
                )
                return

            intents = await self.database.list_open_order_intents(
                self.intent_ledger.mode, self.intent_ledger.run_id
            )
            intents_by_client = {intent.client_id: intent for intent in intents}
            unknown_orders = []

            for order in open_orders:
                client_id = (
                    order.get("orderLinkId")
                    or order.get("clientOrderId")
                    or order.get("client_id")
                )
                order_id = order.get("orderId") or order.get("order_id")
                if not client_id or client_id not in intents_by_client:
                    unknown_orders.append(order_id or client_id or "unknown")
                    continue
                intent = intents_by_client[client_id]
                await self.intent_ledger.update_intent_status(
                    intent, status="acked", order_id=order_id
                )

            if unknown_orders:
                self.reconciliation_block_active = True
                logger.error(
                    "SAFETY_RECON_BLOCK: Unknown open orders detected: %s",
                    ", ".join(unknown_orders),
                )
                await self.alert_sink.send_alert(
                    "critical_reconciliation",
                    "Unknown open orders detected; trading halted.",
                    {"symbol": self.config.symbol, "orders": unknown_orders},
                )

            if hasattr(self.exchange, "get_fills"):
                fills_resp = await self.exchange.get_fills(self.config.symbol)
                fills = fills_resp.get("list", []) if isinstance(fills_resp, dict) else []
                fill_agg: Dict[str, Dict[str, float]] = {}
                for fill in fills:
                    client_id = fill.get("orderLinkId") or fill.get("clientOrderId")
                    if not client_id or client_id not in intents_by_client:
                        continue
                    intent = intents_by_client[client_id]
                    trade_id = str(fill.get("execId") or fill.get("tradeId") or "")
                    if not trade_id:
                        continue
                    qty = float(fill.get("execQty") or fill.get("qty") or 0.0)
                    price = float(fill.get("execPrice") or fill.get("price") or 0.0)
                    side = str(fill.get("side") or intent.side)
                    agg = fill_agg.setdefault(
                        intent.idempotency_key, {"qty": 0.0, "cost": 0.0}
                    )
                    agg["qty"] += qty
                    agg["cost"] += qty * price
                    await self.intent_ledger.record_fill(
                        intent=intent,
                        trade_id=trade_id,
                        order_id=str(fill.get("orderId") or intent.order_id or ""),
                        symbol=str(fill.get("symbol") or self.config.symbol),
                        side=side,
                        quantity=qty,
                        price=price,
                        fee=float(fill.get("execFee") or 0.0),
                        timestamp=self._parse_timestamp_value(fill.get("execTime")),
                    )
                for key, agg in fill_agg.items():
                    intent = next(
                        (intent for intent in intents_by_client.values() if intent.idempotency_key == key),
                        None,
                    )
                    if not intent:
                        continue
                    prev_filled = float(intent.filled_qty or 0.0)
                    new_filled = float(agg["qty"])
                    delta = new_filled - prev_filled
                    avg_price = agg["cost"] / agg["qty"] if agg["qty"] else None
                    status = (
                        "filled"
                        if agg["qty"] >= intent.quantity
                        else "partially_filled"
                    )
                    await self.intent_ledger.update_intent_status(
                        intent,
                        status=status,
                        filled_qty=agg["qty"],
                        avg_fill_price=avg_price,
                    )
                    if delta > 0 and avg_price:
                        await self._apply_fill_delta(
                            intent=intent,
                            filled_delta=delta,
                            avg_price=avg_price,
                        )
        except Exception as exc:
            logger.error("Order reconciliation failed: %s", exc, exc_info=True)

    async def _apply_fill_delta(
        self, *, intent: OrderIntent, filled_delta: float, avg_price: float
    ) -> None:
        if filled_delta <= 0:
            return
        if intent.reduce_only:
            self.current_position_qty = max(
                self.current_position_qty - filled_delta, 0.0
            )
            if self.risk_manager:
                self.risk_manager.adjust_open_position(
                    self.config.symbol,
                    -(filled_delta * avg_price),
                    self.config.riskPct,
                )
            return

        self.current_position_qty += filled_delta
        if self.risk_manager:
            self.risk_manager.adjust_open_position(
                self.config.symbol,
                filled_delta * avg_price,
                self.config.riskPct,
            )

    async def _check_risk_limits(self) -> bool:
        if self.reconciliation_block_active:
            logger.warning(
                "SAFETY_RECON_BLOCK: Reconciliation guard active; refusing new entries until the "
                "existing exchange position is resolved."
            )
            return False

        if self.data_stale_block_active:
            logger.warning(
                "SAFETY_STALE_DATA: Market data stale; refusing new entries."
            )
            return False

        if (
            self.config.consecutiveLossLimit
            and self.pnl_tracker.consecutive_losses >= self.config.consecutiveLossLimit
        ):
            logger.warning(
                "SAFETY_CIRCUIT_BREAKER: %d consecutive losses (limit=%d)",
                self.pnl_tracker.consecutive_losses,
                self.config.consecutiveLossLimit,
            )
            await self.alert_sink.send_alert(
                "safety_circuit_breaker",
                f"{self.pnl_tracker.consecutive_losses} consecutive losses (limit={self.config.consecutiveLossLimit}).",
                {
                    "symbol": self.config.symbol,
                    "equity": self.equity_usdt,
                },
            )
            return False

        daily_pnl = self.pnl_tracker.get_daily_pnl()
        if self.equity_usdt > 0:
            daily_loss_pct = abs(daily_pnl) / self.equity_usdt if daily_pnl < 0 else 0.0

            if daily_loss_pct > self.max_daily_loss_pct:
                logger.warning(
                    "SAFETY_DAILY_LOSS: Daily loss limit exceeded: %.2f%% (limit=%.2f%%)",
                    daily_loss_pct * 100,
                    self.max_daily_loss_pct * 100,
                )
                await self.alert_sink.send_alert(
                    "safety_daily_loss",
                    f"Daily loss {daily_loss_pct * 100:.2f}% exceeded limit {self.max_daily_loss_pct * 100:.2f}%.",
                    {
                        "symbol": self.config.symbol,
                        "equity": self.equity_usdt,
                    },
                )
                return False

        if self.pnl_tracker.peak_equity > 0:
            drawdown = self.pnl_tracker.get_drawdown(self.equity_usdt)

            if drawdown > self.drawdown_threshold:
                logger.warning(
                    "SAFETY_DRAWDOWN: Drawdown limit exceeded: %.2f%% (limit=%.2f%%)",
                    drawdown * 100,
                    self.drawdown_threshold * 100,
                )
                await self.alert_sink.send_alert(
                    "safety_drawdown",
                    f"Drawdown {drawdown * 100:.2f}% exceeded limit {self.drawdown_threshold * 100:.2f}%.",
                    {
                        "symbol": self.config.symbol,
                        "equity": self.equity_usdt,
                    },
                )
                return False

        return True

    def _load_persisted_state(self) -> None:
        state = load_perps_state(self.state_path)
        if not state:
            logger.info(
                "No existing perps state found at %s; starting fresh risk counters.",
                self.state_path,
            )
            return
        self.pnl_tracker.load_state(state)
        logger.info(
            "SAFETY_STATE_LOAD: Restored risk state peak_equity=$%.2f consecutive_losses=%d",
            state.peak_equity,
            state.consecutive_losses,
        )

    def _persist_state(self) -> None:
        try:
            save_perps_state(self.state_path, self.pnl_tracker.to_state())
        except Exception as exc:
            logger.warning("Failed to persist perps state: %s", exc)

    async def _check_session_limits(self) -> bool:
        if not self.session_start_time:
            return True

        if self.config.sessionMaxRuntimeMinutes:
            elapsed_minutes = (
                datetime.now(timezone.utc) - self.session_start_time
            ).total_seconds() / 60.0
            if elapsed_minutes > self.config.sessionMaxRuntimeMinutes:
                logger.warning(
                    "SAFETY_SESSION_RUNTIME: Session runtime %.1f minutes exceeded limit=%d; "
                    "halting new entries for this run.",
                    elapsed_minutes,
                    self.config.sessionMaxRuntimeMinutes,
                )
                await self.alert_sink.send_alert(
                    "safety_session_runtime",
                    f"Runtime {elapsed_minutes:.1f}m exceeded limit {self.config.sessionMaxRuntimeMinutes}m.",
                    {"symbol": self.config.symbol},
                )
                return False

        if (
            self.config.sessionMaxTrades is not None
            and self.session_trades >= self.config.sessionMaxTrades
        ):
            logger.warning(
                "SAFETY_SESSION_TRADES: Session trades=%d reached limit=%d; "
                "halting new entries for this run.",
                self.session_trades,
                self.config.sessionMaxTrades,
            )
            await self.alert_sink.send_alert(
                "safety_session_trades",
                f"Trades {self.session_trades} reached session limit {self.config.sessionMaxTrades}.",
                {"symbol": self.config.symbol},
            )
            return False

        return True

    async def _check_position_pnl(self) -> None:
        if not self.exchange:
            return

        now = datetime.now(timezone.utc)
        if (
            self.last_position_check_time
            and (now - self.last_position_check_time).total_seconds() < 300
        ):
            return

        try:
            start_time = int((now - timedelta(hours=24)).timestamp() * 1000)
            closed_pnl_data = await self.exchange.get_closed_pnl(
                symbol=self.config.symbol,
                start_time=start_time,
                limit=10,
            )

            trades: Any = closed_pnl_data
            if isinstance(trades, dict):
                trades = trades.get("list") or []

            for trade in trades:
                pnl = (
                    self._safe_float(
                        trade.get("closedPnl")
                        or trade.get("pnl")
                        or trade.get("profit")
                    )
                    or 0.0
                )
                trade_time = self._parse_timestamp_value(
                    trade.get("createdTime")
                    or trade.get("timestamp")
                    or trade.get("time")
                )
                if not trade_time:
                    logger.debug(
                        "Skipping closed PnL row with missing timestamp: %s", trade
                    )
                    continue

                already_recorded = any(
                    t["timestamp"] == trade_time for t in self.pnl_tracker.trade_history
                )

                if not already_recorded:
                    self.pnl_tracker.record_trade(pnl, trade_time)
                    if self.risk_manager:
                        self.risk_manager.register_close_position(
                            self.config.symbol, pnl
                        )
                        self.risk_manager.update_equity(self.equity_usdt)
                    if self.trade_logger:
                        trade_info = self._build_trade_log_entry(trade, trade_time, pnl)
                        self.trade_logger.log_completed_trade(trade_info)
                        self.last_entry_time = None
                        self.last_entry_price = None
                        self.last_entry_qty = None
                        self.entry_equity = None
                        self.last_risk_blocked = None
                    self._persist_state()

            if self.pnl_tracker.update_peak_equity(self.equity_usdt):
                self._persist_state()

        except Exception as e:
            logger.error("Failed to check position PnL: %s", e)
        finally:
            self.last_position_check_time = now
