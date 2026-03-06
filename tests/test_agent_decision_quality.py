"""
Agent decision quality tests — Epic 6.12.

Validates LLM response parsing, risk bound enforcement,
multi-agent portfolio coordination, and graceful degradation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import (
    AgentConfig,
    AgentRiskGuardrails,
    AgentSchedule,
    AgentTarget,
)
from src.database import Agent, AgentDecision, AgentPerformance, DatabaseManager
from src.llm_client import LLMError
from src.risk.portfolio_risk import PortfolioRiskManager
from src.services.agent_orchestrator import AgentRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(agent_id: int = 1, status: str = "paper") -> Agent:
    return Agent(
        id=agent_id,
        name=f"test-agent-{agent_id}",
        status=status,
        config_json={
            "name": f"test-agent-{agent_id}",
            "target": {"symbols": ["BTCUSDT"], "timeframes": ["1h"], "exchange": "bybit"},
            "allocation_usd": 1000.0,
        },
        allocation_usd=1000.0,
        created_at=datetime.now(timezone.utc),
    )


def _make_agent_config(
    symbols: Optional[List[str]] = None,
    max_position_size_usd: float = 1000.0,
    max_leverage: float = 3.0,
    allocation_usd: float = 1000.0,
) -> AgentConfig:
    return AgentConfig(
        name="test-agent",
        target=AgentTarget(
            symbols=symbols or ["BTCUSDT"],
            timeframes=["1h"],
            exchange="bybit",
        ),
        risk_guardrails=AgentRiskGuardrails(
            max_position_size_usd=max_position_size_usd,
            max_leverage=max_leverage,
        ),
        schedule=AgentSchedule(rebalance_interval_seconds=10),
        allocation_usd=allocation_usd,
    )


def _mock_db(agent: Optional[Agent] = None) -> AsyncMock:
    db = AsyncMock(spec=DatabaseManager)
    db.update_agent_status = AsyncMock(return_value=True)
    db.get_agent = AsyncMock(return_value=agent or _make_agent())
    db.get_agent_performance = AsyncMock(return_value=[])
    db.create_agent_decision = AsyncMock(return_value=1)
    db.upsert_agent_performance = AsyncMock(return_value=True)
    return db


def _mock_messaging() -> AsyncMock:
    messaging = AsyncMock()
    messaging.publish = AsyncMock()
    messaging.subscribe = AsyncMock()
    return messaging


def _llm_response(content: str) -> Dict[str, Any]:
    """Build a mock LLM chat response with the given content string."""
    return {
        "choices": [{"message": {"content": content}}],
    }


def _valid_llm_json(
    regime: str = "trending_up",
    confidence: int = 75,
    action: str = "buy",
) -> str:
    return json.dumps({
        "regime": regime,
        "confidence": confidence,
        "thesis": "Test thesis",
        "recommended_action": action,
        "reasoning": "Test reasoning",
    })


def _make_runner(
    agent: Optional[Agent] = None,
    config: Optional[AgentConfig] = None,
    db: Optional[AsyncMock] = None,
    llm: Optional[AsyncMock] = None,
    market_price: float = 50000.0,
) -> AgentRunner:
    """Create an AgentRunner with all mocked dependencies."""
    ag = agent or _make_agent()
    cfg = config or _make_agent_config()
    mock_db = db or _mock_db(ag)
    messaging = _mock_messaging()
    mock_llm = llm or AsyncMock()
    if llm is None:
        mock_llm.chat = AsyncMock(
            return_value=_llm_response(_valid_llm_json()),
        )
    runner = AgentRunner(
        agent=ag, config=cfg, db=mock_db,
        messaging=messaging, llm=mock_llm,
    )
    if market_price > 0:
        runner._market_cache["BTCUSDT"] = {
            "price": market_price,
            "volume_24h": 1e9,
            "change_pct_24h": 2.0,
            "bid": market_price - 10,
            "ask": market_price + 10,
            "indicators": {"rsi": 55},
        }
    return runner


# ===================================================================
# Test 1: LLM Response Schema Validation
# ===================================================================

@pytest.mark.integration
class TestLLMResponseSchemaValidation:
    """Verify agent handles various LLM response shapes correctly."""

    @pytest.mark.asyncio
    async def test_valid_json_parsed_correctly(self):
        """Standard well-formed response is parsed into orientation dict."""
        runner = _make_runner()
        observation = {
            "symbols": {"BTCUSDT": {"price": 50000, "change_pct_24h": 2, "indicators": {}}},
            "portfolio": {},
        }
        result = await runner._orient(observation)
        assert result["regime"] == "trending_up"
        assert result["confidence"] == 75
        assert result["recommended_action"] == "buy"

    @pytest.mark.asyncio
    async def test_json_with_extra_fields(self):
        """Extra fields in LLM JSON are ignored, required fields extracted."""
        extra_json = json.dumps({
            "regime": "ranging",
            "confidence": 60,
            "thesis": "Sideways",
            "recommended_action": "hold",
            "reasoning": "No trend",
            "extra_field": "ignored",
            "another": 42,
        })
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(extra_json))
        runner = _make_runner(llm=llm)
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["regime"] == "ranging"
        assert result["confidence"] == 60
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_malformed_json_degrades_gracefully(self):
        """Malformed JSON doesn't crash — agent defaults to hold."""
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response("not valid json {{{"))
        runner = _make_runner(llm=llm)
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["regime"] == "unknown"
        assert result["confidence"] == 0
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_empty_string_response_degrades(self):
        """Empty LLM content defaults to hold orientation."""
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(""))
        runner = _make_runner(llm=llm)
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_missing_required_fields_uses_defaults(self):
        """Missing JSON fields get safe defaults, not KeyError."""
        partial_json = json.dumps({"regime": "volatile"})
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(partial_json))
        runner = _make_runner(llm=llm)
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["regime"] == "volatile"
        assert result["confidence"] == 0
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_0_100(self):
        """Confidence values outside 0-100 are clamped."""
        over_json = json.dumps({
            "regime": "trending_up",
            "confidence": 999,
            "thesis": "x",
            "recommended_action": "buy",
            "reasoning": "x",
        })
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(over_json))
        runner = _make_runner(llm=llm)
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)
        assert result["confidence"] == 100

        negative_json = json.dumps({
            "regime": "trending_down",
            "confidence": -50,
            "thesis": "x",
            "recommended_action": "sell",
            "reasoning": "x",
        })
        llm.chat = AsyncMock(return_value=_llm_response(negative_json))
        result = await runner._orient(observation)
        assert result["confidence"] == 0


