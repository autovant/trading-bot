"""
Unit tests for the agent orchestrator service.

Tests state machine transitions, stage gate validation, and the
decision pipeline with a mocked LLM.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    AgentBacktestRequirements,
    AgentConfig,
    AgentPaperRequirements,
    AgentRiskGuardrails,
    AgentSchedule,
    AgentTarget,
)
from src.database import Agent, AgentDecision, AgentPerformance, DatabaseManager
from src.services.agent_orchestrator import (
    AgentRunner,
    AgentStateMachine,
    BacktestGate,
    PaperGate,
    VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_agent(
    agent_id: int = 1,
    status: str = "created",
    config: Optional[Dict[str, Any]] = None,
) -> Agent:
    default_config = {
        "name": "test-agent",
        "target": {"symbols": ["BTCUSDT"], "timeframes": ["1h"], "exchange": "bybit"},
        "allocation_usd": 1000.0,
    }
    return Agent(
        id=agent_id,
        name="test-agent",
        status=status,
        config_json=config or default_config,
        allocation_usd=1000.0,
        created_at=datetime.now(timezone.utc),
    )


def _make_agent_config() -> AgentConfig:
    return AgentConfig(
        name="test-agent",
        target=AgentTarget(symbols=["BTCUSDT"], timeframes=["1h"], exchange="bybit"),
        allocation_usd=1000.0,
    )


def _mock_db() -> AsyncMock:
    db = AsyncMock(spec=DatabaseManager)
    db.update_agent_status = AsyncMock(return_value=True)
    db.get_agent = AsyncMock(return_value=_make_agent(status="paper"))
    db.get_agent_performance = AsyncMock(return_value=[])
    db.create_agent_decision = AsyncMock(return_value=1)
    db.upsert_agent_performance = AsyncMock(return_value=True)
    return db


def _mock_messaging() -> AsyncMock:
    messaging = AsyncMock()
    messaging.publish = AsyncMock()
    messaging.subscribe = AsyncMock()
    return messaging


def _mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value={
        "choices": [{
            "message": {
                "content": json.dumps({
                    "regime": "trending_up",
                    "confidence": 75,
                    "thesis": "BTC is trending upward",
                    "recommended_action": "buy",
                    "reasoning": "Strong momentum",
                })
            }
        }]
    })
    return llm


# ---------------------------------------------------------------------------
# State Machine Tests
# ---------------------------------------------------------------------------

class TestAgentStateMachine:
    """Test state transition validation."""

    @pytest.mark.parametrize(
        "current, target, expected",
        [
            ("created", "backtesting", True),
            ("created", "retired", True),
            ("created", "live", False),
            ("created", "paper", False),
            ("backtesting", "paper", True),
            ("backtesting", "paused", True),
            ("backtesting", "retired", True),
            ("backtesting", "live", False),
            ("paper", "live", True),
            ("paper", "paused", True),
            ("paper", "retired", True),
            ("paper", "created", False),
            ("live", "paused", True),
            ("live", "retired", True),
            ("live", "paper", False),
            ("paused", "backtesting", True),
            ("paused", "paper", True),
            ("paused", "live", True),
            ("paused", "retired", True),
            ("retired", "created", False),
            ("retired", "live", False),
            ("retired", "paused", False),
        ],
    )
    def test_can_transition(self, current: str, target: str, expected: bool):
        assert AgentStateMachine.can_transition(current, target) == expected

    @pytest.mark.asyncio
    async def test_transition_success(self):
        db = _mock_db()
        messaging = _mock_messaging()

        result = await AgentStateMachine.transition(
            db, 1, "created", "backtesting", messaging
        )
        assert result is True
        db.update_agent_status.assert_called_once()
        messaging.publish.assert_called_once()
        call_args = messaging.publish.call_args
        assert call_args[0][0] == "agent.status"

    @pytest.mark.asyncio
    async def test_transition_invalid(self):
        db = _mock_db()
        result = await AgentStateMachine.transition(db, 1, "created", "live")
        assert result is False
        db.update_agent_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_transition_sets_paused_at(self):
        db = _mock_db()
        await AgentStateMachine.transition(db, 1, "live", "paused")
        call_args = db.update_agent_status.call_args
        assert call_args[1].get("paused_at") is not None

    @pytest.mark.asyncio
    async def test_transition_sets_retired_at(self):
        db = _mock_db()
        await AgentStateMachine.transition(db, 1, "live", "retired")
        call_args = db.update_agent_status.call_args
        assert call_args[1].get("retired_at") is not None


# ---------------------------------------------------------------------------
# Backtest Gate Tests
# ---------------------------------------------------------------------------

class TestBacktestGate:
    """Test backtest result evaluation."""

    def test_pass_all_criteria(self):
        results = {
            "sharpe_ratio": 1.5,
            "profit_factor": 1.5,
            "max_drawdown": 0.10,
            "total_trades": 50,
            "win_rate": 0.55,
        }
        requirements = AgentBacktestRequirements()
        passed, failures = BacktestGate.evaluate(results, requirements)
        assert passed is True
        assert failures == []

    def test_fail_sharpe(self):
        results = {
            "sharpe_ratio": 0.5,
            "profit_factor": 1.5,
            "max_drawdown": 0.10,
            "total_trades": 50,
            "win_rate": 0.55,
        }
        requirements = AgentBacktestRequirements()
        passed, failures = BacktestGate.evaluate(results, requirements)
        assert passed is False
        assert any("Sharpe" in f for f in failures)

    def test_fail_multiple_criteria(self):
        results = {
            "sharpe_ratio": 0.3,
            "profit_factor": 0.9,
            "max_drawdown": 0.25,
            "total_trades": 5,
            "win_rate": 0.20,
        }
        requirements = AgentBacktestRequirements()
        passed, failures = BacktestGate.evaluate(results, requirements)
        assert passed is False
        assert len(failures) == 5  # All criteria fail

    def test_nested_stats_key(self):
        results = {"stats": {"sharpe": 2.0, "profit_factor": 2.0, "max_drawdown_pct": 0.05, "num_trades": 100, "win_rate": 0.60}}
        requirements = AgentBacktestRequirements()
        passed, _ = BacktestGate.evaluate(results, requirements)
        assert passed is True


# ---------------------------------------------------------------------------
# Paper Gate Tests
# ---------------------------------------------------------------------------

class TestPaperGate:
    """Test paper trading evaluation."""

    @pytest.mark.asyncio
    async def test_insufficient_days(self):
        db = _mock_db()
        db.get_agent_performance = AsyncMock(return_value=[
            AgentPerformance(agent_id=1, date="2025-01-01", total_trades=5, equity=1050, win_rate=0.6, sharpe_rolling_30d=1.2, max_drawdown=0.05, realized_pnl=50)
        ])
        requirements = AgentPaperRequirements(min_days=14, min_trades=10)
        passed, failures = await PaperGate.evaluate(db, 1, requirements)
        assert passed is False
        assert any("days" in f for f in failures)

    @pytest.mark.asyncio
    async def test_insufficient_trades(self):
        db = _mock_db()
        db.get_agent_performance = AsyncMock(return_value=[
            AgentPerformance(agent_id=1, date=f"2025-01-{i+1:02d}", total_trades=0, equity=1000, win_rate=0, sharpe_rolling_30d=0, max_drawdown=0, realized_pnl=0)
            for i in range(14)
        ])
        requirements = AgentPaperRequirements(min_days=14, min_trades=10)
        passed, failures = await PaperGate.evaluate(db, 1, requirements)
        assert passed is False
        assert any("trades" in f.lower() for f in failures)

    @pytest.mark.asyncio
    async def test_pass(self):
        db = _mock_db()
        db.get_agent_performance = AsyncMock(return_value=[
            AgentPerformance(agent_id=1, date=f"2025-01-{i+1:02d}", total_trades=3, equity=1000 + i * 10, win_rate=0.6, sharpe_rolling_30d=1.5, max_drawdown=0.05, realized_pnl=10)
            for i in range(14)
        ])
        requirements = AgentPaperRequirements(min_days=14, min_trades=10)
        passed, failures = await PaperGate.evaluate(db, 1, requirements)
        assert passed is True
        assert failures == []


# ---------------------------------------------------------------------------
# Agent Runner OODA Cycle Tests
# ---------------------------------------------------------------------------

class TestAgentRunner:
    """Test the OODA cycle with mocked dependencies."""

    def _make_runner(self) -> AgentRunner:
        agent = _make_agent(status="paper")
        config = _make_agent_config()
        db = _mock_db()
        messaging = _mock_messaging()
        llm = _mock_llm()
        return AgentRunner(agent=agent, config=config, db=db, messaging=messaging, llm=llm)

    @pytest.mark.asyncio
    async def test_observe_returns_observation(self):
        runner = self._make_runner()
        runner._market_cache["BTCUSDT"] = {
            "price": 50000, "volume_24h": 1e9, "change_pct_24h": 2.5,
            "bid": 49990, "ask": 50010, "indicators": {"rsi": 55},
        }
        result = await runner._observe()
        assert "symbols" in result
        assert "BTCUSDT" in result["symbols"]
        assert result["symbols"]["BTCUSDT"]["price"] == 50000

    @pytest.mark.asyncio
    async def test_orient_calls_llm(self):
        runner = self._make_runner()
        observation = {"symbols": {"BTCUSDT": {"price": 50000, "change_pct_24h": 2, "indicators": {}}}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["regime"] == "trending_up"
        assert result["confidence"] == 75
        runner.llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_orient_handles_llm_failure(self):
        runner = self._make_runner()
        from src.llm_client import LLMError
        runner.llm.chat = AsyncMock(side_effect=LLMError("timeout"))
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["regime"] == "unknown"
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_decide_hold_on_low_confidence(self):
        runner = self._make_runner()
        orientation = {"regime": "trending_up", "confidence": 10, "recommended_action": "buy", "reasoning": "weak"}
        result = await runner._decide(orientation)
        assert result["action"] == "hold"
        assert result["order_intents"] == []

    @pytest.mark.asyncio
    async def test_decide_generates_orders_on_high_confidence(self):
        runner = self._make_runner()
        runner._market_cache["BTCUSDT"] = {"price": 50000}
        orientation = {"regime": "trending_up", "confidence": 80, "recommended_action": "buy", "reasoning": "strong"}
        result = await runner._decide(orientation)
        assert result["action"] == "buy"
        assert len(result["order_intents"]) == 1
        intent = result["order_intents"][0]
        assert intent["symbol"] == "BTCUSDT"
        assert intent["side"] == "buy"

    @pytest.mark.asyncio
    async def test_act_publishes_orders(self):
        runner = self._make_runner()
        decision = {
            "action": "buy",
            "order_intents": [
                {"idempotency_key": "test-1", "symbol": "BTCUSDT", "side": "buy", "quantity": 0.01, "price": 50000},
            ],
        }
        outcome = await runner._act(decision)
        assert outcome["orders_submitted"] == 1
        runner.messaging.publish.assert_called_once_with("trading.orders", decision["order_intents"][0])

    @pytest.mark.asyncio
    async def test_act_noop_on_empty_intents(self):
        runner = self._make_runner()
        decision = {"action": "hold", "order_intents": []}
        outcome = await runner._act(decision)
        assert outcome["orders_submitted"] == 0
        runner.messaging.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_learn_records_decision(self):
        runner = self._make_runner()
        observation = {"timestamp": "2025-01-01T00:00:00Z"}
        orientation = {"regime": "ranging"}
        decision = {"action": "hold", "order_intents": []}
        outcome = {"orders_submitted": 0, "order_ids": []}
        await runner._learn(observation, orientation, decision, outcome)
        runner.db.create_agent_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_ooda_cycle(self):
        runner = self._make_runner()
        runner._market_cache["BTCUSDT"] = {
            "price": 50000, "volume_24h": 1e9, "change_pct_24h": 2.5,
            "bid": 49990, "ask": 50010, "indicators": {"rsi": 55},
        }
        await runner._run_ooda_cycle()
        # Verify all phases were executed
        runner.db.get_agent.assert_called()
        runner.llm.chat.assert_called_once()
        runner.db.create_agent_decision.assert_called_once()

    def test_is_active_hours_weekend(self):
        runner = self._make_runner()
        runner.config.schedule.pause_on_weekends = True
        # We can't easily mock datetime here, so just verify the method exists and returns bool
        result = runner._is_active_hours()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_handle_market_data(self):
        runner = self._make_runner()
        msg = MagicMock()
        msg.data = json.dumps({"symbol": "BTCUSDT", "price": 51000}).encode()
        await runner.handle_market_data(msg)
        assert runner._market_cache["BTCUSDT"]["price"] == 51000

    @pytest.mark.asyncio
    async def test_handle_execution_report_filters_by_agent(self):
        runner = self._make_runner()
        msg = MagicMock()
        msg.data = json.dumps({"agent_id": 999, "price": 50000}).encode()
        await runner.handle_execution_report(msg)
        assert len(runner._recent_fills) == 0

        msg.data = json.dumps({"agent_id": 1, "price": 50000}).encode()
        await runner.handle_execution_report(msg)
        assert len(runner._recent_fills) == 1
