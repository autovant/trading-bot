#!/usr/bin/env python3
"""
Backtesting engine for the multi-timeframe ATR perps strategy.

Supports both the legacy single-timeframe signals and the new HTF/LTF ATR
trend/pullback logic. Execution is simplified but includes fees, slippage,
partial profit taking at TP1, and breakeven stops.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import aiohttp
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config, PerpsConfig
from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.strategies.perps_trend_vwap import compute_signals
from src.strategies.perps_trend_atr_multi_tf import compute_signals_multi_tf
from src.engine.perps_executor import risk_position_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class PerpsBacktest:
    def __init__(
        self,
        config: PerpsConfig,
        *,
        initial_balance: float = 1000.0,
        use_multi_tf: Optional[bool] = None,
    ):
        self.config = config
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.position_qty = 0.0
        self.position_entry = 0.0
        self.position_side: Optional[str] = None
        self.active_trade: Optional[Dict[str, Any]] = None
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.consecutive_losses = 0
        self.max_consecutive_losses = 0
        self.tp1_hits = 0
        self.tp2_hits = 0
        self.r_multiples: List[float] = []
        self.trade_durations: List[int] = []
        self.fee_rate = 0.0006  # 0.06% taker fee
        self.slippage_rate = 0.0003  # 0.03% slippage
        self.use_multi_tf = (
            config.useMultiTfAtrStrategy if use_multi_tf is None else use_multi_tf
        )

    def simulate_fill(self, price: float, is_entry: bool = True) -> float:
        slippage = price * self.slippage_rate
        return price + slippage if is_entry else price - slippage

    def calculate_fees(self, notional: float) -> float:
        return notional * self.fee_rate

    def mark_equity(self, mark_price: float) -> None:
        if self.position_qty > 0:
            unrealized = (mark_price - self.position_entry) * self.position_qty
            self.equity = self.balance + unrealized
        else:
            self.equity = self.balance

    def open_position(self, signals: Dict[str, Any], timestamp: pd.Timestamp) -> None:
        if self.position_qty > 0:
            return

        if (
            self.config.consecutiveLossLimit
            and self.consecutive_losses >= self.config.consecutiveLossLimit
        ):
            logger.warning(
                "Circuit breaker active: %d consecutive losses",
                self.consecutive_losses,
            )
            return

        entry_price = signals.get("entry_price", signals.get("price"))
        if entry_price is None or pd.isna(entry_price):
            return

        stop_price = signals.get("stop_price", entry_price * (1 - self.config.stopLossPct))
        tp1_price = signals.get(
            "tp1_price", entry_price * (1 + self.config.takeProfitPct)
        )
        tp2_price = signals.get("tp2_price", tp1_price)

        risk_pct = self.config.riskPct
        atr_pct = signals.get("atr_pct")
        if (
            self.use_multi_tf
            and self.config.atrRiskScaling
            and isinstance(atr_pct, (float, int))
            and atr_pct > self.config.atrRiskScalingThreshold
        ):
            risk_pct *= self.config.atrRiskScalingFactor

        if entry_price <= 0 or stop_price <= 0:
            return

        stop_loss_pct = (entry_price - stop_price) / entry_price
        if stop_loss_pct <= 0:
            return

        qty = risk_position_size(
            equity_usdt=self.equity,
            risk_pct=risk_pct,
            stop_loss_pct=stop_loss_pct,
            price=entry_price,
            cash_cap=self.config.cashDeployCap,
        )
        if qty <= 0:
            return

        entry_fill = self.simulate_fill(entry_price, is_entry=True)
        fees = self.calculate_fees(entry_fill * qty)

        self.position_qty = qty
        self.position_entry = entry_fill
        self.position_side = "LONG"
        self.balance -= fees
        self.mark_equity(entry_fill)

        risk_per_unit = max(entry_fill - stop_price, 1e-8)
        risk_reward = (tp2_price - entry_fill) / risk_per_unit if risk_per_unit else 0

        self.active_trade = {
            "entry_time": timestamp,
            "entry_price": entry_fill,
            "stop_price": stop_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "initial_qty": qty,
            "open_qty": qty,
            "tp1_hit": False,
            "tp2_hit": False,
            "realized_pnl": -fees,
            "risk_per_unit": risk_per_unit,
            "bars_in_trade": 0,
        }

        logger.debug(
            "[%s] OPEN LONG qty=%.4f entry=%.4f tp1=%.4f tp2=%.4f sl=%.4f R:R=%.2f",
            timestamp,
            qty,
            entry_fill,
            tp1_price,
            tp2_price,
            stop_price,
            risk_reward,
        )

    def _take_partial_tp1(self, price: float, timestamp: pd.Timestamp) -> None:
        if not self.active_trade or self.position_qty <= 0:
            return

        qty = self.active_trade["open_qty"] * 0.5
        if qty <= 0:
            return

        exit_fill = self.simulate_fill(price, is_entry=False)
        fees = self.calculate_fees(exit_fill * qty)
        pnl = (exit_fill - self.position_entry) * qty - fees

        self.balance += pnl
        self.active_trade["realized_pnl"] += pnl
        self.active_trade["open_qty"] -= qty
        self.position_qty = self.active_trade["open_qty"]
        self.active_trade["tp1_hit"] = True
        self.tp1_hits += 1

        if self.config.breakevenAfterTp1:
            self.active_trade["stop_price"] = max(
                self.active_trade["stop_price"], self.position_entry
            )

        self.mark_equity(exit_fill)
        logger.debug("[%s] TP1 partial filled qty=%.4f at %.4f", timestamp, qty, exit_fill)

    def _finalize_trade(self, price: float, timestamp: pd.Timestamp, reason: str) -> None:
        if not self.active_trade or self.position_qty <= 0:
            return

        exit_fill = self.simulate_fill(price, is_entry=False)
        qty = self.active_trade["open_qty"]
        fees = self.calculate_fees(exit_fill * qty)
        pnl_remaining = (exit_fill - self.position_entry) * qty - fees
        total_realized = self.active_trade["realized_pnl"] + pnl_remaining

        self.balance += pnl_remaining
        self.position_qty = 0.0
        self.position_entry = 0.0
        self.position_side = None
        self.mark_equity(exit_fill)

        duration_bars = self.active_trade["bars_in_trade"]
        risk_dollars = self.active_trade["risk_per_unit"] * self.active_trade["initial_qty"]
        r_multiple = total_realized / risk_dollars if risk_dollars else 0.0

        self.r_multiples.append(r_multiple)
        self.trade_durations.append(duration_bars)
        self.total_trades += 1
        self.tp2_hits += 1 if self.active_trade.get("tp2_hit") else 0

        if total_realized > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
        self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)

        trade_record = {
            "timestamp": timestamp,
            "pnl": total_realized,
            "reason": reason,
            "tp1_hit": self.active_trade.get("tp1_hit", False),
            "tp2_hit": self.active_trade.get("tp2_hit", False),
            "r_multiple": r_multiple,
            "duration_bars": duration_bars,
        }
        self.trades.append(trade_record)

        logger.debug(
            "[%s] EXIT reason=%s pnl=%.2f r=%.2f duration=%d bars",
            timestamp,
            reason,
            total_realized,
            r_multiple,
            duration_bars,
        )

        self.active_trade = None

    def manage_open_position(
        self, bar: pd.Series, signals: Dict[str, Any], timestamp: pd.Timestamp
    ) -> None:
        if not self.active_trade or self.position_qty <= 0:
            return

        self.active_trade["bars_in_trade"] += 1

        if (
            self.use_multi_tf
            and self.config.exitOnTrendFlip
            and not signals.get("htf_trend_up", False)
        ):
            self._finalize_trade(bar["close"], timestamp, "TREND_FLIP")
            return

        if self.active_trade["bars_in_trade"] >= self.config.maxBarsInTrade:
            self._finalize_trade(bar["close"], timestamp, "MAX_BARS")
            return

        stop_price = self.active_trade["stop_price"]
        tp1_price = self.active_trade["tp1_price"]
        tp2_price = self.active_trade["tp2_price"]

        if bar["low"] <= stop_price:
            self._finalize_trade(stop_price, timestamp, "STOP")
            return

        if bar["high"] >= tp2_price:
            self.active_trade["tp2_hit"] = True
            self._finalize_trade(tp2_price, timestamp, "TP2")
            return

        if not self.active_trade["tp1_hit"] and bar["high"] >= tp1_price:
            self._take_partial_tp1(tp1_price, timestamp)

    def run_backtest(
        self, ltf_df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        if ltf_df is None or ltf_df.empty:
            return {"error": "No historical data provided"}

        start_idx = 35
        if self.use_multi_tf:
            start_idx = max(60, self.config.atrPeriod + 50)
            if htf_df is None or htf_df.empty:
                return {"error": "HTF data required for multi-timeframe strategy"}

        for i in range(start_idx, len(ltf_df)):
            window_ltf = ltf_df.iloc[: i + 1]
            ts = window_ltf.index[-1]

            if self.use_multi_tf:
                htf_window = htf_df[htf_df.index <= ts]
                signals = compute_signals_multi_tf(window_ltf, htf_window, config=self.config)
            else:
                signals = compute_signals(window_ltf)

            bar = window_ltf.iloc[-1]
            self.manage_open_position(bar, signals, ts)

            if self.position_qty == 0 and signals.get("long_signal"):
                self.open_position(signals, ts)

            self.mark_equity(bar["close"])
            self.equity_curve.append(
                {
                    "timestamp": ts,
                    "equity": self.equity,
                    "balance": self.balance,
                    "position_qty": self.position_qty,
                }
            )

        if self.position_qty > 0:
            last_bar = ltf_df.iloc[-1]
            self._finalize_trade(last_bar["close"], ltf_df.index[-1], "END_OF_DATA")

        return self.calculate_metrics()

    def calculate_metrics(self) -> Dict[str, Any]:
        if not self.trades:
            logger.warning("No trades executed during backtest")
            return {
                "total_trades": 0,
                "error": "No trades executed - check if signals are being generated",
            }

        total_pnl = sum(t["pnl"] for t in self.trades)
        win_rate = self.winning_trades / self.total_trades if self.total_trades else 0

        winning_pnls = [t["pnl"] for t in self.trades if t["pnl"] > 0]
        losing_pnls = [t["pnl"] for t in self.trades if t["pnl"] < 0]
        avg_win = np.mean(winning_pnls) if winning_pnls else 0
        avg_loss = np.mean(losing_pnls) if losing_pnls else 0
        gross_profit = sum(winning_pnls) if winning_pnls else 0
        gross_loss = abs(sum(losing_pnls)) if losing_pnls else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        equity_series = pd.Series([e["equity"] for e in self.equity_curve])
        peak = equity_series.expanding().max()
        drawdown = (equity_series - peak) / peak
        max_drawdown = drawdown.min()

        returns = equity_series.pct_change().dropna()
        sharpe_ratio = (
            (returns.mean() / returns.std()) * np.sqrt(252)
            if len(returns) > 1 and returns.std() > 0
            else 0
        )

        avg_r_multiple = np.mean(self.r_multiples) if self.r_multiples else 0.0
        median_r_multiple = np.median(self.r_multiples) if self.r_multiples else 0.0
        tp1_hit_rate = (self.tp1_hits / self.total_trades) * 100 if self.total_trades else 0
        tp2_hit_rate = (self.tp2_hits / self.total_trades) * 100 if self.total_trades else 0
        avg_duration = np.mean(self.trade_durations) if self.trade_durations else 0

        metrics = {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / self.initial_balance) * 100,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate * 100,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown * 100,
            "max_consecutive_losses": self.max_consecutive_losses,
            "sharpe_ratio": sharpe_ratio,
            "avg_r_multiple": avg_r_multiple,
            "median_r_multiple": median_r_multiple,
            "tp1_hit_rate": tp1_hit_rate,
            "tp2_hit_rate": tp2_hit_rate,
            "avg_duration_bars": avg_duration,
        }
        return metrics

    def print_results(self, metrics: Dict[str, Any]) -> None:
        if "error" in metrics:
            logger.error("=" * 60)
            logger.error("Backtest Failed")
            logger.error("=" * 60)
            logger.error(f"Error: {metrics['error']}")
            logger.error("=" * 60)
            return

        logger.info("=" * 60)
        logger.info("Backtest Results")
        logger.info("=" * 60)
        logger.info(f"Initial Balance: ${metrics['initial_balance']:.2f}")
        logger.info(f"Final Balance: ${metrics['final_balance']:.2f}")
        logger.info(f"Total P&L: ${metrics['total_pnl']:.2f} ({metrics['total_pnl_pct']:+.2f}%)")
        logger.info("-" * 60)
        logger.info(f"Total Trades: {metrics['total_trades']}")
        logger.info(f"Winning Trades: {metrics['winning_trades']} ({metrics['win_rate']:.2f}%)")
        logger.info(f"Losing Trades: {metrics['losing_trades']}")
        logger.info(f"Win Rate: {metrics['win_rate']:.2f}%")
        logger.info("-" * 60)
        logger.info(f"Average Win: ${metrics['avg_win']:.2f}")
        logger.info(f"Average Loss: ${metrics['avg_loss']:.2f}")
        logger.info(f"Profit Factor: {metrics['profit_factor']:.2f}")
        logger.info(f"Avg R Multiple: {metrics['avg_r_multiple']:.2f} (median {metrics['median_r_multiple']:.2f})")
        logger.info(f"TP1 Hit Rate: {metrics['tp1_hit_rate']:.2f}% | TP2 Hit Rate: {metrics['tp2_hit_rate']:.2f}%")
        logger.info(f"Avg Duration: {metrics['avg_duration_bars']:.1f} bars")
        logger.info("-" * 60)
        logger.info(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
        logger.info(f"Max Consecutive Losses: {metrics['max_consecutive_losses']}")
        logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info("=" * 60)

    def save_results(self, metrics: Dict[str, Any], output_path: str) -> None:
        payload = {
            "metrics": metrics,
            "trades": [
                {**t, "timestamp": t["timestamp"].isoformat()} for t in self.trades
            ],
            "equity_curve": [
                {**e, "timestamp": e["timestamp"].isoformat()} for e in self.equity_curve
            ],
        }
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        logger.info("Results saved to %s", output_path)


class HistoricalDataProvider(Protocol):
    async def fetch(
        self, symbol: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        ...


class ZoomexDataProvider:
    def __init__(self, *, use_testnet: bool = False, base_url: Optional[str] = None):
        self.use_testnet = use_testnet
        self.base_url = base_url

    async def fetch(
        self, symbol: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        base_url = (
            "https://openapi-testnet.zoomex.com"
            if self.use_testnet
            else (self.base_url or "https://openapi.zoomex.com")
        )
        start_dt = pd.to_datetime(start_date).tz_localize("UTC")
        end_dt = pd.to_datetime(end_date).tz_localize("UTC")

        async with aiohttp.ClientSession() as session:
            client = ZoomexV3Client(
                session,
                base_url=base_url,
                category="linear",
                require_auth=False,
            )

            all_data: List[pd.DataFrame] = []
            current_dt = start_dt

            while current_dt < end_dt:
                try:
                    df = await client.get_klines(
                        symbol=symbol, interval=interval, limit=200
                    )
                    if df.empty:
                        logger.warning("No data returned for %s", current_dt)
                        break

                    all_data.append(df)
                    last_time = df.index[-1].to_pydatetime()
                    if last_time <= current_dt:
                        # Prevent infinite loop if the exchange repeats candles.
                        break
                    current_dt = last_time + timedelta(minutes=int(interval))
                    await asyncio.sleep(0.2)
                except Exception as exc:
                    logger.error("Error fetching data: %s", exc)
                    break

        if not all_data:
            raise ValueError("No data fetched - check symbol and date range")

        combined = pd.concat(all_data).sort_index()
        combined = combined[~combined.index.duplicated(keep="first")]
        mask = (combined.index >= start_dt) & (combined.index <= end_dt)
        return combined[mask]


class CsvDataProvider:
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = csv_path

    def _resolve_path(self, symbol: str, interval: str) -> Path:
        if self.csv_path:
            candidate = Path(self.csv_path)
            if candidate.is_dir():
                primary = candidate / f"{symbol}_{interval}.csv"
                alt = candidate / f"{symbol}_{interval}m.csv"
                return primary if primary.exists() else alt
            return candidate
        base_dir = Path("data") / "history"
        primary = base_dir / f"{symbol}_{interval}.csv"
        alt = base_dir / f"{symbol}_{interval}m.csv"
        return primary if primary.exists() else alt

    async def fetch(
        self, symbol: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        path = self._resolve_path(symbol, interval)
        if not path.exists():
            raise FileNotFoundError(
                f"CSV data not found at {path}. Provide --csv-path or place file under data/history/{symbol}_{interval}.csv"
            )

        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        if not rows:
            raise ValueError(f"CSV at {path} is empty")

        records = []
        for row in rows:
            ts_raw = row.get("timestamp") or row.get("time") or row.get("start")
            if ts_raw is None:
                continue
            try:
                if str(ts_raw).isdigit():
                    ts = pd.to_datetime(int(ts_raw), unit="ms", utc=True)
                else:
                    ts = pd.to_datetime(ts_raw, utc=True)
            except Exception:
                continue
            records.append(
                {
                    "start": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )

        if not records:
            raise ValueError(f"No valid rows parsed from {path}")

        df = pd.DataFrame.from_records(records)
        df.set_index("start", inplace=True)
        df.sort_index(inplace=True)
        try:
            minutes = int(interval)
            rule = f"{minutes}min"
        except ValueError:
            rule = interval
        df = (
            df.resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )

        start_dt = pd.to_datetime(start_date).tz_localize("UTC")
        end_dt = pd.to_datetime(end_date).tz_localize("UTC")
        mask = (df.index >= start_dt) & (df.index <= end_dt)
        return df.loc[mask]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest perpetual futures strategy")
    parser.add_argument("--symbol", type=str, required=True, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", type=str, default="5", help="Candle interval in minutes (default: 5)")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/zoomex_example.yaml",
        help="Configuration file path",
    )
    parser.add_argument(
        "--initial-balance",
        type=float,
        default=1000.0,
        help="Initial balance in USDT (default: 1000)",
    )
    parser.add_argument("--output", type=str, help="Output file path for results (JSON)")
    parser.add_argument("--testnet", action="store_true", help="Use testnet for data fetching")
    parser.add_argument(
        "--data-source",
        type=str,
        choices=["zoomex", "csv"],
        default="zoomex",
        help="Historical data source for backtests (default: zoomex)",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        help="Optional CSV path when using --data-source csv; otherwise defaults to data/history/{symbol}_{interval}.csv",
    )
    parser.add_argument(
        "--use-multi-tf-atr-strategy",
        action="store_true",
        help="Force the multi-timeframe ATR strategy during backtest",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    os.environ["CONFIG_PATH"] = args.config
    config = get_config()
    config.perps.symbol = args.symbol
    config.perps.interval = args.interval
    config.perps.useMultiTfAtrStrategy = (
        args.use_multi_tf_atr_strategy or config.perps.useMultiTfAtrStrategy
    )

    if args.data_source == "csv":
        provider: HistoricalDataProvider = CsvDataProvider(csv_path=args.csv_path)
    else:
        provider = ZoomexDataProvider(use_testnet=args.testnet)

    ltf_df = await provider.fetch(
        symbol=args.symbol,
        interval=args.interval,
        start_date=args.start,
        end_date=args.end,
    )

    htf_df = None
    if config.perps.useMultiTfAtrStrategy:
        htf_df = await provider.fetch(
            symbol=args.symbol,
            interval=config.perps.htfInterval,
            start_date=args.start,
            end_date=args.end,
        )

    backtest = PerpsBacktest(
        config.perps,
        initial_balance=args.initial_balance,
        use_multi_tf=config.perps.useMultiTfAtrStrategy,
    )
    metrics = backtest.run_backtest(ltf_df, htf_df)

    if metrics:
        backtest.print_results(metrics)
        if args.output:
            backtest.save_results(metrics, args.output)


if __name__ == "__main__":
    asyncio.run(main())
