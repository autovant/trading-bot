"""Agent management API routes."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.database import (
    Agent,
    AgentDecision,
    AgentPerformance,
    DatabaseManager,
)

logger = logging.getLogger(__name__)

agents_router = APIRouter(prefix="/api/agents", tags=["agents"])

# Valid state transitions
VALID_TRANSITIONS = {
    "created": {"backtesting"},
    "backtesting": {"paper", "created", "paused", "retired"},
    "paper": {"live", "backtesting", "paused", "retired"},
    "live": {"paused", "retired"},
    "paused": {"backtesting", "paper", "live", "retired"},
}


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class AgentCreateRequest(BaseModel):
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)
    allocation_usd: float = Field(default=1000.0, ge=0)
    strategy_name: Optional[str] = None
    strategy_params: Optional[Dict[str, Any]] = None


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    allocation_usd: Optional[float] = Field(default=None, ge=0)
    strategy_name: Optional[str] = None
    strategy_params: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    status: str
    config: Dict[str, Any]
    allocation_usd: float
    strategy_name: Optional[str] = None
    strategy_params: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    paused_at: Optional[str] = None
    retired_at: Optional[str] = None


class AgentDecisionResponse(BaseModel):
    id: int
    agent_id: int
    timestamp: Optional[str] = None
    phase: str
    market_snapshot: Dict[str, Any]
    decision: Dict[str, Any]
    outcome: Dict[str, Any]
    trade_ids: List[str]


class AgentPerformanceResponse(BaseModel):
    agent_id: int
    date: Optional[str] = None
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int
    win_rate: float
    sharpe_rolling_30d: float
    max_drawdown: float
    equity: float


# ---------------------------------------------------------------------------
# Dependency — overridden at app startup
# ---------------------------------------------------------------------------

async def get_db() -> DatabaseManager:
    raise NotImplementedError


async def get_messaging():
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _audit_agent_transition(db: DatabaseManager, agent_id: int, old_status: str, new_status: str) -> None:
    """Fire-and-forget audit log for agent state transitions."""
    try:
        await db.log_audit(
            action="agent_transition",
            resource_type="agent",
            resource_id=str(agent_id),
            details={"from": old_status, "to": new_status},
            actor="api",
        )
    except Exception:
        logger.warning("Failed to log audit for agent %s transition %s→%s", agent_id, old_status, new_status, exc_info=True)


def _agent_to_response(agent: Agent) -> AgentResponse:
    import json as _json
    strategy_params = None
    if agent.strategy_params:
        try:
            val = agent.strategy_params
            # Handle double-encoded JSON: DB stores jsonb string containing a JSON string
            if isinstance(val, str):
                val = _json.loads(val)
            # After first parse, if still a string, parse again (double-encoded)
            if isinstance(val, str):
                val = _json.loads(val)
            strategy_params = val if isinstance(val, dict) else None
        except (_json.JSONDecodeError, TypeError):
            strategy_params = None
    return AgentResponse(
        id=agent.id or 0,
        name=agent.name,
        status=agent.status,
        config=agent.config_json,
        allocation_usd=agent.allocation_usd,
        strategy_name=agent.strategy_name,
        strategy_params=strategy_params,
        created_at=agent.created_at.isoformat() if agent.created_at else None,
        updated_at=agent.updated_at.isoformat() if agent.updated_at else None,
        paused_at=agent.paused_at.isoformat() if agent.paused_at else None,
        retired_at=agent.retired_at.isoformat() if agent.retired_at else None,
    )


def _decision_to_response(d: AgentDecision) -> AgentDecisionResponse:
    return AgentDecisionResponse(
        id=d.id or 0,
        agent_id=d.agent_id,
        timestamp=d.timestamp.isoformat() if d.timestamp else None,
        phase=d.phase,
        market_snapshot=d.market_snapshot_json,
        decision=d.decision_json,
        outcome=d.outcome_json,
        trade_ids=d.trade_ids,
    )


def _perf_to_response(p: AgentPerformance) -> AgentPerformanceResponse:
    return AgentPerformanceResponse(
        agent_id=p.agent_id,
        date=p.date,
        realized_pnl=p.realized_pnl,
        unrealized_pnl=p.unrealized_pnl,
        total_trades=p.total_trades,
        win_rate=p.win_rate,
        sharpe_rolling_30d=p.sharpe_rolling_30d,
        max_drawdown=p.max_drawdown,
        equity=p.equity,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@agents_router.get("", response_model=List[AgentResponse])
async def list_agents(
    status_filter: Optional[str] = None,
    db: DatabaseManager = Depends(get_db),
):
    agents = await db.list_agents(status=status_filter)
    return [_agent_to_response(a) for a in agents]


@agents_router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    req: AgentCreateRequest,
    db: DatabaseManager = Depends(get_db),
):
    existing = await db.get_agent_by_name(req.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{req.name}' already exists",
        )

    import json as _json
    agent = Agent(
        name=req.name,
        config_json=req.config,
        allocation_usd=req.allocation_usd,
        strategy_name=req.strategy_name,
        strategy_params=_json.dumps(req.strategy_params) if req.strategy_params else None,
    )
    agent_id = await db.create_agent(agent)
    if agent_id is None:
        raise HTTPException(status_code=500, detail="Failed to create agent")

    created = await db.get_agent(agent_id)
    if not created:
        raise HTTPException(status_code=500, detail="Agent created but not found")
    return _agent_to_response(created)


@agents_router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_response(agent)


@agents_router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: int,
    req: AgentUpdateRequest,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status in ("live", "retired"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update agent in '{agent.status}' status",
        )

    if req.name is not None:
        agent.name = req.name
    if req.config is not None:
        agent.config_json = req.config
    if req.allocation_usd is not None:
        agent.allocation_usd = req.allocation_usd
    if req.strategy_name is not None:
        agent.strategy_name = req.strategy_name
    if req.strategy_params is not None:
        import json as _json
        agent.strategy_params = _json.dumps(req.strategy_params)

    await db.update_agent(agent)
    updated = await db.get_agent(agent_id)
    return _agent_to_response(updated or agent)


@agents_router.post("/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
    messaging: Any = Depends(get_messaging),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status not in ("created", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start agent in '{agent.status}' status",
        )

    old_status = agent.status
    new_status = "backtesting"
    await db.update_agent_status(agent_id, new_status)
    await _audit_agent_transition(db, agent_id, old_status, new_status)

    # Notify orchestrator to run the backtest gate
    if messaging:
        try:
            await messaging.publish(
                "agent.command",
                {"command": "start_backtest", "agent_id": agent_id},
            )
        except Exception as e:
            logger.warning("Failed to notify orchestrator for agent %d: %s", agent_id, e)

    updated = await db.get_agent(agent_id)
    return _agent_to_response(updated or agent)


@agents_router.post("/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    allowed = VALID_TRANSITIONS.get(agent.status, set())
    if "paused" not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause agent in '{agent.status}' status",
        )

    old_status = agent.status
    now = datetime.now(timezone.utc)
    await db.update_agent_status(agent_id, "paused", paused_at=now)
    await _audit_agent_transition(db, agent_id, old_status, "paused")
    updated = await db.get_agent(agent_id)
    return _agent_to_response(updated or agent)


@agents_router.post("/{agent_id}/resume", response_model=AgentResponse)
async def resume_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status != "paused":
        raise HTTPException(
            status_code=400,
            detail="Only paused agents can be resumed",
        )

    # Resume to backtesting (safe default — agent must re-earn its way)
    await db.update_agent_status(agent_id, "backtesting")
    await _audit_agent_transition(db, agent_id, "paused", "backtesting")
    updated = await db.get_agent(agent_id)
    return _agent_to_response(updated or agent)


@agents_router.post("/{agent_id}/retire", response_model=AgentResponse)
async def retire_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status == "retired":
        raise HTTPException(status_code=400, detail="Agent is already retired")

    old_status = agent.status
    now = datetime.now(timezone.utc)
    await db.update_agent_status(agent_id, "retired", retired_at=now)
    await _audit_agent_transition(db, agent_id, old_status, "retired")
    updated = await db.get_agent(agent_id)
    return _agent_to_response(updated or agent)


class PromoteResponse(BaseModel):
    promoted: bool
    gate_passed: bool
    failures: List[str]
    agent: AgentResponse


@agents_router.post("/{agent_id}/promote", response_model=PromoteResponse)
async def promote_agent(
    agent_id: int,
    force: bool = False,
    db: DatabaseManager = Depends(get_db),
):
    """Evaluate PaperGate and promote agent from paper to live.

    If ``force=true``, the agent is promoted even when the gate fails.
    """
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status != "paper":
        raise HTTPException(
            status_code=400,
            detail=f"Agent must be in 'paper' status to promote (current: {agent.status})",
        )

    # Evaluate gate criteria inline (avoids import of orchestrator internals)
    perf_records = await db.get_agent_performance(agent_id, days=14)
    failures: List[str] = []

    if len(perf_records) < 14:
        failures.append(f"Only {len(perf_records)} days of paper data (need 14)")

    total_trades = sum(getattr(p, "total_trades", 0) for p in perf_records)
    if total_trades < 10:
        failures.append(f"Only {total_trades} paper trades (need 10)")

    gate_passed = len(failures) == 0

    if not gate_passed and not force:
        return PromoteResponse(
            promoted=False,
            gate_passed=False,
            failures=failures,
            agent=_agent_to_response(agent),
        )

    await db.update_agent_status(agent_id, "live")
    await _audit_agent_transition(db, agent_id, "paper", "live")
    updated = await db.get_agent(agent_id)

    return PromoteResponse(
        promoted=True,
        gate_passed=gate_passed,
        failures=failures,
        agent=_agent_to_response(updated or agent),
    )


@agents_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status in ("live", "paper", "backtesting"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete active agent (status: {agent.status}). Retire it first.",
        )

    deleted = await db.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete agent")


@agents_router.get("/{agent_id}/journal", response_model=List[AgentDecisionResponse])
async def get_agent_journal(
    agent_id: int,
    limit: int = 50,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    decisions = await db.get_agent_decisions(agent_id, limit=limit)
    return [_decision_to_response(d) for d in decisions]


@agents_router.get("/{agent_id}/performance", response_model=List[AgentPerformanceResponse])
async def get_agent_performance(
    agent_id: int,
    days: int = 30,
    db: DatabaseManager = Depends(get_db),
):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    perfs = await db.get_agent_performance(agent_id, days=days)
    return [_perf_to_response(p) for p in perfs]


# ---------------------------------------------------------------------------
# AI-assisted agent builder
# ---------------------------------------------------------------------------

class AgentSuggestionRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=2000)


class AgentSuggestionResponse(BaseModel):
    name: str
    strategy_name: str
    strategy_params: Dict[str, Any]
    symbols: List[str]
    allocation_usd: float
    risk_level: str
    reasoning: str


COPILOT_PROXY_URL = os.getenv("COPILOT_PROXY_URL", "http://copilot-proxy:8087")

AGENT_BUILDER_SYSTEM_PROMPT = """You are an expert trading strategy advisor. Given a user's description of what kind of trading agent they want, suggest the best configuration.

