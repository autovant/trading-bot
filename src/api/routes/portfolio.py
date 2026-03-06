"""Portfolio overview API routes — aggregated metrics across all agents and strategies."""

import logging
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.database import DatabaseManager

logger = logging.getLogger(__name__)

portfolio_router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Dependency — overridden at app startup
# ---------------------------------------------------------------------------

async def get_db() -> DatabaseManager:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AgentSummary(BaseModel):
    id: int
    name: str
    strategy: str
    status: str
    allocation_usd: float
    total_pnl: float
    today_pnl: float
    win_rate: float
    total_trades: int
    sharpe: float
    max_drawdown: float
    equity: float
    mutations_accepted: int


class StrategySummary(BaseModel):
    strategy_name: str
    agent_count: int
    total_pnl: float
    avg_win_rate: float
    total_trades: int
    avg_sharpe: float
    mutations_accepted: int


class EquityPoint(BaseModel):
    date: str
    value: float


class DailyPnlPoint(BaseModel):
    date: str
    pnl: float


class PortfolioOverviewResponse(BaseModel):
    total_equity: float
    total_pnl: float
    today_pnl: float
    total_trades: int
    overall_win_rate: float
    overall_sharpe: float
    overall_max_drawdown: float
    agents: List[AgentSummary]
    strategies: List[StrategySummary]
    equity_curve: List[EquityPoint]
    daily_pnl: List[DailyPnlPoint]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@portfolio_router.get("/overview", response_model=PortfolioOverviewResponse)
async def get_portfolio_overview(
    days: int = 30,
    db: DatabaseManager = Depends(get_db),
):
    """Aggregated portfolio overview with per-agent and per-strategy breakdowns."""
    agents = await db.list_agents()
    if not agents:
        return PortfolioOverviewResponse(
            total_equity=0, total_pnl=0, today_pnl=0, total_trades=0,
            overall_win_rate=0, overall_sharpe=0, overall_max_drawdown=0,
            agents=[], strategies=[], equity_curve=[], daily_pnl=[],
        )

    agent_summaries: List[AgentSummary] = []
    strategy_map: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"agent_count": 0, "total_pnl": 0.0, "win_rates": [], "total_trades": 0, "sharpes": [], "mutations": 0}
    )

    total_equity = 0.0
    total_pnl = 0.0
    today_pnl = 0.0
    total_trades = 0
    total_wins = 0
    all_sharpes: List[float] = []
    all_max_dd: List[float] = []

    # Per-day equity/PnL aggregation
    daily_equity: Dict[str, float] = defaultdict(float)
    daily_pnl_map: Dict[str, float] = defaultdict(float)

    for agent in agents:
        perfs = await db.get_agent_performance(agent.id, days=days)
        mutations = await db.get_param_mutations(agent.id, limit=1000, accepted_only=True)

        strategy_name = agent.strategy_name or ""
        if not strategy_name and agent.config_json:
            strategy_name = agent.config_json.get("strategy", agent.config_json.get("name", ""))

        agent_pnl = 0.0
        agent_today_pnl = 0.0
        agent_trades = 0
        agent_wins = 0
        agent_sharpe = 0.0
        agent_max_dd = 0.0
        agent_equity = agent.allocation_usd

        if perfs:
            agent_pnl = sum(p.realized_pnl for p in perfs)
            agent_today_pnl = perfs[0].realized_pnl if perfs else 0.0
            agent_trades = sum(p.total_trades for p in perfs)
            agent_wins = sum(int(p.win_rate * p.total_trades) for p in perfs if p.total_trades > 0)
            agent_sharpe = perfs[0].sharpe_rolling_30d if perfs else 0.0
            agent_max_dd = max((p.max_drawdown for p in perfs), default=0.0)
            agent_equity = perfs[0].equity if perfs else agent.allocation_usd

            for p in perfs:
                if p.date:
                    daily_equity[p.date] += p.equity
                    daily_pnl_map[p.date] += p.realized_pnl

        agent_win_rate = agent_wins / agent_trades if agent_trades > 0 else 0.0

        agent_summaries.append(AgentSummary(
            id=agent.id,
            name=agent.name,
            strategy=strategy_name,
            status=agent.status,
            allocation_usd=agent.allocation_usd,
            total_pnl=round(agent_pnl, 2),
            today_pnl=round(agent_today_pnl, 2),
            win_rate=round(agent_win_rate, 4),
            total_trades=agent_trades,
            sharpe=round(agent_sharpe, 4),
            max_drawdown=round(agent_max_dd, 6),
            equity=round(agent_equity, 2),
            mutations_accepted=len(mutations),
        ))

        # Aggregate into strategy map
        strategy_map[strategy_name]["agent_count"] += 1
        strategy_map[strategy_name]["total_pnl"] += agent_pnl
        strategy_map[strategy_name]["win_rates"].append(agent_win_rate)
        strategy_map[strategy_name]["total_trades"] += agent_trades
        strategy_map[strategy_name]["sharpes"].append(agent_sharpe)
        strategy_map[strategy_name]["mutations"] += len(mutations)

        total_equity += agent_equity
        total_pnl += agent_pnl
        today_pnl += agent_today_pnl
        total_trades += agent_trades
        total_wins += agent_wins
        if agent_sharpe:
            all_sharpes.append(agent_sharpe)
        all_max_dd.append(agent_max_dd)

    # Build strategy summaries
    strategy_summaries: List[StrategySummary] = []
    for name, data in strategy_map.items():
        avg_wr = sum(data["win_rates"]) / len(data["win_rates"]) if data["win_rates"] else 0.0
        avg_sh = sum(data["sharpes"]) / len(data["sharpes"]) if data["sharpes"] else 0.0
        strategy_summaries.append(StrategySummary(
            strategy_name=name or "unknown",
            agent_count=data["agent_count"],
            total_pnl=round(data["total_pnl"], 2),
            avg_win_rate=round(avg_wr, 4),
            total_trades=data["total_trades"],
            avg_sharpe=round(avg_sh, 4),
            mutations_accepted=data["mutations"],
        ))

    # Build equity curve and daily PnL from real data
    equity_curve = [
        EquityPoint(date=date, value=round(val, 2))
        for date, val in sorted(daily_equity.items())
    ]
    daily_pnl_list = [
        DailyPnlPoint(date=date, pnl=round(val, 2))
        for date, val in sorted(daily_pnl_map.items())
    ]

    overall_win_rate = total_wins / total_trades if total_trades > 0 else 0.0
    overall_sharpe = sum(all_sharpes) / len(all_sharpes) if all_sharpes else 0.0
    overall_max_dd = max(all_max_dd) if all_max_dd else 0.0

    return PortfolioOverviewResponse(
        total_equity=round(total_equity, 2),
        total_pnl=round(total_pnl, 2),
        today_pnl=round(today_pnl, 2),
        total_trades=total_trades,
        overall_win_rate=round(overall_win_rate, 4),
        overall_sharpe=round(overall_sharpe, 4),
        overall_max_drawdown=round(overall_max_dd, 6),
        agents=agent_summaries,
        strategies=strategy_summaries,
        equity_curve=equity_curve,
        daily_pnl=daily_pnl_list,
    )