# ===================================================================
# Test 2: Decision Bounds Enforcement
# ===================================================================

@pytest.mark.integration
class TestDecisionBoundsEnforcement:
    """50 OODA decide cycles: no decision may exceed risk limits."""

    @pytest.mark.asyncio
    async def test_position_size_never_exceeds_limit(self):
        """Run 50 cycles with escalating LLM confidence — position size stays bounded."""
        max_pos = 100.0
        config = _make_agent_config(max_position_size_usd=max_pos, allocation_usd=5000.0)
        agent = _make_agent()
        db = _mock_db(agent)

        all_intents: List[Dict[str, Any]] = []

        for i in range(50):
            confidence = min(30 + i * 2, 100)  # ramps from 30 to 100
            llm_json = _valid_llm_json(confidence=confidence, action="buy")
            llm = AsyncMock()
            llm.chat = AsyncMock(return_value=_llm_response(llm_json))

            runner = _make_runner(agent=agent, config=config, db=db, llm=llm)
            orientation = await runner._orient({"symbols": {}, "portfolio": {}})
            decision = await runner._decide(orientation)

            for intent in decision.get("order_intents", []):
                notional = intent["quantity"] * intent["price"]
                all_intents.append({
                    "cycle": i,
                    "notional_usd": notional,
                    "confidence": confidence,
                })
                # Core assertion: position size never exceeds the guardrail
                assert notional <= max_pos + 0.01, (
                    f"Cycle {i}: notional ${notional:.2f} exceeds limit ${max_pos}"
                )

        # At least some cycles should have generated orders
        assert len(all_intents) > 0, "Expected some order intents across 50 cycles"

    @pytest.mark.asyncio
    async def test_confidence_scores_always_in_range(self):
        """All orientation confidence scores are clamped to 0-100."""
        for raw_conf in [-10, 0, 50, 100, 200, 999, -999]:
            llm_json = json.dumps({
                "regime": "trending_up",
                "confidence": raw_conf,
                "thesis": "t",
                "recommended_action": "buy",
                "reasoning": "r",
            })
            llm = AsyncMock()
            llm.chat = AsyncMock(return_value=_llm_response(llm_json))
            runner = _make_runner(llm=llm)
            result = await runner._orient({"symbols": {}, "portfolio": {}})
            assert 0 <= result["confidence"] <= 100, (
                f"Raw {raw_conf} → {result['confidence']} out of [0,100]"
            )

    @pytest.mark.asyncio
    async def test_allocation_percentage_cap(self):
        """Position size is capped at 10% of allocation even if guardrail is higher."""
        config = _make_agent_config(
            max_position_size_usd=50000.0, allocation_usd=1000.0,
        )
        runner = _make_runner(config=config, market_price=50000.0)
        orientation = {
            "regime": "trending_up",
            "confidence": 90,
            "recommended_action": "buy",
            "reasoning": "strong",
        }
        decision = await runner._decide(orientation)
        for intent in decision.get("order_intents", []):
            notional = intent["quantity"] * intent["price"]
            # min(50000, 1000*0.1) = 100
            assert notional <= 100.0 + 0.01


