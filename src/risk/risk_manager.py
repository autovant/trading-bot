from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from src.state.daily_pnl_store import DailyPnlStore


@dataclass
class RiskManager:
    """
    Lightweight, in-memory risk gate that tracks open exposure and realized PnL.

    Percent-based thresholds are expressed as decimals (e.g. 0.02 == 2%).
    """

    starting_equity: float
    max_account_risk_pct: float
    max_open_risk_pct: float
    max_symbol_risk_pct: float
    max_daily_loss_usd: Optional[float] = None
    daily_pnl_store: Optional[DailyPnlStore] = None
    account_id: Optional[str] = None
    current_equity: float = 0.0
    realized_pnl: float = 0.0
    open_risk_by_symbol: Dict[str, float] = field(default_factory=dict)
    daily_pnl_usd: float = 0.0

    def __post_init__(self) -> None:
        self.current_equity = max(self.current_equity, self.starting_equity)
        self.daily_pnl_usd = self._load_current_daily_pnl()

    @property
    def total_open_risk(self) -> float:
        return sum(self.open_risk_by_symbol.values())

    def update_equity(self, equity: float) -> None:
        if equity > 0:
            self.current_equity = equity

    def register_open_position(
        self, symbol: str, notional: float, per_trade_risk_pct: float
    ) -> None:
        """Track incremental open risk for a symbol."""
        symbol_key = symbol.upper()
        risk_value = self._risk_value(notional, per_trade_risk_pct)
        self.open_risk_by_symbol[symbol_key] = (
            self.open_risk_by_symbol.get(symbol_key, 0.0) + risk_value
        )

    def register_close_position(self, symbol: str, realized_pnl: float) -> None:
        """Reduce open risk for a symbol and aggregate realized PnL."""
        symbol_key = symbol.upper()
        self.realized_pnl += realized_pnl
        self.open_risk_by_symbol.pop(symbol_key, None)
        self._update_daily_pnl(realized_pnl)

    def can_open_new_position(
        self, symbol: str, proposed_notional: float, proposed_risk_pct: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check whether a new position is allowed.

        Returns (allowed, reason). The `reason` is None when allowed.
        """

        equity = self.current_equity or self.starting_equity
        if equity <= 0:
            return False, "missing_equity"

        proposed_risk = self._risk_value(proposed_notional, proposed_risk_pct)
        open_risk_limit = equity * self.max_open_risk_pct
        symbol_key = symbol.upper()
        symbol_open_risk = self.open_risk_by_symbol.get(symbol_key, 0.0)

        if (
            self.max_daily_loss_usd is not None
            and self.daily_pnl_usd <= -self.max_daily_loss_usd
        ):
            return False, "max_daily_loss_usd"

        if self.starting_equity > 0:
            loss_pct = max(-self.realized_pnl, 0) / self.starting_equity
            if loss_pct >= self.max_account_risk_pct:
                return False, "max_account_risk_pct"

        if self.total_open_risk + proposed_risk > open_risk_limit:
            return False, "max_open_risk_pct"

        symbol_limit = equity * self.max_symbol_risk_pct
        if symbol_open_risk + proposed_risk > symbol_limit:
            return False, "max_symbol_risk_pct"

        return True, None

    @staticmethod
    def _risk_value(notional: float, risk_pct: float) -> float:
        notional_abs = abs(notional)
        pct = max(risk_pct, 0.0)
        return notional_abs * pct

    def _update_daily_pnl(self, delta_pnl: float) -> None:
        date_key = self._current_date_key()
        if self.daily_pnl_store and self.account_id:
            self.daily_pnl_usd = self.daily_pnl_store.update_pnl(
                self.account_id, date_key, delta_pnl
            )
        else:
            self.daily_pnl_usd += delta_pnl

    def _load_current_daily_pnl(self) -> float:
        if self.daily_pnl_store and self.account_id:
            return self.daily_pnl_store.get_pnl(self.account_id, self._current_date_key())
        return 0.0

    @staticmethod
    def _current_date_key() -> str:
        return datetime.datetime.utcnow().strftime("%Y-%m-%d")
