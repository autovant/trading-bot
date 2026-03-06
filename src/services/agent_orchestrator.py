"""
Agent Orchestrator Service — FastAPI microservice (port 8088).

Manages the lifecycle of autonomous trading agents using the OODA loop:
  OBSERVE → ORIENT → DECIDE → ACT → LEARN

On startup, loads all non-retired agents from the database, subscribes to
NATS for market data and execution reports, and runs each agent on its
configured rebalance interval.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram

from ..config import (
    AgentBacktestRequirements,
    AgentConfig,
    AgentPaperRequirements,
    TradingBotConfig,
    load_config,
)
from ..database import (
    Agent,
    AgentDecision,
    AgentPerformance,
    DatabaseManager,
    ParamMutation,
    StrategyScorecard,
    TradeAttribution,
)
from ..llm_client import LLMClient, LLMError
from ..messaging import MessagingClient
from .base import BaseService, create_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
AGENT_CYCLE_COUNT = Counter(
    "agent_ooda_cycles_total",
    "Total OODA cycles executed",
    ["agent_id", "phase"],
)
AGENT_ACTIVE = Gauge(
    "agent_active_count",
    "Number of actively running agents",
)
AGENT_CYCLE_LATENCY = Histogram(
    "agent_ooda_cycle_seconds",
    "Duration of a full OODA cycle",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# ---------------------------------------------------------------------------
# Agent State Machine
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "created": ["backtesting", "retired"],
    "backtesting": ["paper", "paused", "retired"],
    "paper": ["live", "paused", "retired"],
    "live": ["paused", "retired"],
    "paused": ["backtesting", "paper", "live", "retired"],
    "retired": [],
}


class AgentStateMachine:
    """Validates and executes agent lifecycle transitions."""

    @staticmethod
    def can_transition(current: str, target: str) -> bool:
        return target in VALID_TRANSITIONS.get(current, [])

    @staticmethod
    async def transition(
        db: DatabaseManager,
        agent_id: int,
        current_status: str,
        target_status: str,
        messaging: Optional[MessagingClient] = None,
    ) -> bool:
        """Transition an agent to a new status with validation.

        Publishes status change to NATS ``agent.status`` on success.
        """
        if not AgentStateMachine.can_transition(current_status, target_status):
            logger.warning(
                "Invalid transition: agent %d %s → %s",
                agent_id,
                current_status,
                target_status,
            )
            return False

        now = datetime.now(timezone.utc)
        paused_at = now if target_status == "paused" else None
        retired_at = now if target_status == "retired" else None

        ok = await db.update_agent_status(
            agent_id, target_status, paused_at=paused_at, retired_at=retired_at
        )
        if ok and messaging:
            await messaging.publish(
                "agent.status",
                {
                    "agent_id": agent_id,
                    "previous": current_status,
                    "status": target_status,
                    "timestamp": now.isoformat(),
                },
            )
        return ok


# ---------------------------------------------------------------------------
# Agent Runner — one per active agent
# ---------------------------------------------------------------------------
class AgentRunner:
    """Runs the OODA loop for a single agent on its rebalance interval."""

    def __init__(
        self,
        agent: Agent,
        config: AgentConfig,
        db: DatabaseManager,
        messaging: MessagingClient,
        llm: LLMClient,
    ):
        self.agent = agent
        self.config = config
        self.db = db
        self.messaging = messaging
        self.llm = llm
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

        # Latest market data cache (populated by NATS subscription)
        self._market_cache: Dict[str, Any] = {}
        self._market_history: Dict[str, List[Dict[str, Any]]] = {}  # symbol → bars
        self._recent_fills: List[Dict[str, Any]] = []

        # Self-learning state
        self._cooldown_remaining: int = 0  # cycles to wait after param change
        self._consecutive_losses: int = 0
        self._last_walk_forward: Optional[datetime] = None

        # Strategy instance (non-LLM path) — lazily loaded from registry
        self._strategy: Optional[Any] = None
        if config.strategy_name:
            from ..strategies.registry import StrategyRegistry
            symbols = config.target.symbols
            self._strategy = StrategyRegistry.instantiate(
                config.strategy_name,
                symbols[0] if symbols else "BTCUSDT",
                config.strategy_params,
            )

    @property
    def agent_id(self) -> int:
        assert self.agent.id is not None
        return self.agent.id

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name=f"agent-{self.agent_id}")
        logger.info("Agent %d runner started", self.agent_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Agent %d runner stopped", self.agent_id)

    # ---- main loop ---------------------------------------------------------
    async def _loop(self) -> None:
        interval = self.config.schedule.rebalance_interval_seconds
        while not self._stop.is_set():
            try:
                if not self._is_active_hours():
                    await asyncio.sleep(60)
                    continue

                start = asyncio.get_event_loop().time()
                if self._strategy:
                    await self._run_strategy_cycle()
                else:
                    await self._run_ooda_cycle()
                elapsed = asyncio.get_event_loop().time() - start
                AGENT_CYCLE_LATENCY.observe(elapsed)

                # Sleep for remaining interval
                sleep_time = max(0, interval - elapsed)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=sleep_time)
                    break  # stop requested
                except asyncio.TimeoutError:
                    pass  # normal — continue to next cycle
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Agent %d OODA cycle error", self.agent_id)
                await asyncio.sleep(min(interval, 30))

    def _is_active_hours(self) -> bool:
        schedule = self.config.schedule
        if schedule.pause_on_weekends:
            now = datetime.now(timezone.utc)
            if now.weekday() >= 5:  # Saturday=5, Sunday=6
                return False
        if schedule.active_hours_utc is not None:
            now = datetime.now(timezone.utc)
            if now.hour not in schedule.active_hours_utc:
                return False
        return True

    # ---- strategy cycle (non-LLM path) ------------------------------------
    async def _run_strategy_cycle(self) -> None:
        """Execute one strategy evaluation cycle using a preset strategy."""
        # Refresh agent status from DB (it may have been paused via API)
        fresh = await self.db.get_agent(self.agent_id)
        if not fresh or fresh.status not in ("paper", "live"):
            logger.info("Agent %d status is %s — skipping cycle", self.agent_id, fresh.status if fresh else "deleted")
            self._stop.set()
            return
        self.agent = fresh

        # Decrement cooldown
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        from ..domain.entities import MarketData

        for symbol in self.config.target.symbols:
            cached = self._market_cache.get(symbol, {})
            price = cached.get("price")
            if not price:
                continue

            market_data = MarketData(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                open=cached.get("open", price),
                high=cached.get("high", price),
                low=cached.get("low", price),
                close=price,
                volume=cached.get("volume", 0.0),
            )

            # Store market bar history for mini-backtests
            if symbol not in self._market_history:
                self._market_history[symbol] = []
            self._market_history[symbol].append({
                "open": market_data.open,
                "high": market_data.high,
                "low": market_data.low,
                "close": market_data.close,
                "volume": market_data.volume,
                "timestamp": market_data.timestamp.isoformat(),
            })
            # Keep last ~2000 bars (~7 days of hourly data)
            if len(self._market_history[symbol]) > 2000:
                self._market_history[symbol] = self._market_history[symbol][-2000:]

            orders = await self._strategy.on_tick(market_data)
            if not orders:
                continue

            guardrails = self.config.risk_guardrails

            # Phase 4: Progressive risk reduction based on drawdown
            risk_multiplier = self._get_progressive_risk_multiplier()

            for order in orders:
                # Phase 4: Confidence-weighted position sizing
                signal_confidence = order.metadata.get("entry_indicators", {}).get("confidence", 50)
                base_size = min(
                    guardrails.max_position_size_usd,
                    self.config.allocation_usd * 0.1,
                )
                # Scale by confidence: 0.3x at 0 confidence, 1.5x at 100
                confidence_mult = 0.3 + (signal_confidence / 100) * 1.2

                # Detect regime for sizing
                regime = self._detect_regime(symbol)
                regime_multipliers = {
                    "trending_up": 1.2, "trending_down": 1.0,
                    "ranging": 0.6, "volatile": 0.4,
                }
                regime_mult = regime_multipliers.get(regime, 0.8)

                position_size_usd = base_size * confidence_mult * regime_mult * risk_multiplier
                position_size_usd = min(position_size_usd, guardrails.max_position_size_usd)

                order.quantity = position_size_usd / market_data.close

                signal_type = order.metadata.get("signal_type", "unknown")
                strategy_name = order.metadata.get("strategy_name", self.config.strategy_name or "")

                intent = {
                    "idempotency_key": order.id if order.id else str(uuid.uuid4()),
                    "symbol": order.symbol,
                    "side": order.side.value if hasattr(order.side, "value") else str(order.side),
                    "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
                    "quantity": round(order.quantity, 8),
                    "price": round(order.price or market_data.close, 2),
                    "agent_id": self.agent_id,
                    "signal_type": signal_type,
                    "entry_indicators": order.metadata.get("entry_indicators", {}),
                    "regime": regime,
                }

                try:
                    await self.messaging.publish("trading.orders", intent)
                    logger.info(
                        "Agent %d strategy submitted %s %s %s @ %s (signal=%s, regime=%s, size=$%.2f)",
                        self.agent_id,
                        intent["side"],
                        intent["quantity"],
                        intent["symbol"],
                        intent["price"],
                        signal_type,
                        regime,
                        position_size_usd,
                    )
                except Exception as e:
                    logger.error("Agent %d failed to publish strategy order: %s", self.agent_id, e)

                # Phase 1: Create trade attribution for entry signals only
                # Exit signals (exit_long_*, exit_short_*) close existing attributions
                if not signal_type.startswith("exit_"):
                    params_snapshot = self._get_strategy_params()
                    await self.db.create_trade_attribution(
                        TradeAttribution(
                            trade_id=intent["idempotency_key"],
                            agent_id=self.agent_id,
                            strategy_name=strategy_name,
                            signal_type=signal_type,
                            entry_price=market_data.close,
                            market_regime=regime,
                            params_snapshot=params_snapshot,
                            entry_indicators=order.metadata.get("entry_indicators", {}),
                        )
                    )

                await self.db.create_agent_decision(
                    AgentDecision(
                        agent_id=self.agent_id,
                        phase="act",
                        market_snapshot_json={"price": market_data.close, "symbol": symbol, "regime": regime},
                        decision_json={
                            "strategy": self.config.strategy_name,
                            "action": intent["side"],
                            "quantity": intent["quantity"],
                            "signal_type": signal_type,
                            "position_size_usd": round(position_size_usd, 2),
                        },
                        outcome_json=intent,
                        trade_ids=[intent["idempotency_key"]],
                    )
                )

        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="strategy").inc()

        # Update daily performance and trigger self-learning from recent fills
        if self._recent_fills:
            await self._update_daily_performance()

    # ---- OODA cycle --------------------------------------------------------
    async def _run_ooda_cycle(self) -> None:
        """Execute one full Observe-Orient-Decide-Act-Learn cycle."""
        # Refresh agent status from DB (it may have been paused via API)
        fresh = await self.db.get_agent(self.agent_id)
        if not fresh or fresh.status not in ("paper", "live"):
            logger.info("Agent %d status is %s — skipping cycle", self.agent_id, fresh.status if fresh else "deleted")
            self._stop.set()
            return
        self.agent = fresh

        # OBSERVE
        observation = await self._observe()
        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="observe").inc()

        # ORIENT
        orientation = await self._orient(observation)
        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="orient").inc()

        # DECIDE
        decision = await self._decide(orientation)
        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="decide").inc()

        # ACT
        outcome = await self._act(decision)
        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="act").inc()

        # LEARN
        await self._learn(observation, orientation, decision, outcome)
        AGENT_CYCLE_COUNT.labels(agent_id=str(self.agent_id), phase="learn").inc()

    # ---- OBSERVE -----------------------------------------------------------
    async def _observe(self) -> Dict[str, Any]:
        """Gather current market data, indicators, and portfolio snapshot."""
        symbols = self.config.target.symbols
        observation: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols": {},
            "portfolio": {
                "allocation_usd": self.config.allocation_usd,
                "agent_status": self.agent.status,
            },
        }

        for symbol in symbols:
            cached = self._market_cache.get(symbol, {})
            observation["symbols"][symbol] = {
                "price": cached.get("price"),
                "volume_24h": cached.get("volume_24h"),
                "change_pct_24h": cached.get("change_pct_24h"),
                "bid": cached.get("bid"),
                "ask": cached.get("ask"),
                "indicators": cached.get("indicators", {}),
            }

        return observation

    # ---- ORIENT ------------------------------------------------------------
    async def _orient(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Send market context to LLM for regime analysis and thesis."""
        symbols_summary = []
        for sym, data in observation.get("symbols", {}).items():
            symbols_summary.append(
                f"{sym}: price={data.get('price')}, "
                f"24h_change={data.get('change_pct_24h')}%, "
                f"indicators={json.dumps(data.get('indicators', {}))}"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a quantitative trading analyst. Analyze the market data "
                    "and provide a structured assessment. Respond ONLY with valid JSON.\n"
                    "Schema: {\"regime\": \"trending_up|trending_down|ranging|volatile\", "
                    "\"confidence\": 0-100, \"thesis\": \"string\", "
                    "\"recommended_action\": \"buy|sell|hold|reduce\", "
                    "\"reasoning\": \"string\"}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Agent: {self.config.name}\n"
                    f"Allocation: ${self.config.allocation_usd}\n"
                    f"Status: {self.agent.status}\n"
                    f"Markets:\n" + "\n".join(symbols_summary)
                ),
            },
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                temperature=self.config.llm_temperature,
            )
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            return {
                "regime": parsed.get("regime", "unknown"),
                "confidence": min(max(int(parsed.get("confidence", 0)), 0), 100),
                "thesis": parsed.get("thesis", ""),
                "recommended_action": parsed.get("recommended_action", "hold"),
                "reasoning": parsed.get("reasoning", ""),
            }
        except (LLMError, json.JSONDecodeError, KeyError) as e:
            logger.warning("Agent %d orient failed: %s — defaulting to hold", self.agent_id, e)
            return {
                "regime": "unknown",
                "confidence": 0,
                "thesis": "LLM unavailable",
                "recommended_action": "hold",
                "reasoning": str(e),
            }

    # ---- DECIDE ------------------------------------------------------------
    async def _decide(self, orientation: Dict[str, Any]) -> Dict[str, Any]:
        """Apply risk guardrails and generate order intents."""
        guardrails = self.config.risk_guardrails
        action = orientation.get("recommended_action", "hold")
        confidence = orientation.get("confidence", 0)

        decision: Dict[str, Any] = {
            "action": "hold",
            "order_intents": [],
            "reason": "",
        }

        # Hold if confidence too low or LLM unavailable
        if confidence < 30 or action == "hold":
            decision["reason"] = f"Low confidence ({confidence}) or hold signal"
            return decision

        # Check drawdown kill switch
        perf = await self.db.get_agent_performance(self.agent_id, days=1)
        if perf:
            latest = perf[0]
            if latest.equity > 0:
                dd = latest.max_drawdown
                if dd >= guardrails.kill_switch_drawdown_pct:
                    decision["reason"] = f"Kill switch: drawdown {dd:.1%} >= {guardrails.kill_switch_drawdown_pct:.1%}"
                    # Auto-pause
                    await AgentStateMachine.transition(
                        self.db, self.agent_id, self.agent.status, "paused", self.messaging
                    )
                    self._stop.set()
                    return decision

        # Generate order intents
        for symbol in self.config.target.symbols:
            cached = self._market_cache.get(symbol, {})
            price = cached.get("price")
            if not price or price <= 0:
                continue

            position_size_usd = min(
                guardrails.max_position_size_usd,
                self.config.allocation_usd * 0.1,  # max 10% per position
            )

            if action in ("buy", "sell"):
                qty = position_size_usd / price
                decision["order_intents"].append(
                    {
                        "idempotency_key": str(uuid.uuid4()),
                        "symbol": symbol,
                        "side": action,
                        "order_type": "limit",
                        "quantity": round(qty, 8),
                        "price": round(price, 2),
                        "agent_id": self.agent_id,
                    }
                )
            elif action == "reduce":
                decision["order_intents"].append(
                    {
                        "idempotency_key": str(uuid.uuid4()),
                        "symbol": symbol,
                        "side": "sell",
                        "order_type": "market",
                        "quantity": 0,  # will be set by position manager
                        "price": 0,
                        "agent_id": self.agent_id,
                        "reduce_only": True,
                    }
                )

        decision["action"] = action
        decision["reason"] = orientation.get("reasoning", "")
        return decision

    # ---- ACT ---------------------------------------------------------------
    async def _act(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Publish order intents to NATS and track results."""
        intents = decision.get("order_intents", [])
        outcome: Dict[str, Any] = {
            "orders_submitted": 0,
            "order_ids": [],
        }

        if not intents:
            return outcome

        for intent in intents:
            try:
                await self.messaging.publish("trading.orders", intent)
                outcome["orders_submitted"] += 1
                outcome["order_ids"].append(intent["idempotency_key"])
                logger.info(
                    "Agent %d submitted %s %s %s @ %s",
                    self.agent_id,
                    intent["side"],
                    intent["quantity"],
                    intent["symbol"],
                    intent.get("price", "market"),
                )
            except Exception as e:
                logger.error("Agent %d failed to publish order: %s", self.agent_id, e)

        return outcome

    # ---- LEARN -------------------------------------------------------------
    async def _learn(
        self,
        observation: Dict[str, Any],
        orientation: Dict[str, Any],
        decision: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> None:
        """Record the decision cycle and update performance metrics."""
        await self.db.create_agent_decision(
            AgentDecision(
                agent_id=self.agent_id,
                phase="learn",
                market_snapshot_json=observation,
                decision_json={
                    "orientation": orientation,
                    "decision": decision,
                },
                outcome_json=outcome,
                trade_ids=outcome.get("order_ids", []),
            )
        )

        # Update daily performance from recent fills
        if self._recent_fills:
            await self._update_daily_performance()

    async def _update_daily_performance(self) -> None:
        """Compute and persist daily performance rollup from recent fills."""
        # Snapshot and clear atomically (no await between) to avoid
        # losing fills appended by handle_execution_report during DB I/O.
        fills_snapshot = list(self._recent_fills)
        self._recent_fills.clear()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total_pnl = sum(f.get("realized_pnl", 0) for f in fills_snapshot)
        wins = sum(1 for f in fills_snapshot if f.get("realized_pnl", 0) > 0)
        total = len(fills_snapshot)
        win_rate = wins / total if total > 0 else 0

        existing = await self.db.get_agent_performance(self.agent_id, days=30)
        prev_equity = existing[0].equity if existing else self.config.allocation_usd
        new_equity = prev_equity + total_pnl

        # Compute rolling 30d Sharpe from daily PnL history
        daily_pnls = [p.realized_pnl for p in existing]
        daily_pnls.append(total_pnl)
        sharpe_30d = 0.0
        if len(daily_pnls) >= 2:
            import statistics
            mean_pnl = statistics.mean(daily_pnls)
            std_pnl = statistics.stdev(daily_pnls)
            if std_pnl > 0:
                sharpe_30d = round((mean_pnl / std_pnl) * (252 ** 0.5), 4)

        # Compute max drawdown from equity curve
        equities = [p.equity for p in reversed(existing)]
        equities.append(new_equity)
        peak = equities[0] if equities else new_equity
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        await self.db.upsert_agent_performance(
            AgentPerformance(
                agent_id=self.agent_id,
                date=today,
                realized_pnl=total_pnl,
                unrealized_pnl=0,  # computed from open positions
                total_trades=total,
                win_rate=win_rate,
                sharpe_rolling_30d=sharpe_30d,
                max_drawdown=round(max_dd, 6),
                equity=new_equity,
            )
        )

        # Trigger self-learning evaluation — lower threshold for faster adaptation
        if total >= 2:
            await self._evaluate_and_adapt(win_rate, sharpe_30d, max_dd, total_pnl, total)
        elif total >= 1 and existing:
            # Even with 1 fill, evaluate if we have historical context showing losses
            cumulative_pnl = sum(p.realized_pnl for p in existing) + total_pnl
            if cumulative_pnl < 0:
                await self._evaluate_and_adapt(win_rate, sharpe_30d, max_dd, total_pnl, total)

    # ---- Self-learning / parameter adaptation (Phase 2) --------------------
    async def _evaluate_and_adapt(
        self,
        win_rate: float,
        sharpe: float,
        max_drawdown: float,
        recent_pnl: float,
        trade_count: int,
    ) -> None:
        """Backtest-validated parameter adaptation.

        Instead of blindly adjusting params via rules, this method:
        1. Generates multiple parameter candidates (conservative, aggressive, regime-aware, LLM-suggested)
        2. Runs each through a mini-backtest on recent market data
        3. Accepts only if improvement exceeds a threshold above current params
        4. Logs every mutation for audit and cross-agent learning
        """
        sl_cfg = self.config.self_learning
        if not sl_cfg.enabled or not self._strategy or not self.config.strategy_name:
            return

        # Respect cooldown
        if self._cooldown_remaining > 0:
            logger.debug("Agent %d self-learning: %d cycles cooldown remaining", self.agent_id, self._cooldown_remaining)
            return

        current_params = self._get_strategy_params()
        if not current_params:
            return

        # Need at least some market history for mini-backtest
        any_symbol = next(iter(self._market_history), None)
        if not any_symbol or len(self._market_history[any_symbol]) < 50:
            logger.debug("Agent %d self-learning: insufficient market history (%d bars)",
                         self.agent_id, len(self._market_history.get(any_symbol, [])))
            return

        # Phase 3: Trigger LLM post-mortem on consecutive losses
        if self._consecutive_losses >= sl_cfg.progressive_risk.llm_postmortem_after_losses:
            await self._llm_post_mortem(win_rate, sharpe, max_drawdown, recent_pnl)

        # Generate parameter mutation candidates
        candidates = self._generate_candidates(current_params, win_rate, sharpe, max_drawdown)
        if not candidates:
            return

        # Run mini-backtest on current params as baseline
        baseline_result = await self._mini_backtest(current_params)
        if not baseline_result:
            return

        baseline_sharpe = baseline_result.get("sharpe", 0)
        improvement_threshold = sl_cfg.sharpe_improvement_threshold

        best_candidate = None
        best_result = None
        best_improvement = 0.0

        for candidate in candidates[:sl_cfg.max_candidates_per_cycle]:
            result = await self._mini_backtest(candidate["params"])
            if not result:
                continue

            candidate_sharpe = result.get("sharpe", 0)
            improvement = candidate_sharpe - baseline_sharpe

            # Also require win rate >= 40% and profit factor >= 1.0
            if (improvement > improvement_threshold
                    and result.get("win_rate", 0) >= 0.40
                    and result.get("profit_factor", 0) >= 1.0
                    and improvement > best_improvement):
                best_candidate = candidate
                best_result = result
                best_improvement = improvement

        if not best_candidate:
            logger.info("Agent %d self-learning: no candidate beat baseline (sharpe=%.3f)",
                        self.agent_id, baseline_sharpe)
            return

        # Apply winning candidate
        applied = self._apply_params(best_candidate["params"])
        if not applied:
            return

        # Log the mutation
        await self._log_mutation(
            current_params, best_candidate, baseline_result, best_result, applied
        )

        # Update scorecard for signal types involved
        await self._update_scorecard()

        logger.info(
            "Agent %d self-learning: applied '%s' mutation (sharpe %.3f → %.3f, +%.3f)",
            self.agent_id,
            best_candidate["source"],
            baseline_sharpe,
            best_result.get("sharpe", 0),
            best_improvement,
        )

    def _generate_candidates(
        self,
        current_params: Dict[str, Any],
        win_rate: float,
        sharpe: float,
        max_drawdown: float,
    ) -> List[Dict[str, Any]]:
        """Generate diverse parameter mutation candidates."""
        candidates: List[Dict[str, Any]] = []
        import random

        # 1. Conservative: tighten entries (for poor performance)
        if win_rate < 0.50 or max_drawdown > 0.03:
            conservative = dict(current_params)
            for key, val in conservative.items():
                if isinstance(val, (int, float)):
                    if "threshold" in key or "period" in key or "lookback" in key:
                        conservative[key] = val * 1.15  # increase by 15%
                    elif "oversold" in key:
                        conservative[key] = max(5, val - 3)
                    elif "overbought" in key:
                        conservative[key] = min(95, val + 3)
            candidates.append({"source": "conservative", "params": conservative})

        # 2. Aggressive: relax entries (for strong performance)
        if win_rate > 0.55 and sharpe > 0.5:
            aggressive = dict(current_params)
            for key, val in aggressive.items():
                if isinstance(val, (int, float)):
                    if "threshold" in key or "period" in key:
                        aggressive[key] = val * 0.9  # decrease by 10%
                    elif "oversold" in key:
                        aggressive[key] = min(40, val + 3)
                    elif "overbought" in key:
                        aggressive[key] = max(60, val - 3)
            candidates.append({"source": "aggressive", "params": aggressive})

        # 3. Regime-aware: adjust based on detected regime
        any_symbol = next(iter(self._market_history), None)
        if any_symbol:
            regime = self._detect_regime(any_symbol)
            regime_params = dict(current_params)
            if regime == "trending_up":
                for key, val in regime_params.items():
                    if isinstance(val, (int, float)) and "fast" in key:
                        regime_params[key] = max(3, val * 0.85)
            elif regime == "ranging":
                for key, val in regime_params.items():
                    if isinstance(val, (int, float)) and ("std" in key or "bb" in key):
                        regime_params[key] = val * 0.9
            elif regime == "volatile":
                for key, val in regime_params.items():
                    if isinstance(val, (int, float)) and "period" in key:
                        regime_params[key] = val * 1.2
            candidates.append({"source": f"regime_{regime}", "params": regime_params})

        # 4. Random perturbation: small noise to explore parameter space
        perturbed = dict(current_params)
        for key, val in perturbed.items():
            if isinstance(val, float):
                perturbed[key] = val * (1 + random.uniform(-0.1, 0.1))
            elif isinstance(val, int) and val > 0:
                perturbed[key] = max(1, val + random.randint(-2, 2))
        candidates.append({"source": "random_perturbation", "params": perturbed})

        return candidates

    async def _mini_backtest(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run a mini-backtest with the given parameters on recent market history."""
        try:
            from ..backtest.mini_engine import run_mini_backtest
            any_symbol = next(iter(self._market_history), None)
            if not any_symbol:
                return None
            bars = self._market_history[any_symbol]
            strategy_name = self.config.strategy_name or ""
            result = await run_mini_backtest(strategy_name, any_symbol, params, bars)
            return {
                "sharpe": result.sharpe,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "max_drawdown": result.max_drawdown,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades,
            }
        except Exception as e:
            logger.warning("Agent %d mini-backtest failed: %s", self.agent_id, e)
            return None

    def _apply_params(self, new_params: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Apply validated params to the strategy, returning a dict of changes."""
        applied: Dict[str, Dict[str, Any]] = {}
        for param, new_value in new_params.items():
            old_value = getattr(self._strategy, param, None)
            if old_value is not None and old_value != new_value:
                # Type-safe: cast new_value to match the original type
                if isinstance(old_value, int) and isinstance(new_value, float):
                    new_value = int(round(new_value))
                setattr(self._strategy, param, new_value)
                applied[param] = {"old": old_value, "new": new_value}
        return applied

    async def _log_mutation(
        self,
        old_params: Dict[str, Any],
        candidate: Dict[str, Any],
        baseline_result: Dict[str, Any],
        new_result: Dict[str, Any],
        applied: Dict[str, Dict[str, Any]],
    ) -> None:
        """Log a parameter mutation to the database for audit/learning."""
        import math

        def _sanitize(d: Dict[str, Any]) -> Dict[str, Any]:
            """Replace inf/nan with finite values for JSON serialization."""
            return {k: (0.0 if isinstance(v, float) and (math.isinf(v) or math.isnan(v)) else v) for k, v in d.items()}

        safe_baseline = _sanitize(baseline_result)
        safe_new = _sanitize(new_result)

        await self.db.create_param_mutation(
            ParamMutation(
                agent_id=self.agent_id,
                previous_params=old_params,
                candidate_params=candidate["params"],
                mutation_reason=f"{candidate['source']}|{self.config.strategy_name or ''}",
                backtest_sharpe=safe_new.get("sharpe", 0),
                backtest_win_rate=safe_new.get("win_rate", 0),
                backtest_pnl=safe_new.get("total_pnl", 0),
                backtest_trades=safe_new.get("total_trades", 0),
                accepted=True,
            )
        )

        # Also record as agent decision for audit trail
        await self.db.create_agent_decision(
            AgentDecision(
                agent_id=self.agent_id,
                phase="learn",
                market_snapshot_json={
                    "baseline": safe_baseline,
                    "regime": self._detect_regime(next(iter(self._market_history), "")),
                },
                decision_json={
                    "type": "backtest_validated_mutation",
                    "strategy": self.config.strategy_name,
                    "source": candidate["source"],
                    "changes": applied,
                },
                outcome_json={"new_result": safe_new, "status": "applied"},
                trade_ids=[],
            )
        )

    def _get_strategy_params(self) -> Dict[str, Any]:
        """Extract tunable parameters from the current strategy instance."""
        if not self._strategy:
            return {}
        import inspect
        # Only include params that are actual constructor arguments (tunable),
        # not internal runtime state like bars_in_trade, current_position, etc.
        init_sig = inspect.signature(type(self._strategy).__init__)
        init_params = set(init_sig.parameters.keys()) - {"self", "symbol"}
        params: Dict[str, Any] = {}
        for attr in init_params:
            val = getattr(self._strategy, attr, None)
            if isinstance(val, (int, float)) and not callable(val):
                params[attr] = val
        return params

    def _detect_regime(self, symbol: str) -> str:
        """Detect market regime from recent price history."""
        bars = self._market_history.get(symbol, [])
        if len(bars) < 20:
            return "unknown"

        closes = [b["close"] for b in bars[-50:]]
        n = len(closes)

        # Simple trend detection via linear regression slope
        x_mean = (n - 1) / 2
        y_mean = sum(closes) / n
        numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        slope_pct = slope / y_mean if y_mean > 0 else 0

        # Volatility via std of returns
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, n) if closes[i - 1] > 0]
        if not returns:
            return "unknown"
        import statistics
        vol = statistics.stdev(returns) if len(returns) >= 2 else 0

        if vol > 0.03:
            return "volatile"
        if slope_pct > 0.001:
            return "trending_up"
        if slope_pct < -0.001:
            return "trending_down"
        return "ranging"

    def _get_progressive_risk_multiplier(self) -> float:
        """Phase 4: Calculate risk multiplier based on drawdown tiers."""
        risk_cfg = self.config.self_learning.progressive_risk
        # Get current drawdown from recent performance
        perf = getattr(self, "_last_max_drawdown", 0.0)

        tier1_dd = risk_cfg.tier1_drawdown_pct
        tier2_dd = risk_cfg.tier2_drawdown_pct
        tier3_dd = risk_cfg.tier3_drawdown_pct
        pause_dd = risk_cfg.pause_drawdown_pct

        if perf >= pause_dd:
            return 0.0  # fully paused
        if perf >= tier3_dd:
            return 0.25
        if perf >= tier2_dd:
            return 0.50
        if perf >= tier1_dd:
            return 0.75
        return 1.0

    async def _update_scorecard(self) -> None:
        """Phase 1: Update per-signal-type performance scorecards."""
        attributions = await self.db.get_trade_attributions(self.agent_id, limit=200)
        if not attributions:
            return

        # Group by signal_type
        from collections import defaultdict
        by_signal: Dict[str, List] = defaultdict(list)
        for attr in attributions:
            if attr.exit_price is not None:  # only closed trades
                by_signal[attr.signal_type].append(attr)

        for signal_type, trades in by_signal.items():
            wins = sum(1 for t in trades if (t.exit_price or 0) > t.entry_price)
            total = len(trades)
            win_rate = wins / total if total > 0 else 0
            gross_profit = sum(
                (t.exit_price or 0) - t.entry_price
                for t in trades if (t.exit_price or 0) > t.entry_price
            )
            gross_loss = abs(sum(
                (t.exit_price or 0) - t.entry_price
                for t in trades if (t.exit_price or 0) <= t.entry_price
            ))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            avg_pnl = sum((t.exit_price or 0) - t.entry_price for t in trades) / total if total > 0 else 0

            await self.db.upsert_strategy_scorecard(
                StrategyScorecard(
                    agent_id=self.agent_id,
                    strategy_name=self.config.strategy_name or "",
                    signal_type=signal_type,
                    sample_size=total,
                    win_rate=round(win_rate, 4),
                    avg_pnl=round(avg_pnl, 4),
                    profit_factor=round(profit_factor, 4),
                    avg_hold_duration=0.0,
                )
            )

    # ---- Phase 3: LLM Post-Mortem ------------------------------------------
    async def _llm_post_mortem(
        self,
        win_rate: float,
        sharpe: float,
        max_drawdown: float,
        recent_pnl: float,
    ) -> None:
        """Ask LLM to analyze recent losing trades and suggest parameter changes."""
        try:
            from ..llm_client import LLMClient
            llm = LLMClient()

            # Gather context for LLM
            recent_attributions = await self.db.get_trade_attributions(self.agent_id, limit=20)
            scorecards = await self.db.get_strategy_scorecards(self.agent_id)
            current_params = self._get_strategy_params()
            any_symbol = next(iter(self._market_history), "")
            regime = self._detect_regime(any_symbol)

            losing_trades = [
                {
                    "signal_type": a.signal_type,
                    "entry_price": a.entry_price,
                    "exit_price": a.exit_price,
                    "market_regime": a.market_regime,
                    "params_snapshot": a.params_snapshot,
                }
                for a in recent_attributions
                if a.exit_price is not None and (a.exit_price or 0) < a.entry_price
            ]

            scorecard_summary = [
                {"signal": s.signal_type, "win_rate": s.win_rate, "profit_factor": s.profit_factor, "trades": s.sample_size}
                for s in scorecards
            ]

            prompt = (
                "You are a quantitative trading analyst. Analyze these recent losing trades "
                "and suggest parameter adjustments.\n\n"
                f"Strategy: {self.config.strategy_name}\n"
                f"Current regime: {regime}\n"
                f"Win rate: {win_rate:.1%}, Sharpe: {sharpe:.2f}, Max DD: {max_drawdown:.1%}\n"
                f"Recent PnL: {recent_pnl:.2f}\n"
                f"Current params: {json.dumps(current_params)}\n"
                f"Losing trades: {json.dumps(losing_trades[:10])}\n"
                f"Signal scorecards: {json.dumps(scorecard_summary)}\n\n"
                "Respond in JSON format: {\"analysis\": \"...\", \"suggestions\": [{\"param\": \"...\", \"current\": ..., \"suggested\": ..., \"reason\": \"...\"}]}"
            )

            raw_response = await llm.chat([{"role": "user", "content": prompt}])
            # Extract content string from OpenAI-compatible response
            response_text = ""
            if raw_response and "choices" in raw_response:
                response_text = raw_response["choices"][0]["message"]["content"]
            if response_text:
                await self.db.create_agent_decision(
                    AgentDecision(
                        agent_id=self.agent_id,
                        phase="learn",
                        market_snapshot_json={
                            "regime": regime,
                            "win_rate": win_rate,
                            "sharpe": sharpe,
                        },
                        decision_json={
                            "type": "llm_post_mortem",
                            "prompt_summary": f"Analyzed {len(losing_trades)} losing trades",
                            "response": response_text[:2000],
                        },
                        outcome_json={"status": "logged_for_review"},
                        trade_ids=[],
                    )
                )
                logger.info("Agent %d LLM post-mortem completed: %s", self.agent_id, response_text[:200])

                # Reset consecutive loss counter after analysis
                self._consecutive_losses = 0
        except Exception as e:
            logger.warning("Agent %d LLM post-mortem failed: %s", self.agent_id, e)

    # ---- Phase 5: Cross-Agent Learning -------------------------------------
    async def _cross_pollinate(self, orchestrator: "AgentOrchestratorService") -> None:
        """Share successful mutations across agents using the same strategy."""
        sl_cfg = self.config.self_learning
        if not sl_cfg.cross_agent_learning:
            return

        strategy_name = self.config.strategy_name or ""
        if not strategy_name:
            return

        # Find other agents using the same strategy
        all_agents = await self.db.list_agents()
        peers = [
            a for a in all_agents
            if a.id != self.agent_id
            and a.config
            and a.config.get("strategy_name") == strategy_name
            and a.status in ("paper", "live")
        ]

        if not peers:
            return

        # Get recent successful mutations from this agent
        recent_mutations = await self.db.get_param_mutations(
            self.agent_id, limit=5, accepted_only=True
        )
        successful = [m for m in recent_mutations if m.accepted and (m.backtest_sharpe or 0) > 0]

        if not successful:
            return

        # Share the best mutation with peers by logging it for their consideration
        best = max(successful, key=lambda m: m.backtest_sharpe or 0)
        logger.info(
            "Agent %d cross-pollinating mutation to %d peers",
            self.agent_id, len(peers),
        )

        for peer in peers:
            await self.db.create_agent_decision(
                AgentDecision(
                    agent_id=peer.id,
                    phase="learn",
                    market_snapshot_json={"source_agent": self.agent_id},
                    decision_json={
                        "type": "cross_pollination_candidate",
                        "from_agent": self.agent_id,
                        "source": best.mutation_reason,
                        "params": best.candidate_params,
                        "sharpe": best.backtest_sharpe,
                    },
                    outcome_json={"status": "pending_validation"},
                    trade_ids=[],
                )
            )

    # ---- Phase 5: Walk-Forward Optimization --------------------------------
    async def _run_walk_forward_optimization(self) -> None:
        """Periodically run walk-forward optimization to prevent overfitting."""
        sl_cfg = self.config.self_learning
        schedule_hours = sl_cfg.walk_forward_schedule_hours
        if schedule_hours <= 0:
            return

        now = datetime.now(timezone.utc)
        if self._last_walk_forward:
            elapsed = (now - self._last_walk_forward).total_seconds() / 3600
            if elapsed < schedule_hours:
                return

        self._last_walk_forward = now
        strategy_name = self.config.strategy_name or ""
        if not strategy_name:
            return

        current_params = self._get_strategy_params()
        if not current_params:
            return

        # Run out-of-sample validation using mini-backtest on recent data
        any_symbol = next(iter(self._market_history), None)
        if not any_symbol or len(self._market_history[any_symbol]) < 100:
            return

        bars = self._market_history[any_symbol]
        # Split: 70% in-sample, 30% out-of-sample
        split = int(len(bars) * 0.7)
        in_sample_bars = bars[:split]
        out_of_sample_bars = bars[split:]

        try:
            from ..backtest.mini_engine import run_mini_backtest

            # Test current params on out-of-sample
            oos_result = await run_mini_backtest(strategy_name, any_symbol, current_params, out_of_sample_bars)

            await self.db.create_agent_decision(
                AgentDecision(
                    agent_id=self.agent_id,
                    phase="learn",
                    market_snapshot_json={
                        "type": "walk_forward_validation",
                        "in_sample_bars": len(in_sample_bars),
                        "out_of_sample_bars": len(out_of_sample_bars),
                    },
                    decision_json={
                        "strategy": strategy_name,
                        "params": current_params,
                    },
                    outcome_json={
                        "oos_sharpe": oos_result.sharpe,
                        "oos_win_rate": oos_result.win_rate,
                        "oos_profit_factor": oos_result.profit_factor,
                        "oos_trades": oos_result.total_trades,
                    },
                    trade_ids=[],
                )
            )

            # If OOS performance is poor, set cooldown to prevent bad trades
            if oos_result.sharpe < 0 or oos_result.win_rate < 0.35:
                self._cooldown_remaining = sl_cfg.progressive_risk.cooldown_cycles
                logger.warning(
                    "Agent %d walk-forward: poor OOS (sharpe=%.3f, WR=%.1f%%) — setting %d cycle cooldown",
                    self.agent_id, oos_result.sharpe, oos_result.win_rate * 100, self._cooldown_remaining,
                )
        except Exception as e:
            logger.warning("Agent %d walk-forward optimization failed: %s", self.agent_id, e)

    # ---- Market data handler ------------------------------------------------
    async def handle_market_data(self, msg: Any) -> None:
        """NATS callback: update internal market cache."""
        try:
            data = json.loads(msg.data) if isinstance(msg.data, (bytes, str)) else msg.data
            symbol = data.get("symbol")
            if symbol:
                # Normalize keys for strategy consumption
                if "last_price" in data and "price" not in data:
                    data["price"] = data["last_price"]
                if "best_bid" in data and "bid" not in data:
                    data["bid"] = data["best_bid"]
                if "best_ask" in data and "ask" not in data:
                    data["ask"] = data["best_ask"]
                self._market_cache[symbol] = data
        except Exception as e:
            logger.debug("Agent %d market data parse error: %s", self.agent_id, e)

    async def handle_execution_report(self, msg: Any) -> None:
        """NATS callback: process fill reports for this agent."""
        try:
            data = json.loads(msg.data) if isinstance(msg.data, (bytes, str)) else msg.data
            if data.get("agent_id") == self.agent_id:
                self._recent_fills.append(data)
                logger.info(
                    "Agent %d received fill: %s %s %s @ %s",
                    self.agent_id,
                    data.get("side"),
                    data.get("quantity"),
                    data.get("symbol"),
                    data.get("price"),
                )

                # Phase 1: Close trade attribution on exit fills only
                # Entry fills have realized_pnl=0 (opening a position)
                # Exit fills have realized_pnl != 0 (closing/reducing)
                realized_pnl = data.get("realized_pnl", 0)
                exit_price = data.get("price")

                if exit_price and realized_pnl != 0:
                    try:
                        await self.db.close_oldest_open_attribution(
                            agent_id=self.agent_id,
                            exit_price=float(exit_price),
                            realized_pnl=float(realized_pnl),
                            hold_duration_seconds=0,
                            exit_reason=data.get("side", "unknown"),
                        )
                    except Exception:
                        pass  # no open attribution to close

                # Phase 4: Track consecutive losses for progressive risk
                if realized_pnl < 0:
                    self._consecutive_losses += 1
                elif realized_pnl > 0:
                    self._consecutive_losses = 0

                # Store max drawdown for progressive risk multiplier
                perf = await self.db.get_agent_performance(self.agent_id, days=7)
                if perf:
                    self._last_max_drawdown = max(p.max_drawdown for p in perf)

                # Phase 5: Periodically trigger walk-forward optimization
                sl_cfg = self.config.self_learning
                if sl_cfg.enabled and sl_cfg.walk_forward_schedule_hours > 0:
                    await self._run_walk_forward_optimization()

        except Exception as e:
            logger.debug("Agent %d execution report parse error: %s", self.agent_id, e)


# ---------------------------------------------------------------------------
# Backtest Gate — validates backtest results against requirements
# ---------------------------------------------------------------------------
class BacktestGate:
    """Evaluates backtest results against agent's configured requirements."""

    @staticmethod
    def evaluate(
        results: Dict[str, Any],
        requirements: AgentBacktestRequirements,
    ) -> tuple[bool, List[str]]:
        """Return (passed, list_of_failure_reasons)."""
        failures: List[str] = []
        stats = results.get("stats", results)

        sharpe = float(stats.get("sharpe_ratio", stats.get("sharpe", 0)))
        if sharpe < requirements.min_sharpe:
            failures.append(f"Sharpe {sharpe:.2f} < {requirements.min_sharpe}")

        pf = float(stats.get("profit_factor", 0))
        if pf < requirements.min_profit_factor:
            failures.append(f"Profit factor {pf:.2f} < {requirements.min_profit_factor}")

        max_dd = float(stats.get("max_drawdown", stats.get("max_drawdown_pct", 1)))
        if max_dd > requirements.max_drawdown_pct:
            failures.append(f"Max drawdown {max_dd:.1%} > {requirements.max_drawdown_pct:.1%}")

        total_trades = int(stats.get("total_trades", stats.get("num_trades", 0)))
        if total_trades < requirements.min_trades:
            failures.append(f"Trades {total_trades} < {requirements.min_trades}")

        win_rate = float(stats.get("win_rate", 0))
        if win_rate < requirements.min_win_rate:
            failures.append(f"Win rate {win_rate:.1%} < {requirements.min_win_rate:.1%}")

        return (len(failures) == 0, failures)


# ---------------------------------------------------------------------------
# Paper Gate — validates paper trading performance
# ---------------------------------------------------------------------------
class PaperGate:
    """Evaluates paper trading performance vs backtest expectations."""

    @staticmethod
    async def evaluate(
        db: DatabaseManager,
        agent_id: int,
        requirements: AgentPaperRequirements,
        backtest_sharpe: float = 0.0,
    ) -> tuple[bool, List[str]]:
        """Return (passed, list_of_failure_reasons)."""
        failures: List[str] = []
        perf_records = await db.get_agent_performance(agent_id, days=requirements.min_days)

        if len(perf_records) < requirements.min_days:
            failures.append(
                f"Only {len(perf_records)} days of paper data, need {requirements.min_days}"
            )
            return (False, failures)

        total_trades = sum(p.total_trades for p in perf_records)
        if total_trades < requirements.min_trades:
            failures.append(f"Paper trades {total_trades} < {requirements.min_trades}")

        # Check that paper performance is within tolerance of backtest
        if backtest_sharpe > 0 and perf_records:
            latest = perf_records[0]
            if latest.sharpe_rolling_30d > 0:
                deviation = abs(latest.sharpe_rolling_30d - backtest_sharpe) / backtest_sharpe
                if deviation > requirements.performance_tolerance_pct:
                    failures.append(
                        f"Sharpe deviation {deviation:.1%} > tolerance {requirements.performance_tolerance_pct:.1%}"
                    )

        return (len(failures) == 0, failures)


# ---------------------------------------------------------------------------
# Orchestrator Service
# ---------------------------------------------------------------------------
class AgentOrchestratorService(BaseService):
    """Manages all agent runners, subscriptions, and stage gates."""

    def __init__(self) -> None:
        super().__init__("agent-orchestrator")
        self.config: Optional[TradingBotConfig] = None
        self.database: Optional[DatabaseManager] = None
        self.messaging: Optional[MessagingClient] = None
        self.llm: Optional[LLMClient] = None
        self.runners: Dict[int, AgentRunner] = {}
        self._subscriptions: List[Any] = []

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        # Database
        self.database = DatabaseManager(self.config.database.url)
        await self.database.initialize()

        # Messaging (NATS)
        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        # LLM client
        self.llm = LLMClient()

        # Subscribe to market data and execution reports
        sub_market = await self.messaging.subscribe(
            "market.data", self._on_market_data
        )
        sub_exec = await self.messaging.subscribe(
            "trading.executions", self._on_execution_report
        )
        sub_agent_cmd = await self.messaging.subscribe(
            "agent.command", self._on_agent_command
        )
        self._subscriptions.extend([sub_market, sub_exec, sub_agent_cmd])

        # Load and start all non-retired agents
        await self._load_active_agents()

        logger.info(
            "Agent orchestrator started — %d active agents", len(self.runners)
        )

    async def on_shutdown(self) -> None:
        # Stop all runners
        for runner in self.runners.values():
            await runner.stop()
        self.runners.clear()
        AGENT_ACTIVE.set(0)

        # Unsubscribe
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()

        # Close connections
        if self.llm:
            await self.llm.close()
        if self.messaging:
            await self.messaging.close()
        if self.database:
            await self.database.close()

    # ---- agent management --------------------------------------------------
    async def _load_active_agents(self) -> None:
        """Load all non-retired agents from DB and start runners for active ones."""
        assert self.database is not None
        agents = await self.database.list_agents()
        for agent in agents:
            if agent.status in ("paper", "live") and agent.id is not None:
                await self._start_runner(agent)

    async def _start_runner(self, agent: Agent) -> None:
        """Create and start an AgentRunner for the given agent."""
        if agent.id is None or agent.id in self.runners:
            return

        try:
            config = AgentConfig(**agent.config_json)
        except Exception as e:
            logger.error("Agent %d has invalid config: %s", agent.id, e)
            return

        assert self.database is not None
        assert self.messaging is not None
        assert self.llm is not None

        runner = AgentRunner(
            agent=agent,
            config=config,
            db=self.database,
            messaging=self.messaging,
            llm=self.llm,
        )
        self.runners[agent.id] = runner
        runner.start()
        AGENT_ACTIVE.set(len(self.runners))

    async def _stop_runner(self, agent_id: int) -> None:
        """Stop and remove an agent runner."""
        runner = self.runners.pop(agent_id, None)
        if runner:
            await runner.stop()
            AGENT_ACTIVE.set(len(self.runners))

    # ---- backtest gate -----------------------------------------------------
    async def run_backtest_gate(self, agent_id: int) -> bool:
        """Submit a backtest via the API server and evaluate results.

        On success, transitions agent from backtesting → paper.
        On failure, keeps agent in backtesting and logs reasons.
        """
        import os

        import httpx

        assert self.database is not None
        assert self.messaging is not None

        agent = await self.database.get_agent(agent_id)
        if not agent or agent.status != "backtesting":
            return False

        try:
            config = AgentConfig(**agent.config_json)
        except Exception as e:
            logger.error("Agent %d invalid config for backtest: %s", agent_id, e)
            return False

        symbol = config.target.symbols[0] if config.target.symbols else "BTCUSDT"
        api_base = os.environ.get("API_SERVER_URL", "http://api-server:8000")
        api_key = os.environ.get("API_KEY", "")

        headers = {"X-API-Key": api_key} if api_key else {}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(360.0)) as client:
                # Submit backtest job
                resp = await client.post(
                    f"{api_base}/api/backtests",
                    json={
                        "symbol": symbol,
                        "start": "2024-01-01",
                        "end": "2025-01-01",
                        "strategy_name": config.strategy_name,
                        "strategy_params": config.strategy_params if isinstance(config.strategy_params, dict) else None,
                    },
                    headers=headers,
                )
                if resp.status_code != 202:
                    raise RuntimeError(f"Backtest submit failed: {resp.status_code} {resp.text}")

                job_id = resp.json().get("job_id")
                if not job_id:
                    raise RuntimeError("No job_id in backtest response")

                logger.info("Agent %d backtest submitted: job_id=%s", agent_id, job_id)

                # Poll for completion (max 5 minutes)
                for _ in range(60):
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        f"{api_base}/api/backtests/{job_id}",
                        headers=headers,
                    )
                    if status_resp.status_code != 200:
                        continue
                    job_data = status_resp.json()
                    job_status = job_data.get("status")
                    if job_status == "completed":
                        result = job_data.get("result_json", {})
                        break
                    elif job_status == "failed":
                        raise RuntimeError(f"Backtest failed: {job_data.get('error', 'unknown')}")
                else:
                    raise RuntimeError("Backtest timed out after 5 minutes")

        except Exception as e:
            logger.error("Agent %d backtest request failed: %s", agent_id, e)
            await self.database.create_agent_decision(
                AgentDecision(
                    agent_id=agent_id,
                    phase="learn",
                    decision_json={"gate": "backtest", "error": str(e)},
                    outcome_json={"passed": False},
                )
            )
            return False

        if not result:
            logger.warning("Agent %d backtest returned no results", agent_id)
            return False

        passed, failures = BacktestGate.evaluate(result, config.backtest_requirements)

        # Record gate evaluation
        await self.database.create_agent_decision(
            AgentDecision(
                agent_id=agent_id,
                phase="learn",
                decision_json={"gate": "backtest", "result": result},
                outcome_json={"passed": passed, "failures": failures},
            )
        )

        if passed:
            logger.info("Agent %d passed backtest gate → paper", agent_id)
            await AgentStateMachine.transition(
                self.database, agent_id, "backtesting", "paper", self.messaging
            )
            # Start the runner for paper trading
            updated = await self.database.get_agent(agent_id)
            if updated:
                await self._start_runner(updated)
            return True
        else:
            logger.info("Agent %d failed backtest gate: %s", agent_id, failures)
            # Transition to paused so the agent can be restarted
            await AgentStateMachine.transition(
                self.database, agent_id, "backtesting", "paused", self.messaging
            )
            return False

    # ---- paper gate --------------------------------------------------------
    async def run_paper_gate(self, agent_id: int) -> bool:
        """Evaluate paper trading performance and potentially advance to live.

        On success, transitions agent from paper → live.
        On failure, transitions agent back to backtesting.
        """
        assert self.database is not None

        agent = await self.database.get_agent(agent_id)
        if not agent or agent.status != "paper":
            return False

        try:
            config = AgentConfig(**agent.config_json)
        except Exception:
            return False

        # Retrieve Sharpe from the most recent backtest gate decision
        backtest_sharpe = 0.0
        decisions = await self.database.get_agent_decisions(agent_id, limit=50)
        for d in decisions:
            if d.decision_json.get("gate") == "backtest" and d.outcome_json.get("passed"):
                result = d.decision_json.get("result", {})
                stats = result.get("stats", result)
                backtest_sharpe = float(stats.get("sharpe_ratio", stats.get("sharpe", 0)))
                break

        passed, failures = await PaperGate.evaluate(
            self.database,
            agent_id,
            config.paper_requirements,
            backtest_sharpe=backtest_sharpe,
        )

        await self.database.create_agent_decision(
            AgentDecision(
                agent_id=agent_id,
                phase="learn",
                decision_json={"gate": "paper"},
                outcome_json={"passed": passed, "failures": failures},
            )
        )

        if passed:
            logger.info("Agent %d passed paper gate → live", agent_id)
            await AgentStateMachine.transition(
                self.database, agent_id, "paper", "live", self.messaging
            )
            return True
        else:
            logger.info("Agent %d failed paper gate: %s — pausing", agent_id, failures)
            await self._stop_runner(agent_id)
            await AgentStateMachine.transition(
                self.database, agent_id, "paper", "paused", self.messaging
            )
            return False

    # ---- NATS callbacks ----------------------------------------------------
    async def _on_market_data(self, msg: Any) -> None:
        """Forward market data to all active runners."""
        for runner in self.runners.values():
            try:
                await runner.handle_market_data(msg)
            except Exception:
                pass

    async def _on_execution_report(self, msg: Any) -> None:
        """Forward execution reports to the relevant agent runner."""
        for runner in self.runners.values():
            try:
                await runner.handle_execution_report(msg)
            except Exception:
                pass

    async def _on_agent_command(self, msg: Any) -> None:
        """Handle agent lifecycle commands from the API server."""
        try:
            data = json.loads(msg.data) if isinstance(msg.data, (bytes, str)) else msg.data
            command = data.get("command")
            agent_id = data.get("agent_id")

            if not command or not agent_id:
                return

            assert self.database is not None

            if command == "start_backtest":
                asyncio.create_task(self.run_backtest_gate(agent_id))
            elif command == "check_paper_gate":
                asyncio.create_task(self.run_paper_gate(agent_id))
            elif command == "stop":
                await self._stop_runner(agent_id)
            elif command == "start":
                agent = await self.database.get_agent(agent_id)
                if agent and agent.status in ("paper", "live"):
                    await self._start_runner(agent)
        except Exception as e:
            logger.error("Agent command handler error: %s", e)


# ---------------------------------------------------------------------------
# Module-level app creation
# ---------------------------------------------------------------------------
service = AgentOrchestratorService()
app: FastAPI = create_app(service)