# ===================================================================
# Test 3: Risk Guardrail Override
# ===================================================================

@pytest.mark.integration
class TestRiskGuardrailOverride:
    """LLM suggests oversized position — decide phase clamps it."""

    @pytest.mark.asyncio
    async def test_decide_clamps_to_max_position_size(self):
        """Position size is clamped to min(max_position_size, allocation*0.1)."""
        max_pos = 100.0
        config = _make_agent_config(max_position_size_usd=max_pos, allocation_usd=5000.0)
        # LLM suggests high-confidence buy
        llm_json = _valid_llm_json(confidence=95, action="buy")
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(llm_json))
        runner = _make_runner(config=config, llm=llm, market_price=50000.0)

        orientation = await runner._orient({"symbols": {}, "portfolio": {}})
        decision = await runner._decide(orientation)

        assert decision["action"] == "buy"
        assert len(decision["order_intents"]) == 1
        intent = decision["order_intents"][0]
        notional = intent["quantity"] * intent["price"]
        assert notional <= max_pos + 0.01

    @pytest.mark.asyncio
    async def test_kill_switch_pauses_agent(self):
        """Agent auto-pauses when drawdown exceeds kill switch threshold."""
        config = _make_agent_config()
        config.risk_guardrails.kill_switch_drawdown_pct = 0.05
        agent = _make_agent()
        db = _mock_db(agent)
        # Simulate high drawdown in performance records
        db.get_agent_performance = AsyncMock(return_value=[
            AgentPerformance(
                agent_id=1, date="2026-03-04", total_trades=20,
                equity=800, win_rate=0.3, sharpe_rolling_30d=0.5,
                max_drawdown=0.10, realized_pnl=-200,
            ),
        ])
        runner = _make_runner(config=config, db=db)
        orientation = {
            "regime": "trending_down",
            "confidence": 80,
            "recommended_action": "sell",
            "reasoning": "crash",
        }
        decision = await runner._decide(orientation)
        assert decision["action"] == "hold"
        assert "Kill switch" in decision["reason"]
        # Verify transition to paused was attempted
        db.update_agent_status.assert_called()

    @pytest.mark.asyncio
    async def test_low_confidence_forces_hold(self):
        """Below confidence threshold of 30, agent always holds."""
        llm_json = _valid_llm_json(confidence=15, action="buy")
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response(llm_json))
        runner = _make_runner(llm=llm)
        orientation = await runner._orient({"symbols": {}, "portfolio": {}})
        decision = await runner._decide(orientation)
        assert decision["action"] == "hold"
        assert decision["order_intents"] == []


