"""
Prometheus metrics definitions for the trading bot.
"""

from prometheus_client import Gauge, Histogram, Counter

# General Metrics
TRADING_MODE = Gauge(
    "trading_mode", "Current trading mode by service", ["service", "mode"]
)

# Latency Metrics
SIGNAL_ACK_LATENCY = Histogram(
    "signal_ack_latency_seconds",
    "Latency between signal generation and acknowledgement",
    ["mode"],
)

# Execution Metrics
MAKER_RATIO = Gauge("maker_ratio", "Ratio of maker trades", ["mode", "symbol"])

AVERAGE_SLIPPAGE_BPS = Gauge(
    "average_slippage_bps", "Average slippage in basis points", ["mode", "symbol"]
)

SPREAD_ATR_PCT = Gauge(
    "spread_atr_pct", "Spread as a percentage of ATR", ["mode", "symbol"]
)

REJECT_RATE = Gauge("reject_rate", "Rate of rejected orders", ["mode"])

# Risk Metrics
CIRCUIT_BREAKERS = Counter(
    "circuit_breakers_total", "Total number of circuit breaker events", ["mode"]
)
