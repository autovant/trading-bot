import logging
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import ccxt.async_support as ccxt
import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


def _timeframe_to_seconds(tf: str) -> int:
    units = {"m": 60, "h": 3600, "d": 86400}
    tf = tf.strip().lower()
    for suffix, mult in units.items():
        if tf.endswith(suffix):
            return int(float(tf[:-1]) * mult)
    raise ValueError(f"Unsupported timeframe {tf}")


class IndicatorLibrary:
    """Polars/NumPy indicator set including Market Cipher B."""

    @staticmethod
    def _ema(arr: np.ndarray, period: int) -> np.ndarray:
        if len(arr) == 0:
            return arr
        alpha = 2 / (period + 1)
        ema = np.zeros_like(arr, dtype=float)
        ema[0] = arr[0]
        for i in range(1, len(arr)):
            ema[i] = alpha * arr[i] + (1 - alpha) * ema[i - 1]
        return ema

    def rsi(self, series: pl.Series, period: int = 14) -> pl.Series:
        arr = series.to_numpy()
        delta = np.diff(arr, prepend=arr[0]).astype(float)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        avg_gain = self._ema(gain, period)
        avg_loss = self._ema(loss, period)
        rs = np.divide(
            avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0
        )
        rsi = 100 - (100 / (1 + rs))
        return pl.Series(rsi)

    def ema(self, series: pl.Series, period: int) -> pl.Series:
        return pl.Series(self._ema(series.to_numpy(), period))

    def macd(
        self, series: pl.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Dict[str, pl.Series]:
        macd_line = self.ema(series, fast) - self.ema(series, slow)
        signal_line = pl.Series(self._ema(macd_line.to_numpy(), signal))
        hist = macd_line - signal_line
        return {"macd": macd_line, "signal": signal_line, "hist": hist}

    def bollinger(
        self, series: pl.Series, period: int = 20, std: float = 2.0
    ) -> Dict[str, pl.Series]:
        ma = series.rolling_mean(window_size=period)
        rolling_std = series.rolling_std(window_size=period)
        upper = ma + rolling_std * std
        lower = ma - rolling_std * std
        return {"middle": ma, "upper": upper, "lower": lower}

    def vwap(self, df: pl.DataFrame) -> pl.Series:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        cum_vol = df["volume"].cum_sum()
        cum_tp_vol = (typical * df["volume"]).cum_sum()
        return cum_tp_vol / cum_vol

    def ema_ribbon(
        self, series: pl.Series, periods: Optional[List[int]] = None
    ) -> Dict[str, pl.Series]:
        periods = periods or [8, 13, 21, 34, 55]
        ribbon = {}
        for p in periods:
            ribbon[f"ema_{p}"] = self.ema(series, p)
        return ribbon

    def wavetrend_cipher_b(
        self, df: pl.DataFrame, n1: int = 10, n2: int = 21
    ) -> Dict[str, pl.Series]:
        """
        Market Cipher B / WaveTrend implementation (NumPy on Polars data).
        Returns wt1, wt2, money_flow (vwap approx) and dot colors.
        """
        ap = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
        esa = self._ema(ap, n1)
        d = self._ema(np.abs(ap - esa), n1)
        ci = (ap - esa) / (0.015 * d + 1e-9)
        tci = self._ema(ci, n2)
        wt1 = tci
        wt2 = (
            pl.Series(wt1)
            .rolling_mean(window_size=4)
            .fill_null(strategy="backward")
            .to_numpy()
        )
        diff = wt1 - wt2

        green = (np.roll(diff, 1) < 0) & (diff >= 0) & (wt1 < -60)
        red = (np.roll(diff, 1) > 0) & (diff <= 0) & (wt1 > 60)
        dot = np.full_like(diff, "NONE", dtype=object)
        dot[green] = "GREEN"
        dot[red] = "RED"

        money_flow = self.vwap(df).to_numpy()

        return {
            "wt1": pl.Series(wt1),
            "wt2": pl.Series(wt2),
            "diff": pl.Series(diff),
            "dot": pl.Series(dot),
            "money_flow": pl.Series(money_flow),
        }

    def divergence(
        self, price: pl.Series, indicator: pl.Series, lookback: int = 5
    ) -> pl.Series:
        """
        Simple divergence detector: bearish if price higher highs while indicator lower highs,
        bullish if price lower lows while indicator higher lows.
        """
        price_arr = price.to_numpy()
        ind_arr = indicator.to_numpy()
        states = np.array(["none"] * len(price_arr), dtype=object)

        def pivots(arr: np.ndarray, is_high: bool) -> List[int]:
            idxs: List[int] = []
            for i in range(lookback, len(arr) - lookback):
                window = arr[i - lookback : i + lookback + 1]
                if is_high and arr[i] == window.max():
                    idxs.append(i)
                if not is_high and arr[i] == window.min():
                    idxs.append(i)
            return idxs

        highs = pivots(price_arr, True)
        lows = pivots(price_arr, False)
        ind_highs = pivots(ind_arr, True)
        ind_lows = pivots(ind_arr, False)

        if len(highs) >= 2 and len(ind_highs) >= 2:
            if (
                price_arr[highs[-1]] > price_arr[highs[-2]]
                and ind_arr[ind_highs[-1]] < ind_arr[ind_highs[-2]]
            ):
                states[highs[-1]] = "bearish"
        if len(lows) >= 2 and len(ind_lows) >= 2:
            if (
                price_arr[lows[-1]] < price_arr[lows[-2]]
                and ind_arr[ind_lows[-1]] > ind_arr[ind_lows[-2]]
            ):
                states[lows[-1]] = "bullish"

        return pl.Series(states)


class DynamicStrategyEngine:
    """
    Executes trading strategies defined in JSON format using real CCXT OHLCV data.
    Supports multi-timeframe aggregation, Market Cipher B, divergence detection,
    EMA ribbons, VWAP checks, and walk-forward sweeps.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        exchange_client: Any = None,
        base_timeframe: str = "1m",
    ):
        self.exchange_id = exchange_id
        self.exchange = exchange_client
        self.base_timeframe = base_timeframe
        self.indicators = IndicatorLibrary()

    async def _ensure_exchange(self):
        if self.exchange is None:
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class({"enableRateLimit": True})
            await self.exchange.load_markets()

    async def fetch_data(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int = 1000,
    ) -> pl.DataFrame:
        await self._ensure_exchange()
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        step = _timeframe_to_seconds(timeframe) * 1000

        all_rows: List[List[float]] = []
        since = start_ms
        while since < end_ms:
            batch = await self.exchange.fetch_ohlcv(
                symbol, timeframe, since=since, limit=limit
            )
            if not batch:
                break
            all_rows.extend(batch)
            since = batch[-1][0] + step
            if batch[-1][0] >= end_ms or len(batch) < limit:
                break

        if not all_rows:
            raise RuntimeError("No data returned from exchange for requested window.")

        df = pl.DataFrame(
            all_rows,
            schema=["timestamp", "open", "high", "low", "close", "volume"],
            orient="row",
        )
        df = df.with_columns(
            pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp")
        ).sort("timestamp")
        df = df.filter(
            pl.col("timestamp") <= pl.lit(datetime.fromtimestamp(end_ms / 1000))
        )
        return df

    def resample(self, df: pl.DataFrame, timeframe: str) -> pl.DataFrame:
        every = timeframe
        if timeframe[-1].isdigit():
            every = timeframe + "s"  # fallback
        try:
            return (
                df.sort("timestamp")
                .group_by_dynamic(
                    "timestamp",
                    every=every,
                    period=every,
                    closed="right",
                    label="right",
                )
                .agg(
                    [
                        pl.col("open").first().alias("open"),
                        pl.col("high").max().alias("high"),
                        pl.col("low").min().alias("low"),
                        pl.col("close").last().alias("close"),
                        pl.col("volume").sum().alias("volume"),
                    ]
                )
                .drop_nulls()
            )
        except Exception:
            # Fallback: use seconds duration if polars complains about format
            every = f"{_timeframe_to_seconds(timeframe)}s"
            return (
                df.sort("timestamp")
                .group_by_dynamic(
                    "timestamp",
                    every=every,
                    period=every,
                    closed="right",
                    label="right",
                )
                .agg(
                    [
                        pl.col("open").first().alias("open"),
                        pl.col("high").max().alias("high"),
                        pl.col("low").min().alias("low"),
                        pl.col("close").last().alias("close"),
                        pl.col("volume").sum().alias("volume"),
                    ]
                )
                .drop_nulls()
            )

    def _indicator_frame(
        self, df: pl.DataFrame, trigger: Dict[str, Any]
    ) -> pl.DataFrame:
        name = trigger.get("indicator")
        params = trigger.get("params", {}) or {}

        if name == "rsi":
            series = self.indicators.rsi(df["close"], params.get("period", 14))
            return pl.DataFrame({"timestamp": df["timestamp"], "value": series})
        if name == "ema":
            series = self.indicators.ema(df["close"], params.get("period", 20))
            return pl.DataFrame({"timestamp": df["timestamp"], "value": series})
        if name == "macd":
            macd = self.indicators.macd(
                df["close"],
                params.get("fast", 12),
                params.get("slow", 26),
                params.get("signal", 9),
            )
            return pl.DataFrame(
                {
                    "timestamp": df["timestamp"],
                    "value": macd["hist"],
                    "macd": macd["macd"],
                    "signal": macd["signal"],
                }
            )
        if name == "bollinger":
            bands = self.indicators.bollinger(
                df["close"], params.get("period", 20), params.get("std", 2.0)
            )
            return pl.DataFrame(
                {
                    "timestamp": df["timestamp"],
                    "upper": bands["upper"],
                    "lower": bands["lower"],
                    "value": bands["middle"],
                    "close": df["close"],
                }
            )
        if name == "vwap":
            return pl.DataFrame(
                {"timestamp": df["timestamp"], "value": self.indicators.vwap(df)}
            )
        if name == "ema_ribbon":
            ribbon = self.indicators.ema_ribbon(df["close"], params.get("periods"))
            above = df["close"] > pl.DataFrame(ribbon).select(pl.all()).min_horizontal()
            below = df["close"] < pl.DataFrame(ribbon).select(pl.all()).max_horizontal()
            return pl.DataFrame(
                {
                    "timestamp": df["timestamp"],
                    "state": above.replace(True, "above").replace(False, "below"),
                }
            ).with_columns(  # type: ignore  # noqa: E501
                pl.when(below)
                .then("below")
                .when(above)
                .then("above")
                .otherwise("neutral")
                .alias("state")
            )
        if name in ("wavetrend_dot", "wavetrend_wt1", "wavetrend_wt2"):
            wt = self.indicators.wavetrend_cipher_b(
                df, params.get("n1", 10), params.get("n2", 21)
            )
            if name == "wavetrend_dot":
                return pl.DataFrame({"timestamp": df["timestamp"], "state": wt["dot"]})
            if name == "wavetrend_wt1":
                return pl.DataFrame({"timestamp": df["timestamp"], "value": wt["wt1"]})
            return pl.DataFrame({"timestamp": df["timestamp"], "value": wt["wt2"]})
        if name == "divergence":
            rsi = self.indicators.rsi(df["close"], params.get("period", 14))
            state = self.indicators.divergence(
                df["close"], rsi, params.get("lookback", 5)
            )
            return pl.DataFrame({"timestamp": df["timestamp"], "state": state})

        # default passthrough close price
        return pl.DataFrame({"timestamp": df["timestamp"], "value": df["close"]})

    def _condition_series(self, df: pl.DataFrame, trigger: Dict[str, Any]) -> pl.Series:
        operator = trigger.get("operator")
        target = trigger.get("value")
        params = trigger.get("params", {}) or {}

        field = params.get("field")
        if field and field in df.columns:
            series = df[field]
        elif "state" in df.columns:
            series = df["state"]
        else:
            series = df["value"]

        compare_to = params.get("compare_to")
        rhs_series = df[compare_to] if compare_to and compare_to in df.columns else None

        def _as_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        if operator == "crosses_up":
            thresh = _as_float(target)
            if thresh is None:
                return pl.Series([False] * len(series))
            prev = series.shift(1)
            return (prev < thresh) & (series >= thresh)
        if operator == "crosses_down":
            thresh = _as_float(target)
            if thresh is None:
                return pl.Series([False] * len(series))
            prev = series.shift(1)
            return (prev > thresh) & (series <= thresh)
        if operator == "==":
            return series.cast(str) == (
                rhs_series.cast(str) if rhs_series is not None else str(target)
            )
        if operator == ">":
            if rhs_series is not None:
                return series > rhs_series
            rhs = _as_float(target)
            if rhs is None:
                return pl.Series([False] * len(series))
            return series > rhs
        if operator == "<":
            if rhs_series is not None:
                return series < rhs_series
            rhs = _as_float(target)
            if rhs is None:
                return pl.Series([False] * len(series))
            return series < rhs
        if operator == ">=":
            if rhs_series is not None:
                return series >= rhs_series
            rhs = _as_float(target)
            if rhs is None:
                return pl.Series([False] * len(series))
            return series >= rhs
        if operator == "<=":
            if rhs_series is not None:
                return series <= rhs_series
            rhs = _as_float(target)
            if rhs is None:
                return pl.Series([False] * len(series))
            return series <= rhs
        return pl.Series([False] * len(series))

    def _evaluate_triggers(
        self, base: pl.DataFrame, triggers: List[Dict[str, Any]]
    ) -> pl.DataFrame:
        if not triggers:
            return base.select(["timestamp"])

        timeframes = {t.get("timeframe", self.base_timeframe) for t in triggers}
        cached: Dict[str, pl.DataFrame] = {}
        for tf in timeframes:
            cached[tf] = base if tf == self.base_timeframe else self.resample(base, tf)

        trigger_frames: List[pl.DataFrame] = []
        for idx, trig in enumerate(triggers):
            tf = trig.get("timeframe", self.base_timeframe)
            tf_df = cached[tf]
            ind_df = self._indicator_frame(tf_df, trig)
            cond = self._condition_series(ind_df, trig)
            tf_signals = pl.DataFrame(
                {"timestamp": ind_df["timestamp"], f"trigger_{idx}": cond}
            )
            aligned = base.join_asof(
                tf_signals.sort("timestamp"), on="timestamp", strategy="backward"
            ).select(["timestamp", f"trigger_{idx}"])
            trigger_frames.append(aligned)

        combined = trigger_frames[0]
        for frame in trigger_frames[1:]:
            combined = combined.join(frame, on="timestamp", how="inner")
        return combined

    def _combine_logic(self, trigger_df: pl.DataFrame, logic: str) -> pl.Series:
        cols = [c for c in trigger_df.columns if c.startswith("trigger_")]
        if not cols:
            return pl.Series([False] * len(trigger_df))
        if logic.upper() == "OR":
            return trigger_df.select(pl.any_horizontal(cols)).to_series()
        return trigger_df.select(pl.all_horizontal(cols)).to_series()

    def _position_size(
        self, equity: float, risk_pct: float, entry: float, stop: float
    ) -> float:
        risk_amount = equity * (risk_pct / 100.0)
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def _simulate(
        self,
        data: pl.DataFrame,
        signals: pl.Series,
        risk: Dict[str, Any],
    ) -> Dict[str, Any]:
        equity = float(risk.get("initial_capital", 100_000))
        risk_pct = float(risk.get("risk_per_trade_pct", 1.0))
        stop_loss_pct = float(risk.get("stop_loss_pct", 1.0)) / 100.0
        take_profit_pct = float(risk.get("take_profit_pct", 2.0)) / 100.0

        in_position = False
        qty = 0.0
        entry_price = 0.0
        wins = 0
        losses = 0
        equity_curve: List[Tuple[datetime, float]] = []

        for row, signal in zip(data.iter_rows(named=True), signals, strict=False):
            price = float(row["close"])
            ts = row["timestamp"]

            if in_position:
                stop_price = entry_price * (1 - stop_loss_pct)
                target_price = entry_price * (1 + take_profit_pct)
                low = float(row["low"])
                high = float(row["high"])

                if low <= stop_price:
                    equity += qty * (stop_price - entry_price)
                    losses += 1
                    in_position = False
                    qty = 0
                    entry_price = 0
                elif high >= target_price:
                    equity += qty * (target_price - entry_price)
                    wins += 1
                    in_position = False
                    qty = 0
                    entry_price = 0
                elif not signal:
                    equity += qty * (price - entry_price)
                    if price > entry_price:
                        wins += 1
                    else:
                        losses += 1
                    in_position = False
                    qty = 0
                    entry_price = 0
            else:
                if signal:
                    stop_price = price * (1 - stop_loss_pct)
                    qty = self._position_size(equity, risk_pct, price, stop_price)
                    if qty > 0:
                        entry_price = price
                        in_position = True

            mtm = equity if not in_position else equity + qty * (price - entry_price)
            equity_curve.append((ts, mtm))

        if in_position:
            equity += qty * (float(data[-1, "close"]) - entry_price)
            if float(data[-1, "close"]) > entry_price:
                wins += 1
            else:
                losses += 1
            equity_curve.append((data[-1, "timestamp"], equity))

        pnl = equity - float(risk.get("initial_capital", 100_000))
        trades = wins + losses
        win_rate = wins / trades if trades > 0 else 0.0
        equity_vals = np.array([eq for _, eq in equity_curve], dtype=float)
        peaks = np.maximum.accumulate(equity_vals)
        drawdowns = (peaks - equity_vals) / peaks
        max_dd = float(drawdowns.max()) if len(drawdowns) else 0.0

        return {
            "pnl": float(pnl),
            "trades": trades,
            "win_rate": win_rate,
            "max_drawdown": max_dd,
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": float(eq)}
                for ts, eq in equity_curve
            ],
        }

    async def run_backtest(
        self,
        strategy_config: Dict[str, Any],
        symbol: str,
        start_date: str,
        end_date: str,
        optimization: Optional[Dict[str, Any]] = None,
        data: Optional[pl.DataFrame] = None,
    ) -> Dict[str, Any]:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        base_df = (
            data
            if data is not None
            else await self.fetch_data(symbol, self.base_timeframe, start, end)
        )
        risk_block = strategy_config.get(
            "risk",
            {
                "initial_capital": 100_000,
                "risk_per_trade_pct": 1.0,
                "stop_loss_pct": 1.0,
                "take_profit_pct": 2.0,
            },
        )

        async def evaluate(config: Dict[str, Any]) -> Dict[str, Any]:
            triggers = config.get("triggers", [])
            trigger_df = self._evaluate_triggers(base_df, triggers)
            signals = self._combine_logic(trigger_df, config.get("logic", "AND"))
            return self._simulate(base_df, signals, risk_block)

        if optimization:
            idx = optimization.get("trigger_index", 0)
            start_val = float(optimization.get("start", 0))
            end_val = float(optimization.get("end", 0))
            step = float(optimization.get("step", 1))
            results: List[Dict[str, Any]] = []

            sweep_val = start_val
            while sweep_val <= end_val + 1e-9:
                candidate = deepcopy(strategy_config)
                triggers = candidate.get("triggers")
                if (
                    isinstance(triggers, list)
                    and 0 <= idx < len(triggers)
                    and isinstance(triggers[idx], dict)
                ):
                    triggers[idx]["value"] = sweep_val
                res = await evaluate(candidate)
                res["sweep_value"] = sweep_val
                results.append(res)
                sweep_val += step

            best = max(results, key=lambda r: r["pnl"]) if results else {}
            return {
                "optimization": {
                    "grid": [
                        {
                            "value": r["sweep_value"],
                            "pnl": r["pnl"],
                            "trades": r["trades"],
                        }
                        for r in results
                    ],
                    "best_value": best.get("sweep_value"),
                    "best_pnl": best.get("pnl"),
                },
                "pnl": best.get("pnl", 0.0),
                "trades": best.get("trades", 0),
                "win_rate": best.get("win_rate", 0.0),
                "max_drawdown": best.get("max_drawdown", 0.0),
                "equity_curve": best.get("equity_curve", []),
            }

        return await evaluate(strategy_config)

    async def walk_forward_optimization(
        self,
        strategy_template: Dict[str, Any],
        symbol: str,
        start_date: str,
        end_date: str,
        param_ranges: Dict[str, List[Any]],
    ) -> Dict[str, Any]:
        """
        Walk-forward optimization: Test multiple parameter combinations.

        param_ranges example:
        {
            "rsi_period": [10, 12, 14, 16],
            "rsi_threshold": [30, 35, 40]
        }
        """
        import itertools

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        base_df = await self.fetch_data(symbol, self.base_timeframe, start, end)

        param_names = list(param_ranges.keys())
        combinations = list(itertools.product(*param_ranges.values()))
        results: List[Dict[str, Any]] = []

        for combo in combinations:
            strategy = deepcopy(strategy_template)
            for name, val in zip(param_names, combo, strict=False):
                for trigger in strategy.get("triggers", []):
                    indicator_name = trigger.get("indicator", "")
                    if indicator_name and indicator_name in name:
                        trigger.setdefault("params", {})
                        if "period" in name:
                            trigger["params"]["period"] = val
                        if "threshold" in name or name.endswith("value"):
                            trigger["value"] = val

            trig_df = self._evaluate_triggers(base_df, strategy.get("triggers", []))
            signals = self._combine_logic(trig_df, strategy.get("logic", "AND"))
            res = self._simulate(
                base_df,
                signals,
                strategy.get(
                    "risk",
                    {
                        "initial_capital": 100_000,
                        "risk_per_trade_pct": 1.0,
                        "stop_loss_pct": 1.0,
                        "take_profit_pct": 2.0,
                    },
                ),
            )
            res["params"] = dict(zip(param_names, combo, strict=False))
            results.append(res)

        results.sort(key=lambda x: x["pnl"], reverse=True)
        return {
            "best_params": results[0]["params"] if results else {},
            "best_pnl": results[0]["pnl"] if results else 0.0,
            "all_results": results,
        }

    @staticmethod
    def calculate_position_size(
        account_balance: float,
        risk_per_trade_percent: float,
        entry_price: float,
        stop_loss_price: float,
    ) -> float:
        """
        Calculate position size based on risk management rules.

        Args:
            account_balance: Current account balance
            risk_per_trade_percent: Risk per trade as a percentage (e.g., 1.0 for 1%)
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price

        Returns:
            Position size (quantity to buy/sell)
        """
        if stop_loss_price == 0 or entry_price == 0:
            return 0

        # Calculate risk amount in dollars
        risk_amount = account_balance * (risk_per_trade_percent / 100)

        # Calculate stop loss distance
        stop_loss_distance = abs(entry_price - stop_loss_price)

        # Calculate position size
        position_size = risk_amount / stop_loss_distance

        return position_size
