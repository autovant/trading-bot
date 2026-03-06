"""
Intelligence API — Real-time market analysis, agent monitoring, and AI-driven insights.

Replaces the frontend mock AI service with server-side computation + LLM synthesis.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.database import DatabaseManager

logger = logging.getLogger(__name__)

intelligence_router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])

COPILOT_PROXY_URL = os.getenv("COPILOT_PROXY_URL", "http://copilot-proxy:8087")

# ---------------------------------------------------------------------------
# Dependency stubs (overridden in main.py)
# ---------------------------------------------------------------------------

def get_db():
    raise NotImplementedError

def get_exchange():
    raise NotImplementedError

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MarketPulse(BaseModel):
    """Lightweight real-time market snapshot — no LLM call."""
    symbol: str
    price: float
    price_change_pct: float
    regime: str  # trending_up, trending_down, ranging, volatile
    rsi: float
    ema_20: float
    ema_50: float
    atr: float
    atr_pct: float
    volume_ratio: float  # current volume / average volume
    obi: float  # order book imbalance -1..1
    support: float
    resistance: float
    momentum: str  # bullish, bearish, neutral
    timestamp: float


class MarketAnalysisResponse(BaseModel):
    """Full LLM-synthesised market analysis."""
    symbol: str
    sentiment: str  # BULLISH, BEARISH, NEUTRAL
    summary: str
    support_level: float
    resistance_level: float
    signal: str  # LONG, SHORT, WAIT
    confidence: int
    regime: str
    key_levels: List[float]
    indicators: Dict[str, Any]
    risk_factors: List[str]


class TradeSuggestionResponse(BaseModel):
    """LLM-synthesised trade setup."""
    symbol: str
    direction: str  # LONG, SHORT, WAIT
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: int
    reasoning: str
    risk_reward: float
    position_size_pct: float
    invalidation: str


class AgentBriefing(BaseModel):
    """Portfolio-level agent intelligence briefing."""
    total_agents: int
    active_agents: int
    portfolio_equity: float
    portfolio_pnl: float
    top_performer: Optional[Dict[str, Any]] = None
    worst_performer: Optional[Dict[str, Any]] = None
    agents_summary: List[Dict[str, Any]]
    risk_alerts: List[str]
    recommendations: List[str]
    correlation_warnings: List[str]


class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    response: str
    market_analysis: Optional[MarketAnalysisResponse] = None
    trade_suggestion: Optional[TradeSuggestionResponse] = None


# ---------------------------------------------------------------------------
# Technical indicator computation (pure Python, no external deps)
# ---------------------------------------------------------------------------

def _compute_sma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    return sum(closes[-period:]) / period


def _compute_ema(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    multiplier = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _compute_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    # Use only last `period` changes
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)
    return sum(true_ranges[-period:]) / period


def _compute_bollinger(closes: List[float], period: int = 20, std_dev: float = 2.0):
    if len(closes) < period:
        p = closes[-1] if closes else 0.0
        return p, p, p
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = variance ** 0.5
    return sma - std_dev * std, sma, sma + std_dev * std


def _detect_regime(closes: List[float], atr: float) -> str:
    if len(closes) < 50:
        return "ranging"
    ema_20 = _compute_ema(closes, 20)
    ema_50 = _compute_ema(closes, 50)
    price = closes[-1]
    # Volatility check
    atr_pct = (atr / price * 100) if price > 0 else 0
    if atr_pct > 3.0:
        return "volatile"
    # Trend check
    if ema_20 > ema_50 and price > ema_20:
        return "trending_up"
    if ema_20 < ema_50 and price < ema_20:
        return "trending_down"
    return "ranging"


def _find_support_resistance(highs: List[float], lows: List[float], closes: List[float]):
    if len(closes) < 20:
        p = closes[-1] if closes else 0.0
        return p * 0.98, p * 1.02
    # Simple: recent swing low and swing high from last 50 candles
    window = min(50, len(closes))
    recent_lows = lows[-window:]
    recent_highs = highs[-window:]
    support = min(recent_lows)
    resistance = max(recent_highs)
    return support, resistance


def _compute_obi(order_book: Optional[Dict]) -> float:
    """Order Book Imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol). Returns -1..1."""
    if not order_book:
        return 0.0
    bids = order_book.get("bids", [])
    asks = order_book.get("asks", [])
    bid_vol = sum(float(b[1]) if isinstance(b, (list, tuple)) else float(b.get("size", 0)) for b in bids[:10])
    ask_vol = sum(float(a[1]) if isinstance(a, (list, tuple)) else float(a.get("size", 0)) for a in asks[:10])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def _build_market_context(candles: List[Dict], order_book: Optional[Dict] = None) -> Dict[str, Any]:
    """Compute all indicators from raw candle data."""
    if not candles:
        return {}
    closes = [float(c.get("close", c.get("c", 0))) for c in candles]
    highs = [float(c.get("high", c.get("h", 0))) for c in candles]
    lows = [float(c.get("low", c.get("l", 0))) for c in candles]
    volumes = [float(c.get("volume", c.get("v", 0))) for c in candles]

    price = closes[-1] if closes else 0.0
    rsi = _compute_rsi(closes)
    ema_20 = _compute_ema(closes, 20)
    ema_50 = _compute_ema(closes, 50)
    sma_200 = _compute_sma(closes, 200) if len(closes) >= 200 else _compute_sma(closes, len(closes))
    atr = _compute_atr(highs, lows, closes)
    atr_pct = (atr / price * 100) if price > 0 else 0
    bb_lower, bb_mid, bb_upper = _compute_bollinger(closes)
    support, resistance = _find_support_resistance(highs, lows, closes)
    regime = _detect_regime(closes, atr)
    obi = _compute_obi(order_book)

    # Volume analysis
    avg_volume = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
    current_volume = volumes[-1] if volumes else 0
    volume_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    # Price change
    if len(closes) >= 2:
        price_change_pct = ((closes[-1] - closes[-2]) / closes[-2] * 100) if closes[-2] != 0 else 0
    else:
        price_change_pct = 0.0

    # Momentum assessment
    if rsi > 60 and ema_20 > ema_50:
        momentum = "bullish"
    elif rsi < 40 and ema_20 < ema_50:
        momentum = "bearish"
    else:
        momentum = "neutral"

    return {
        "price": price,
        "price_change_pct": round(price_change_pct, 4),
        "rsi": round(rsi, 2),
        "ema_20": round(ema_20, 2),
        "ema_50": round(ema_50, 2),
        "sma_200": round(sma_200, 2),
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 4),
        "bb_lower": round(bb_lower, 2),
        "bb_mid": round(bb_mid, 2),
        "bb_upper": round(bb_upper, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "regime": regime,
        "obi": round(obi, 4),
        "volume_ratio": round(volume_ratio, 2),
        "momentum": momentum,
        "current_volume": round(current_volume, 2),
        "avg_volume_20": round(avg_volume, 2),
    }


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

async def _call_llm(system_prompt: str, user_prompt: str, json_mode: bool = True, max_tokens: int = 1024) -> str:
    """Call the LLM proxy and return raw content string."""
    body: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(f"{COPILOT_PROXY_URL}/v1/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

MARKET_ANALYSIS_SYSTEM_PROMPT = """You are an elite institutional quantitative analyst embedded in a crypto trading terminal. You receive computed technical indicators and must produce a precise market analysis.