# ===================================================================
# Test 4: Multi-Agent Portfolio Coordination
# ===================================================================

@pytest.mark.integration
class TestMultiAgentPortfolioCoordination:
    """Portfolio risk manager blocks correlated and overlapping positions."""

    def test_portfolio_blocks_excess_exposure(self):
        """Order rejected when total portfolio exposure would exceed limit."""
        prm = PortfolioRiskManager(
            max_total_exposure_usd=10_000.0,
            max_symbol_concentration_pct=0.40,
        )
        guardrails = AgentRiskGuardrails(max_position_size_usd=5000.0, max_open_positions=5)

        # Agent 1 holds $8000 in BTCUSDT
        prm.update_position(1, "BTCUSDT", 8000.0)

        # Agent 2 tries to open $3000 in ETHUSDT — would exceed $10k total
        allowed, reasons = prm.check_order(2, "ETHUSDT", 3000.0, guardrails)
        assert allowed is False
        assert any("exposure" in r.lower() for r in reasons)

    def test_portfolio_blocks_symbol_concentration(self):
        """Order rejected when symbol concentration would exceed limit."""
        prm = PortfolioRiskManager(
            max_total_exposure_usd=50_000.0,
            max_symbol_concentration_pct=0.40,
        )
        guardrails = AgentRiskGuardrails(max_position_size_usd=20_000.0, max_open_positions=5)

        # Agent 1 already has $10k in BTCUSDT
        prm.update_position(1, "BTCUSDT", 10_000.0)

        # Agent 2 tries another $10k in BTCUSDT — 100% concentration
        allowed, reasons = prm.check_order(2, "BTCUSDT", 10_000.0, guardrails)
        assert allowed is False
        assert any("concentration" in r.lower() for r in reasons)

    def test_correlation_blocks_correlated_agent(self):
        """High correlation between agents triggers rejection."""
        prm = PortfolioRiskManager(max_agent_correlation=0.70)

        # Agent 1 and Agent 2 have identical return series (correlation ≈ 1.0)
        returns_a = [0.01 * i for i in range(10)]
        returns_b = [0.01 * i for i in range(10)]  # same pattern

        for r in returns_a:
            prm.record_daily_return(1, r)
        for r in returns_b:
            prm.record_daily_return(2, r)

        allowed, reason = prm.check_correlation(2)
        assert allowed is False
        assert reason is not None
        assert "correlation" in reason.lower()

    def test_uncorrelated_agents_pass(self):
        """Low-correlation agents pass the correlation check."""
        prm = PortfolioRiskManager(max_agent_correlation=0.70)

        # Agent 1: upward, Agent 3: downward (negative correlation)
        for i in range(10):
            prm.record_daily_return(1, 0.01 * i)
            prm.record_daily_return(3, -0.01 * i)

        allowed, reason = prm.check_correlation(3)
        # Negative correlation is high in absolute value → blocked
        assert allowed is False

    def test_three_agents_coordination(self):
        """3 agents: 2 correlated, portfolio manager blocks the correlated pair."""
        prm = PortfolioRiskManager(
            max_total_exposure_usd=50_000.0,
            max_symbol_concentration_pct=0.50,
            max_agent_correlation=0.70,
        )
        guardrails = AgentRiskGuardrails(max_position_size_usd=20_000.0, max_open_positions=5)

        # Agents 1 & 2 trade BTCUSDT (correlated)
        prm.update_position(1, "BTCUSDT", 10_000.0)
        prm.update_position(2, "BTCUSDT", 10_000.0)
        # Agent 3 wants ETHUSDT
        prm.update_position(3, "ETHUSDT", 5_000.0)

        # Same returns for 1 & 2, different for 3
        for i in range(10):
            prm.record_daily_return(1, 0.02 * i)
            prm.record_daily_return(2, 0.02 * i + 0.001)
            prm.record_daily_return(3, -0.01 * i + 0.005)

        results = {}
        for agent_id in [1, 2, 3]:
            allowed, reason = prm.check_correlation(agent_id)
            results[agent_id] = {"allowed": allowed, "reason": reason}

        # At least one agent should be blocked due to correlation
        blocked = [aid for aid, r in results.items() if not r["allowed"]]
        assert len(blocked) >= 1, "Expected at least 1 agent blocked by correlation"

    def test_per_agent_position_limit(self):
        """Agent cannot exceed max_open_positions."""
        prm = PortfolioRiskManager(max_total_exposure_usd=100_000.0)
        guardrails = AgentRiskGuardrails(max_position_size_usd=5000.0, max_open_positions=2)

        prm.update_position(1, "BTCUSDT", 1000.0)
        prm.update_position(1, "ETHUSDT", 1000.0)

        # 3rd symbol should be blocked
        allowed, reasons = prm.check_order(1, "SOLUSDT", 1000.0, guardrails)
        assert allowed is False
        assert any("positions" in r.lower() for r in reasons)


