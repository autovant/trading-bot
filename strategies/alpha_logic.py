from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import polars as pl

from src.strategies.dynamic_engine import DynamicStrategyEngine


@dataclass
class StrategyEnvelope:
    """Lightweight wrapper for JSON-defined strategies."""

    name: str
    triggers: List[Dict[str, Any]]
    logic: str = "AND"
    risk: Dict[str, Any] = field(
        default_factory=lambda: {
            "initial_capital": 100_000,
            "risk_per_trade_pct": 1.0,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
        }
    )

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "triggers": self.triggers, "logic": self.logic, "risk": self.risk}


class JSONStrategyRunner:
    """
    Stateless-ish runner that can evaluate a JSON strategy incrementally (on_candle)
    and delegate full backtests to DynamicStrategyEngine.
    """

    def __init__(self, strategy: StrategyEnvelope, engine: Optional[DynamicStrategyEngine] = None):
        self.strategy = strategy
        self.engine = engine or DynamicStrategyEngine()
        self.history: List[Dict[str, Any]] = []
        self.position = 0.0
        self.entry_price = 0.0
        self.cash = float(strategy.risk.get("initial_capital", 100_000))

    async def backtest(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        optimization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self.engine.run_backtest(
            self.strategy.as_dict(),
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            optimization=optimization,
        )

    def on_candle(self, candle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluate the JSON strategy on a streaming candle.
        Returns an order suggestion dict or None.
        """
        self.history.append(candle)
        if len(self.history) < 10:
            return None

        df = pl.DataFrame(self.history)
        trigger_df = self.engine._evaluate_triggers(df, self.strategy.triggers)
        signals = self.engine._combine_logic(trigger_df, self.strategy.logic)
        if len(signals) == 0:
            return None

        latest_signal = bool(signals[-1])
        price = float(candle["close"])
        risk = self.strategy.risk
        stop_loss_pct = float(risk.get("stop_loss_pct", 1.0)) / 100.0
        take_profit_pct = float(risk.get("take_profit_pct", 2.0)) / 100.0

        if latest_signal and self.position == 0:
            stop_price = price * (1 - stop_loss_pct)
            qty = self.engine._position_size(
                self.cash,
                float(risk.get("risk_per_trade_pct", 1.0)),
                price,
                stop_price,
            )
            if qty <= 0:
                return None
            self.position = qty
            self.entry_price = price
            self.cash -= qty * price
            return {
                "action": "buy",
                "price": price,
                "amount": qty,
                "stop_loss": stop_price,
                "take_profit": price * (1 + take_profit_pct),
            }

        if not latest_signal and self.position > 0:
            proceeds = self.position * price
            pnl = self.position * (price - self.entry_price)
            closed = self.position
            self.cash += proceeds
            self.position = 0
            self.entry_price = 0
            return {"action": "sell", "price": price, "amount": closed, "pnl": pnl}

        return None


class VolatilityBreakoutStrategy(JSONStrategyRunner):
    """
    Legacy-friendly alias that now uses the JSON engine under the hood.
    Default logic: close > upper Bollinger band AND RSI < 70 on 5m bars.
    """

    def __init__(self):
        default_strategy = StrategyEnvelope(
            name="Volatility Breakout",
            triggers=[
                {
                    "indicator": "bollinger",
                    "timeframe": "5m",
                    "operator": ">",
                    "value": 0,  # value ignored when compare_to is set
                    "params": {"period": 20, "std": 2.0, "field": "close", "compare_to": "upper"},
                },
                {
                    "indicator": "rsi",
                    "timeframe": "5m",
                    "operator": "<",
                    "value": 70,
                    "params": {"period": 14},
                },
            ],
            logic="AND",
            risk={
                "initial_capital": 10000,
                "risk_per_trade_pct": 1.0,
                "stop_loss_pct": 1.0,
                "take_profit_pct": 2.0,
            },
        )
        super().__init__(default_strategy)