Your analysis must be:
- Actionable: Clear sentiment, signal direction, confidence level
- Data-driven: Reference the specific indicator values provided
- Risk-aware: Identify key risks and invalidation levels
- Concise: Professional tone, no filler

Respond in JSON only:
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "2-3 sentence analysis referencing specific indicators",
  "signal": "LONG" | "SHORT" | "WAIT",
  "confidence": 0-100,
  "key_levels": [price1, price2, ...],
  "risk_factors": ["risk1", "risk2"]
}"""

TRADE_SETUP_SYSTEM_PROMPT = """You are an elite institutional trade structuring specialist for crypto perpetual futures. Given market indicators, positions, and risk metrics, produce a precise trade setup.

Rules:
- Stop loss must be at a logical technical level (support/resistance, ATR-based)
- Take profit should give at least 2:1 risk-reward
- Position size should be conservative (1-5% of equity) adjusted for volatility
- If conditions are unclear, return direction "WAIT"
- Entry should be at or near current price, adjusted for order book imbalance

Respond in JSON only:
{
  "direction": "LONG" | "SHORT" | "WAIT",
  "entry_price": number,
  "stop_loss": number,
  "take_profit": number,
  "confidence": 0-100,
  "reasoning": "2-3 sentence explanation referencing indicators",
  "risk_reward": number,
  "position_size_pct": number (1-5),
  "invalidation": "condition that invalidates this setup"
}"""

CHAT_SYSTEM_PROMPT = """You are the Cupertino Quant System — an elite AI trading co-pilot embedded in an institutional crypto trading platform. You have access to real-time market data, agent performance metrics, and risk analytics.

