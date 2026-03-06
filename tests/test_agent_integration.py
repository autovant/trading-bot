"""
Integration tests for the agent lifecycle.

Tests the full agent lifecycle: create → backtest gate → paper gate → live,
with mocked external dependencies (LLM, exchange).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    AgentBacktestRequirements,
    AgentConfig,
    AgentPaperRequirements,
    AgentTarget,
)
from src.database import Agent, AgentPerformance
from src.services.agent_orchestrator import (
    AgentOrchestratorService,
    AgentStateMachine,
    BacktestGate,
    PaperGate,
)


def _mock_db():
    db = AsyncMock()
    db.update_agent_status = AsyncMock(return_value=True)
    db.create_agent = AsyncMock(return_value=1)
    db.get_agent = AsyncMock()
    db.get_agent_performance = AsyncMock(return_value=[])
    db.create_agent_decision = AsyncMock(return_value=1)
    db.upsert_agent_performance = AsyncMock(return_value=True)
    return db


# ---------------------------------------------------------------------------
# Full Agent Lifecycle
# ---------------------------------------------------------------------------

class TestAgentLifecycle:
    """Integration: create → backtesting → paper → live → retire."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_happy_path(self):
        db = _mock_db()
        messaging = AsyncMock()
        messaging.publish = AsyncMock()

        # 1. Created → Backtesting
        db.get_agent.return_value = Agent(
            id=1, name="lifecycle-agent", status="created",
            config_json={"name": "lifecycle-agent", "target": {"symbols": ["BTCUSDT"], "timeframes": ["1h"], "exchange": "bybit"}, "allocation_usd": 1000},
            allocation_usd=1000, created_at=datetime.now(timezone.utc),
        )
        ok = await AgentStateMachine.transition(db, 1, "created", "backtesting", messaging)
        assert ok is True

        # 2. Backtest gate passes
        results = {"sharpe_ratio": 2.0, "profit_factor": 2.0, "max_drawdown": 0.05, "total_trades": 100, "win_rate": 0.60}
        requirements = AgentBacktestRequirements()
        passed, failures = BacktestGate.evaluate(results, requirements)
        assert passed is True

        # 3. Backtesting → Paper
        ok = await AgentStateMachine.transition(db, 1, "backtesting", "paper", messaging)
        assert ok is True

        # 4. Paper gate passes (enough days + trades)
        db.get_agent_performance.return_value = [
            AgentPerformance(agent_id=1, date=f"2025-01-{i+1:02d}", total_trades=3, equity=1000+i*10, win_rate=0.6, sharpe_rolling_30d=1.5, max_drawdown=0.05, realized_pnl=10)
            for i in range(14)
        ]
        paper_reqs = AgentPaperRequirements(min_days=14, min_trades=10)
        passed, failures = await PaperGate.evaluate(db, 1, paper_reqs)
        assert passed is True

        # 5. Paper → Live
        ok = await AgentStateMachine.transition(db, 1, "paper", "live", messaging)
        assert ok is True

        # 6. Live → Paused
        ok = await AgentStateMachine.transition(db, 1, "live", "paused", messaging)
        assert ok is True

        # 7. Paused → Retired
        ok = await AgentStateMachine.transition(db, 1, "paused", "retired", messaging)
        assert ok is True

    @pytest.mark.asyncio
    async def test_lifecycle_blocked_by_backtest_gate(self):
        db = _mock_db()

        # Bad backtest results — should NOT proceed to paper
        results = {"sharpe_ratio": 0.3, "profit_factor": 0.8, "max_drawdown": 0.30, "total_trades": 5, "win_rate": 0.20}
        requirements = AgentBacktestRequirements()
        passed, failures = BacktestGate.evaluate(results, requirements)
        assert passed is False
        assert len(failures) >= 3

        # Agent should stay in backtesting since gate failed
        ok = AgentStateMachine.can_transition("backtesting", "paper")
        assert ok is True  # transition is technically valid
        # But the orchestrator won't trigger it because gate failed

    @pytest.mark.asyncio
    async def test_lifecycle_blocked_by_paper_gate(self):
        db = _mock_db()

        # Only 3 days of paper data — not enough
        db.get_agent_performance.return_value = [
            AgentPerformance(agent_id=1, date=f"2025-01-{i+1:02d}", total_trades=1, equity=1000, win_rate=0.5, sharpe_rolling_30d=1.0, max_drawdown=0.05, realized_pnl=5)
            for i in range(3)
        ]
        paper_reqs = AgentPaperRequirements(min_days=14, min_trades=10)
        passed, failures = await PaperGate.evaluate(db, 1, paper_reqs)
        assert passed is False

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self):
        db = _mock_db()

        # Cannot go directly from created → live (skipping backtest + paper)
        ok = await AgentStateMachine.transition(db, 1, "created", "live")
        assert ok is False
        db.update_agent_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_retired_agent_cannot_restart(self):
        db = _mock_db()

        # Retired is a terminal state
        ok = await AgentStateMachine.transition(db, 1, "retired", "backtesting")
        assert ok is False
        ok = await AgentStateMachine.transition(db, 1, "retired", "live")
        assert ok is False
        ok = await AgentStateMachine.transition(db, 1, "retired", "paused")
        assert ok is False
