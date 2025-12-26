
from typing import Dict
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest

# Metrics required by PaperBroker (Standardizing naming)
AVERAGE_SLIPPAGE_BPS = Gauge(
    'paper_slippage_bps', 
    'Average slippage in basis points', 
    ['mode', 'symbol']
)
MAKER_RATIO = Gauge(
    'paper_maker_ratio', 
    'Ratio of maker fills', 
    ['mode', 'symbol']
)
SIGNAL_ACK_LATENCY = Histogram(
    'paper_signal_ack_latency_seconds', 
    'Latency from signal to acknowledgement', 
    ['mode']
)
TRADING_MODE = Gauge(
    'trading_mode_status',
    'Active trading mode status (1=active)',
    ['service', 'mode']
)


class MetricsManager:
    """Centralized metrics manager."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MetricsManager, cls).__new__(cls)
            cls._instance._initialize_metrics()
        return cls._instance

    def _initialize_metrics(self):
        self.registry = CollectorRegistry()
        
        # Business Metrics
        self.order_count = Counter(
            'trading_order_total', 
            'Total orders placed', 
            ['symbol', 'side', 'type', 'status'],
            registry=self.registry
        )
        self.trade_count = Counter(
            'trading_trade_total', 
            'Total trades executed', 
            ['symbol', 'side'],
            registry=self.registry
        )
        self.active_positions = Gauge(
            'trading_positions_active', 
            'Number of active positions', 
            ['symbol', 'side'],
            registry=self.registry
        )
        
        # System Metrics
        self.api_latency = Histogram(
            'api_request_duration_seconds', 
            'API request latency', 
            ['method', 'endpoint'],
            registry=self.registry
        )
        self.error_count = Counter(
            'system_error_total', 
            'Total system errors', 
            ['type', 'module'],
            registry=self.registry
        )
        
    def generate_latest(self):
        return generate_latest(self.registry)
        
    def content_type(self):
        return CONTENT_TYPE_LATEST

# Global instance
metrics = MetricsManager()