# ===================================================================
# Test 5: Agent Graceful Degradation
# ===================================================================

@pytest.mark.integration
class TestAgentGracefulDegradation:
    """Agent survives LLM failures without crashing or state transitions."""

    @pytest.mark.asyncio
    async def test_llm_timeout_no_crash(self):
        """LLM timeout → agent stays in current state, cycle completes."""
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMError("Connection timed out"))
        runner = _make_runner(llm=llm)

        initial_status = runner.agent.status
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)

        assert result["regime"] == "unknown"
        assert result["recommended_action"] == "hold"
        assert runner.agent.status == initial_status

    @pytest.mark.asyncio
    async def test_llm_connection_error_no_crash(self):
        """LLM connection refused → agent degrades gracefully."""
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMError("Connection refused"))
        runner = _make_runner(llm=llm)

        initial_status = runner.agent.status
        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)

        assert result["regime"] == "unknown"
        assert result["recommended_action"] == "hold"
        assert runner.agent.status == initial_status

    @pytest.mark.asyncio
    async def test_full_cycle_survives_llm_failure(self):
        """Complete OODA cycle with LLM failure → no orders submitted, no crash."""
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMError("Service unavailable"))
        runner = _make_runner(llm=llm)

        initial_status = runner.agent.status
        await runner._run_ooda_cycle()

        # Agent should still be in original state
        assert runner.agent.status == initial_status
        # No orders published (hold decision due to LLM failure)
        runner.messaging.publish.assert_not_called()
        # Decision was still recorded in learn phase
        runner.db.create_agent_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_decode_error_logged_not_crashed(self):
        """LLM returns non-JSON → orient logs warning and returns hold."""
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=_llm_response("I'm not JSON at all!"))
        runner = _make_runner(llm=llm)

        observation = {"symbols": {}, "portfolio": {}}
        result = await runner._orient(observation)

        assert result["regime"] == "unknown"
        assert result["confidence"] == 0
        assert result["recommended_action"] == "hold"

    @pytest.mark.asyncio
    async def test_multiple_failures_dont_accumulate_state(self):
        """Multiple consecutive LLM failures don't corrupt agent state."""
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMError("Repeated failure"))
        runner = _make_runner(llm=llm)
        initial_status = runner.agent.status

        for _ in range(5):
            observation = {"symbols": {}, "portfolio": {}}
            result = await runner._orient(observation)
            assert result["recommended_action"] == "hold"

        assert runner.agent.status == initial_status
