from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from src.state.perps_state_store import PerpsState

logger = logging.getLogger(__name__)


class PnLTracker:
    def __init__(self):
        self.peak_equity: float = 0.0
        self.daily_pnl: Dict[str, float] = {}
        self.consecutive_losses: int = 0
        self.trade_history: List[Dict] = []
        
    def update_peak_equity(self, current_equity: float) -> bool:
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
            logger.info(f"New peak equity: ${self.peak_equity:.2f}")
            return True
        return False
    
    def get_drawdown(self, current_equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - current_equity) / self.peak_equity
    
    def record_trade(self, pnl: float, timestamp: Optional[datetime] = None) -> None:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        date_key = timestamp.strftime("%Y-%m-%d")
        
        if date_key not in self.daily_pnl:
            self.daily_pnl[date_key] = 0.0
        
        self.daily_pnl[date_key] += pnl
        
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        self.trade_history.append({
            "timestamp": timestamp,
            "pnl": pnl,
            "date": date_key,
        })
        
        logger.info(
            f"Trade recorded: PnL=${pnl:.2f} | Daily PnL=${self.daily_pnl[date_key]:.2f} | "
            f"Consecutive losses={self.consecutive_losses}"
        )
    
    def get_daily_pnl(self, date: Optional[str] = None) -> float:
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.daily_pnl.get(date, 0.0)
    
    def cleanup_old_days(self, days_to_keep: int = 30) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        cutoff_key = cutoff.strftime("%Y-%m-%d")
        
        keys_to_remove = [k for k in self.daily_pnl.keys() if k < cutoff_key]
        for key in keys_to_remove:
            del self.daily_pnl[key]
        
        if keys_to_remove:
            logger.debug(f"Cleaned up {len(keys_to_remove)} old daily PnL records")

    def to_state(self) -> PerpsState:
        return PerpsState(
            peak_equity=self.peak_equity,
            daily_pnl_by_date=dict(self.daily_pnl),
            consecutive_losses=self.consecutive_losses,
        )

    def load_state(self, state: PerpsState) -> None:
        self.peak_equity = state.peak_equity
        self.daily_pnl = dict(state.daily_pnl_by_date)
        self.consecutive_losses = state.consecutive_losses
