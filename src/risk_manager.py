import logging
from typing import Any, Dict

from src.config import TradingBotConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Manages risk controls, crisis mode, and daily limits.
    """

    def __init__(self, config: TradingBotConfig, initial_capital: float = 10000.0):
        self.config = config
        self.peak_equity = initial_capital
        self.crisis_mode = False
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.peak_equity = 0.0
        self.consecutive_losses = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_trades = 0

    async def check_risk_management(
        self, current_equity: float, active_positions_count: int = 0
    ) -> Dict[str, bool]:
        """
        Check and enforce risk management rules.
        Returns a dict of actions that should be taken (e.g., {'close_all': True}).
        """
        actions = {"close_all": False, "halt_trading": False}

        try:
            # Update peak equity
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity

            # Calculate Drawdown
            current_drawdown = (
                (self.peak_equity - current_equity) / self.peak_equity
                if self.peak_equity > 0
                else 0
            )

            # Check crisis mode triggers
            crisis_triggers = [
                current_drawdown
                > self.config.risk_management.crisis_mode.drawdown_threshold,
                self.consecutive_losses
                >= self.config.risk_management.crisis_mode.consecutive_losses,
            ]

            if any(crisis_triggers):
                if not self.crisis_mode:
                    await self._activate_crisis_mode()
                # Enforce crisis actions
                actions["halt_trading"] = True
                actions["close_all"] = True
                return actions # Immediate return
            
            elif not any(crisis_triggers) and self.crisis_mode:
                await self._deactivate_crisis_mode()

            # Check daily risk limits
            # Assuming daily_pnl is updated externally or via update_pnl
            if (
                abs(self.daily_pnl)
                > current_equity * self.config.trading.max_daily_risk
            ):
                if self.daily_pnl < 0:  # Only stop if it's a LOSS
                    logger.warning(
                        "Daily risk limit exceeded, recommending close all positions"
                    )
                    actions["close_all"] = True
                    actions["halt_trading"] = True # Daily limit also halts

            return actions

        except Exception as e:
            logger.error(f"Error checking risk management: {e}")
            return actions

    async def _activate_crisis_mode(self):
        """Activate crisis mode."""
        self.crisis_mode = True
        logger.warning("CRISIS MODE ACTIVATED")

    async def _deactivate_crisis_mode(self):
        """Deactivate crisis mode."""
        self.crisis_mode = False
        logger.info("Crisis mode deactivated")

    def update_trade_stats(self, pnl: float):
        """Update stats after a closed trade."""
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.total_trades += 1

        if pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Return current risk state metrics."""
        return {
            "crisis_mode": self.crisis_mode,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "consecutive_losses": self.consecutive_losses,
            "peak_equity": self.peak_equity,
            "win_rate": (self.winning_trades / self.total_trades)
            if self.total_trades > 0
            else 0,
        }