Available strategies:
1. dual-ma-crossover: Dual Moving Average Crossover. Params: fast_period (5-20), slow_period (15-50), adx_threshold (15-40). Good for trend following. Conservative.
2. bollinger-mean-reversion: Bollinger Band Mean Reversion. Params: bb_period (10-30), bb_std (1.5-3.0). Good for ranging markets. Moderate risk.
3. breakout-volume: Volume Breakout. Params: lookback (10-40), volume_multiplier (1.0-3.0). Good for catching momentum. Aggressive.
4. adaptive-rsi: Adaptive RSI. Params: rsi_period (3-21), rsi_entry_low (5-30), rsi_entry_high (70-95). Good for multi-asset rotation. Moderate risk.

Available symbols: BTCUSDT, ETHUSDT, SOLUSDT

Respond in JSON only:
{"name": "descriptive name", "strategy_name": "one of the 4 above", "strategy_params": {...}, "symbols": [...], "allocation_usd": number, "risk_level": "conservative|moderate|aggressive", "reasoning": "1-2 sentence explanation"}"""


@agents_router.post("/suggest", response_model=AgentSuggestionResponse)
async def suggest_agent(req: AgentSuggestionRequest):
    """Use AI to suggest an agent configuration from natural language."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{COPILOT_PROXY_URL}/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": AGENT_BUILDER_SYSTEM_PROMPT},
                        {"role": "user", "content": req.prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            suggestion = json.loads(content)

            # Validate and constrain the suggestion
            valid_strategies = {"dual-ma-crossover", "bollinger-mean-reversion", "breakout-volume", "adaptive-rsi"}
            valid_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

            strategy = suggestion.get("strategy_name", "dual-ma-crossover")
            if strategy not in valid_strategies:
                strategy = "dual-ma-crossover"

            symbols = [s for s in suggestion.get("symbols", ["BTCUSDT"]) if s in valid_symbols]
            if not symbols:
                symbols = ["BTCUSDT"]

            allocation = max(100, min(100000, suggestion.get("allocation_usd", 5000)))

            return AgentSuggestionResponse(
                name=suggestion.get("name", f"AI-{strategy}")[:50],
                strategy_name=strategy,
                strategy_params=suggestion.get("strategy_params", {}),
                symbols=symbols,
                allocation_usd=allocation,
                risk_level=suggestion.get("risk_level", "moderate"),
                reasoning=suggestion.get("reasoning", "AI-suggested configuration"),
            )
    except httpx.HTTPStatusError as e:
        logger.warning("LLM proxy returned %s: %s", e.response.status_code, e.response.text[:200])
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable") from e
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse LLM response: %s", e)
        raise HTTPException(status_code=502, detail="AI returned invalid response") from e
    except Exception as e:
        logger.exception("Agent suggestion failed")
        raise HTTPException(status_code=500, detail="Failed to generate suggestion") from e


# ---------------------------------------------------------------------------
# Self-Learning Endpoints
# ---------------------------------------------------------------------------

class TradeAttributionResponse(BaseModel):
    trade_id: str
    agent_id: int
    strategy_name: str
    signal_type: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    market_regime: str = ""
    params_snapshot: Dict[str, Any] = {}
    entry_indicators: Dict[str, Any] = {}
    created_at: Optional[str] = None


class ScorecardResponse(BaseModel):
    agent_id: int
    strategy_name: str
    signal_type: str
    total_trades: int
    win_rate: float
    avg_pnl: float
    profit_factor: float
    avg_hold_time_minutes: float


class MutationResponse(BaseModel):
    agent_id: int
    strategy_name: str
    source: str
    old_params: Dict[str, Any]
    new_params: Dict[str, Any]
    backtest_sharpe_before: float
    backtest_sharpe_after: float
    accepted: bool
    created_at: Optional[str] = None


class ReasoningResponse(BaseModel):
    """Combined view of agent's learning history."""
    recent_decisions: List[AgentDecisionResponse]
    scorecards: List[ScorecardResponse]
    recent_mutations: List[MutationResponse]
    current_regime: str = "unknown"


@agents_router.get("/{agent_id}/attributions", response_model=List[TradeAttributionResponse])
async def get_agent_attributions(
    agent_id: int,
    limit: int = 50,
    db: DatabaseManager = Depends(get_db),
) -> List[TradeAttributionResponse]:
    """Get trade attributions for an agent (Phase 1: trade-level performance tracking)."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    attributions = await db.get_trade_attributions(agent_id, limit=limit)
    return [
        TradeAttributionResponse(
            trade_id=a.trade_id,
            agent_id=a.agent_id,
            strategy_name=a.strategy_name,
            signal_type=a.signal_type,
            entry_price=a.entry_price,
            exit_price=a.exit_price,
            pnl=a.realized_pnl,
            market_regime=a.market_regime,
            params_snapshot=a.params_snapshot,
            entry_indicators=a.entry_indicators,
            created_at=a.created_at.isoformat() if a.created_at else None,
        )
        for a in attributions
    ]


@agents_router.get("/{agent_id}/scorecards", response_model=List[ScorecardResponse])
async def get_agent_scorecards(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
) -> List[ScorecardResponse]:
    """Get per-signal-type performance scorecards (Phase 1: signal effectiveness)."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    scorecards = await db.get_strategy_scorecards(agent_id)
    return [
        ScorecardResponse(
            agent_id=s.agent_id,
            strategy_name=s.strategy_name,
            signal_type=s.signal_type,
            total_trades=s.sample_size,
            win_rate=s.win_rate,
            avg_pnl=s.avg_pnl,
            profit_factor=s.profit_factor,
            avg_hold_time_minutes=s.avg_hold_duration,
        )
        for s in scorecards
    ]


@agents_router.get("/{agent_id}/mutations", response_model=List[MutationResponse])
async def get_agent_mutations(
    agent_id: int,
    limit: int = 20,
    db: DatabaseManager = Depends(get_db),
) -> List[MutationResponse]:
    """Get parameter mutation history (Phase 2: backtest-validated adaptations)."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    mutations = await db.get_param_mutations(agent_id, limit=limit)
    return [
        MutationResponse(
            agent_id=m.agent_id,
            strategy_name=m.mutation_reason,
            source=m.mutation_reason,
            old_params=m.previous_params,
            new_params=m.candidate_params,
            backtest_sharpe_before=m.backtest_sharpe or 0.0,
            backtest_sharpe_after=m.backtest_sharpe or 0.0,
            accepted=m.accepted,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in mutations
    ]


@agents_router.get("/{agent_id}/reasoning", response_model=ReasoningResponse)
async def get_agent_reasoning(
    agent_id: int,
    db: DatabaseManager = Depends(get_db),
) -> ReasoningResponse:
    """Get combined self-learning reasoning view (decisions, scorecards, mutations)."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get learn-phase decisions
    all_decisions = await db.get_agent_decisions(agent_id, limit=50)
    learn_decisions = [d for d in all_decisions if d.phase == "learn"]

    scorecards = await db.get_strategy_scorecards(agent_id)
    mutations = await db.get_param_mutations(agent_id, limit=10)

    return ReasoningResponse(
        recent_decisions=[_decision_to_response(d) for d in learn_decisions[:20]],
        scorecards=[
            ScorecardResponse(
                agent_id=s.agent_id,
                strategy_name=s.strategy_name,
                signal_type=s.signal_type,
                total_trades=s.total_trades,
                win_rate=s.win_rate,
                avg_pnl=s.avg_pnl,
                profit_factor=s.profit_factor,
                avg_hold_time_minutes=s.avg_hold_time_minutes,
            )
            for s in scorecards
        ],
        recent_mutations=[
            MutationResponse(
                agent_id=m.agent_id,
                strategy_name=m.strategy_name,
                source=m.source,
                old_params=m.old_params,
                new_params=m.new_params,
                backtest_sharpe_before=m.backtest_sharpe_before,
                backtest_sharpe_after=m.backtest_sharpe_after,
                accepted=m.accepted,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in mutations
        ],
    )