Your persona:
- Speak like a senior quant trader at a top prop firm
- Be direct, precise, data-driven
- Reference specific numbers and indicators when available
- Never give financial advice disclaimers — you are an internal tool, not a retail advisor
- When asked about market conditions, reference the live data provided in context

You are monitoring multiple AI trading agents that execute strategies autonomously. You can analyze their performance, suggest optimizations, and flag risks.

If the user asks about market analysis or trade setups and you have market context, provide actionable insights. Otherwise, engage conversationally about trading strategy, risk management, and agent performance."""

AGENT_BRIEFING_SYSTEM_PROMPT = """You are a portfolio risk analyst reviewing AI trading agent performance. Given agent metrics and portfolio data, produce actionable recommendations.

Focus on:
- Which agents are performing well vs poorly
- Correlation risk between agent positions
- Agents that should be paused, scaled up, or parameter-tuned
- Portfolio-level risk concentration

Respond in JSON only:
{
  "recommendations": ["action1", "action2", ...],
  "correlation_warnings": ["warning1", ...],
  "risk_alerts": ["alert1", ...]
}"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@intelligence_router.get("/pulse", response_model=MarketPulse)
async def get_market_pulse(
    symbol: str = "BTCUSDT",
    interval: str = "15",
    exchange=Depends(get_exchange),
):
    """Real-time market pulse — pure computation, no LLM call. Fast."""
    try:
        klines, _ = await exchange.get_klines(symbol, interval, 200)
        candles = []
        for k in klines:
            if isinstance(k, dict):
                candles.append(k)
            elif isinstance(k, (list, tuple)) and len(k) >= 6:
                candles.append({"open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5]})

        # Attempt to get order book for OBI
        order_book = None
        try:
            order_book = await exchange.get_order_book(symbol)
        except Exception as e:
            logger.debug("Order book fetch failed for %s: %s", symbol, e)

        ctx = _build_market_context(candles, order_book)
        if not ctx:
            raise HTTPException(status_code=503, detail="No market data available")

        return MarketPulse(
            symbol=symbol,
            price=ctx["price"],
            price_change_pct=ctx["price_change_pct"],
            regime=ctx["regime"],
            rsi=ctx["rsi"],
            ema_20=ctx["ema_20"],
            ema_50=ctx["ema_50"],
            atr=ctx["atr"],
            atr_pct=ctx["atr_pct"],
            volume_ratio=ctx["volume_ratio"],
            obi=ctx["obi"],
            support=ctx["support"],
            resistance=ctx["resistance"],
            momentum=ctx["momentum"],
            timestamp=time.time(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Market pulse failed")
        raise HTTPException(status_code=500, detail="Failed to compute market pulse") from e


@intelligence_router.post("/market-analysis", response_model=MarketAnalysisResponse)
async def analyze_market(
    symbol: str = "BTCUSDT",
    interval: str = "15",
    exchange=Depends(get_exchange),
    db: DatabaseManager = Depends(get_db),
):
    """Full AI-powered market analysis with LLM synthesis."""
    try:
        klines, _ = await exchange.get_klines(symbol, interval, 200)
        candles = []
        for k in klines:
            if isinstance(k, dict):
                candles.append(k)
            elif isinstance(k, (list, tuple)) and len(k) >= 6:
                candles.append({"open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5]})

        order_book = None
        try:
            order_book = await exchange.get_order_book(symbol)
        except Exception as e:
            logger.debug("Order book fetch failed for %s: %s", symbol, e)

        ctx = _build_market_context(candles, order_book)
        if not ctx:
            raise HTTPException(status_code=503, detail="No market data available")

        # Get positions for additional context
        positions = []
        try:
            positions = await db.get_positions()
        except Exception as e:
            logger.debug("Position fetch failed: %s", e)

        user_prompt = f"""Analyze {symbol} on the {interval}m timeframe.

Current Market Data:
- Price: ${ctx['price']:,.2f} ({ctx['price_change_pct']:+.2f}%)
- RSI(14): {ctx['rsi']:.1f}
- EMA(20): ${ctx['ema_20']:,.2f} | EMA(50): ${ctx['ema_50']:,.2f} | SMA(200): ${ctx['sma_200']:,.2f}
- Bollinger Bands: Lower ${ctx['bb_lower']:,.2f} | Mid ${ctx['bb_mid']:,.2f} | Upper ${ctx['bb_upper']:,.2f}
- ATR(14): ${ctx['atr']:,.2f} ({ctx['atr_pct']:.2f}% of price)
- Volume Ratio: {ctx['volume_ratio']:.2f}x average
- Order Book Imbalance: {ctx['obi']:+.3f} ({'bid-heavy' if ctx['obi'] > 0.1 else 'ask-heavy' if ctx['obi'] < -0.1 else 'balanced'})
- Detected Regime: {ctx['regime']}
- Momentum: {ctx['momentum']}
- Support: ${ctx['support']:,.2f} | Resistance: ${ctx['resistance']:,.2f}

Open Positions: {len(positions)}"""

        content = await _call_llm(MARKET_ANALYSIS_SYSTEM_PROMPT, user_prompt)
        result = json.loads(content)

        return MarketAnalysisResponse(
            symbol=symbol,
            sentiment=result.get("sentiment", "NEUTRAL"),
            summary=result.get("summary", "Analysis unavailable"),
            support_level=ctx["support"],
            resistance_level=ctx["resistance"],
            signal=result.get("signal", "WAIT"),
            confidence=min(100, max(0, result.get("confidence", 50))),
            regime=ctx["regime"],
            key_levels=result.get("key_levels", [ctx["support"], ctx["resistance"]]),
            indicators={
                "rsi": ctx["rsi"],
                "ema_20": ctx["ema_20"],
                "ema_50": ctx["ema_50"],
                "atr": ctx["atr"],
                "bb_lower": ctx["bb_lower"],
                "bb_upper": ctx["bb_upper"],
                "volume_ratio": ctx["volume_ratio"],
                "obi": ctx["obi"],
            },
            risk_factors=result.get("risk_factors", []),
        )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.warning("LLM proxy error: %s", e.response.status_code)
        raise HTTPException(status_code=502, detail="AI analysis service unavailable") from e
    except Exception as e:
        logger.exception("Market analysis failed")
        raise HTTPException(status_code=500, detail="Market analysis failed") from e


@intelligence_router.post("/trade-setup", response_model=TradeSuggestionResponse)
async def get_trade_setup(
    symbol: str = "BTCUSDT",
    interval: str = "15",
    exchange=Depends(get_exchange),
    db: DatabaseManager = Depends(get_db),
):
    """AI-generated trade setup with entry, stop loss, take profit."""
    try:
        klines, _ = await exchange.get_klines(symbol, interval, 200)
        candles = []
        for k in klines:
            if isinstance(k, dict):
                candles.append(k)
            elif isinstance(k, (list, tuple)) and len(k) >= 6:
                candles.append({"open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5]})

        order_book = None
        try:
            order_book = await exchange.get_order_book(symbol)
        except Exception as e:
            logger.debug("Order book fetch failed for %s: %s", symbol, e)

        ctx = _build_market_context(candles, order_book)
        if not ctx:
            raise HTTPException(status_code=503, detail="No market data available")

        # Get positions and account for risk context
        positions = []
        equity = 10000.0
        try:
            positions = await db.get_positions()
            balance = await exchange.get_balance()
            pos_data = await exchange.get_positions()
            unrealized = sum(p.get("unrealized_pnl", 0) for p in pos_data) if pos_data else 0
            equity = balance + unrealized
        except Exception as e:
            logger.debug("Position/balance fetch failed: %s", e)

        user_prompt = f"""Generate a trade setup for {symbol} on {interval}m timeframe.

Market Data:
- Price: ${ctx['price']:,.2f} ({ctx['price_change_pct']:+.2f}%)
- RSI(14): {ctx['rsi']:.1f}
- EMA(20): ${ctx['ema_20']:,.2f} | EMA(50): ${ctx['ema_50']:,.2f}
- ATR(14): ${ctx['atr']:,.2f} ({ctx['atr_pct']:.2f}%)
- Bollinger: Lower ${ctx['bb_lower']:,.2f} | Upper ${ctx['bb_upper']:,.2f}
- Volume: {ctx['volume_ratio']:.2f}x average
- OBI: {ctx['obi']:+.3f}
- Regime: {ctx['regime']} | Momentum: {ctx['momentum']}
- Support: ${ctx['support']:,.2f} | Resistance: ${ctx['resistance']:,.2f}

Portfolio Context:
- Equity: ${equity:,.2f}
- Open Positions: {len(positions)}"""

        content = await _call_llm(TRADE_SETUP_SYSTEM_PROMPT, user_prompt)
        result = json.loads(content)

        direction = result.get("direction", "WAIT")
        entry = result.get("entry_price", ctx["price"])
        sl = result.get("stop_loss", ctx["price"] * 0.98)
        tp = result.get("take_profit", ctx["price"] * 1.04)

        # Compute risk:reward
        risk = abs(entry - sl) if entry != sl else 1
        reward = abs(tp - entry) if tp != entry else 1
        rr = round(reward / risk, 2) if risk > 0 else 0

        return TradeSuggestionResponse(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry, 2),
            stop_loss=round(sl, 2),
            take_profit=round(tp, 2),
            confidence=min(100, max(0, result.get("confidence", 50))),
            reasoning=result.get("reasoning", ""),
            risk_reward=rr,
            position_size_pct=min(5.0, max(0.5, result.get("position_size_pct", 2.0))),
            invalidation=result.get("invalidation", ""),
        )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.warning("LLM proxy error for trade setup: %s", e.response.status_code)
        raise HTTPException(status_code=502, detail="AI trade setup service unavailable") from e
    except Exception as e:
        logger.exception("Trade setup failed")
        raise HTTPException(status_code=500, detail="Trade setup generation failed") from e


@intelligence_router.get("/agent-briefing", response_model=AgentBriefing)
async def get_agent_briefing(
    days: int = Query(7, ge=1, le=90),
    db: DatabaseManager = Depends(get_db),
    exchange=Depends(get_exchange),
):
    """Portfolio-level agent intelligence briefing with LLM recommendations."""
    try:
        agents = await db.list_agents()
        if not agents:
            return AgentBriefing(
                total_agents=0,
                active_agents=0,
                portfolio_equity=0,
                portfolio_pnl=0,
                agents_summary=[],
                risk_alerts=["No agents configured"],
                recommendations=["Create your first trading agent to get started"],
                correlation_warnings=[],
            )

        active_statuses = {"backtesting", "paper", "live"}
        active_agents = [a for a in agents if a.status in active_statuses]

        # Gather performance for each agent
        agents_data = []
        total_pnl = 0.0
        for agent in agents:
            perf = []
            try:
                perf = await db.get_agent_performance(agent.id, days=days)
            except Exception:
                pass

            total_agent_pnl = sum(p.realized_pnl for p in perf) if perf else 0
            win_rate = perf[-1].win_rate if perf else 0
            sharpe = perf[-1].sharpe_rolling_30d if perf else 0
            equity = perf[-1].equity if perf else agent.allocation_usd
            max_dd = max((p.max_drawdown for p in perf), default=0)
            total_pnl += total_agent_pnl

            agents_data.append({
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "strategy": agent.strategy_name or "llm",
                "allocation_usd": agent.allocation_usd,
                "pnl": round(total_agent_pnl, 2),
                "win_rate": round(win_rate, 2),
                "sharpe": round(sharpe, 2),
                "equity": round(equity, 2),
                "max_drawdown": round(max_dd, 4),
            })

        # Sort for top/worst
        sorted_by_pnl = sorted(agents_data, key=lambda x: x["pnl"], reverse=True)
        top = sorted_by_pnl[0] if sorted_by_pnl else None
        worst = sorted_by_pnl[-1] if len(sorted_by_pnl) > 1 else None

        # Portfolio equity
        portfolio_equity = sum(a["equity"] for a in agents_data)

        # Get LLM recommendations if we have agents
        recommendations = []
        risk_alerts = []
        correlation_warnings = []

        if active_agents and agents_data:
            try:
                agents_summary_text = "\n".join(
                    f"- {a['name']} ({a['strategy']}): status={a['status']}, PnL=${a['pnl']:+.2f}, "
                    f"win_rate={a['win_rate']:.0%}, sharpe={a['sharpe']:.2f}, max_dd={a['max_drawdown']:.2%}"
                    for a in agents_data
                )
                user_prompt = f"""Review these AI trading agents (last {days} days):

{agents_summary_text}

Portfolio: ${portfolio_equity:,.2f} total equity, ${total_pnl:+,.2f} total PnL, {len(active_agents)} active agents."""

                content = await _call_llm(AGENT_BRIEFING_SYSTEM_PROMPT, user_prompt, max_tokens=512)
                result = json.loads(content)
                recommendations = result.get("recommendations", [])
                risk_alerts = result.get("risk_alerts", [])
                correlation_warnings = result.get("correlation_warnings", [])
            except Exception as e:
                logger.warning("LLM briefing failed, returning data-only briefing: %s", e)
                # Fallback: generate basic recommendations without LLM
                for a in agents_data:
                    if a["max_drawdown"] > 0.15:
                        risk_alerts.append(f"{a['name']}: drawdown exceeds 15% ({a['max_drawdown']:.1%})")
                    if a["win_rate"] < 0.35 and a["status"] in active_statuses:
                        recommendations.append(f"Consider pausing {a['name']} — win rate is only {a['win_rate']:.0%}")

        return AgentBriefing(
            total_agents=len(agents),
            active_agents=len(active_agents),
            portfolio_equity=round(portfolio_equity, 2),
            portfolio_pnl=round(total_pnl, 2),
            top_performer=top,
            worst_performer=worst,
            agents_summary=agents_data,
            risk_alerts=risk_alerts,
            recommendations=recommendations,
            correlation_warnings=correlation_warnings,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Agent briefing failed")
        raise HTTPException(status_code=500, detail="Agent briefing failed") from e


@intelligence_router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    req: ChatRequest,
    symbol: str = "BTCUSDT",
    exchange=Depends(get_exchange),
    db: DatabaseManager = Depends(get_db),
):
    """Free-form chat with the AI, enriched with live market context."""
    try:
        # Build live context
        market_context = ""
        try:
            klines, _ = await exchange.get_klines(symbol, "15", 100)
            candles = []
            for k in klines:
                if isinstance(k, dict):
                    candles.append(k)
                elif isinstance(k, (list, tuple)) and len(k) >= 6:
                    candles.append({"open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5]})

            ctx = _build_market_context(candles)
            if ctx:
                market_context = f"""
Live Market ({symbol}):
- Price: ${ctx['price']:,.2f} ({ctx['price_change_pct']:+.2f}%)
- RSI: {ctx['rsi']:.1f} | EMA20: ${ctx['ema_20']:,.2f} | EMA50: ${ctx['ema_50']:,.2f}
- ATR: ${ctx['atr']:,.2f} ({ctx['atr_pct']:.2f}%)
- Regime: {ctx['regime']} | Momentum: {ctx['momentum']}
- Volume: {ctx['volume_ratio']:.2f}x avg | OBI: {ctx['obi']:+.3f}
- Support: ${ctx['support']:,.2f} | Resistance: ${ctx['resistance']:,.2f}"""
        except Exception:
            market_context = "(Market data temporarily unavailable)"

        # Agent context
        agent_context = ""
        try:
            agents = await db.list_agents()
            if agents:
                active = [a for a in agents if a.status in {"backtesting", "paper", "live"}]
                agent_context = f"\nActive Agents: {len(active)}/{len(agents)} total"
                for a in active[:5]:
                    agent_context += f"\n- {a.name} ({a.strategy_name or 'llm'}): {a.status}"
        except Exception:
            pass

        # Position context
        position_context = ""
        try:
            positions = await db.get_positions()
            if positions:
                position_context = f"\nOpen Positions: {len(positions)}"
                for p in positions[:3]:
                    position_context += f"\n- {p.symbol} {p.side} {p.size} @ {p.entry_price}"
        except Exception:
            pass

        # Additional user context
        extra = ""
        if req.context:
            extra = f"\nUser-provided context: {json.dumps(req.context)}"

        full_context = f"{market_context}{agent_context}{position_context}{extra}"

        user_prompt = f"""Context:{full_context}

User: {req.message}"""

        content = await _call_llm(CHAT_SYSTEM_PROMPT, user_prompt, json_mode=False, max_tokens=1024)

        return ChatResponse(response=content)
    except httpx.HTTPStatusError as e:
        logger.warning("Chat LLM error: %s", e.response.status_code)
        raise HTTPException(status_code=502, detail="AI chat service unavailable") from e
    except Exception as e:
        logger.exception("Chat failed")
        raise HTTPException(status_code=500, detail="Chat service failed") from e
