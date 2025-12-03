# Perps Trading - Quick Reference

## Risk Limits Configuration

```yaml
perps:
  # Circuit breaker - stops after N consecutive losses
  consecutiveLossLimit: 3
  
  # Maximum margin ratio before blocking new entries (0.8 = 80%)
  maxMarginRatio: 0.8
  
  # API rate limiting
  maxRequestsPerSecond: 5
  maxRequestsPerMinute: 60
  
  # Position sizing
  riskPct: 0.005          # Risk 0.5% of equity per trade
  stopLossPct: 0.01       # 1% stop loss
  cashDeployCap: 0.20     # Max 20% of equity per position
```

## Risk Checks (Automatic)

### 1. Consecutive Loss Circuit Breaker
- **Trigger**: After N consecutive losing trades
- **Action**: Stops all new entries until manual reset
- **Config**: `consecutiveLossLimit`
- **Default**: 3 losses

### 2. Daily Loss Limit
- **Trigger**: Daily loss exceeds 5% of equity
- **Action**: Stops trading for remainder of day
- **Resets**: At start of new trading day (UTC)

### 3. Maximum Drawdown
- **Trigger**: Drawdown from peak exceeds 10%
- **Action**: Stops all new entries
- **Calculation**: `(peak_equity - current_equity) / peak_equity`

### 4. Margin Ratio Check
- **Trigger**: Current margin ratio exceeds configured limit
- **Action**: Blocks new position entries
- **Config**: `maxMarginRatio`
- **Default**: 80%

## Position Reconciliation

Runs automatically on service startup:
- Detects existing open positions
- Adopts position state (quantity, entry price, PnL)
- Prevents duplicate entries
- Logs reconciliation details

**Log Example**:
```
POSITION RECONCILIATION: Adopted existing position for SOLUSDT | 
Qty=0.500000 | Entry=$150.2500 | Unrealized PnL=$12.50
```

## PnL Tracking

### Automatic Tracking
- Checks closed positions every 5 minutes
- Records trade outcomes (win/loss)
- Updates consecutive loss counter
- Tracks daily PnL by date
- Maintains peak equity for drawdown calculations

### Manual Queries
```python
# Get current drawdown
drawdown = pnl_tracker.get_drawdown(current_equity)

# Get today's PnL
daily_pnl = pnl_tracker.get_daily_pnl()

# Get specific date PnL
pnl = pnl_tracker.get_daily_pnl("2024-01-15")

# Check consecutive losses
losses = pnl_tracker.consecutive_losses
```

## Order ID Generation

Idempotent order IDs prevent duplicate orders:

```python
from src.engine.order_id_generator import generate_order_id

# Generate deterministic ID
order_id = generate_order_id(
    symbol="BTCUSDT",
    side="Buy",
    timestamp=datetime.now(timezone.utc),
)
# Result: "BTCB143045e4ccc845"

# With nonce for uniqueness
order_id = generate_order_id(
    symbol="BTCUSDT",
    side="Buy",
    timestamp=datetime.now(timezone.utc),
    nonce="retry1",
)
```

## API Rate Limiting

Built-in throttling prevents API bans:
- **Per-second limit**: Configurable (default: 5 req/s)
- **Per-minute limit**: Configurable (default: 60 req/min)
- **Automatic backoff**: Sleeps when limits approached
- **Transparent**: No code changes needed

## Monitoring & Logs

### Key Log Messages

**Risk Limit Triggered**:
```
WARNING: Circuit breaker: 3 consecutive losses (limit=3)
WARNING: Daily loss limit exceeded: 5.20% (limit=5.00%)
WARNING: Drawdown limit exceeded: 10.50% (limit=10.00%)
WARNING: Margin ratio 85.00% exceeds limit 80.00%, skipping entry
```

**Position Reconciliation**:
```
INFO: No existing positions found for SOLUSDT
WARNING: POSITION RECONCILIATION: Adopted existing position...
```

**PnL Tracking**:
```
INFO: Trade recorded: PnL=$12.50 | Daily PnL=$45.30 | Consecutive losses=0
INFO: New peak equity: $10250.00
```

**Order Placement**:
```
INFO: Order placed: 1234567890 (order_link_id=BTCB143045e4ccc845)
```

## Testing

### Run All Tests
```bash
python -m pytest tests/test_risk_position_size.py tests/test_pnl_tracker.py tests/test_order_id_generator.py -v
```

### Run Specific Tests
```bash
# Position sizing
python -m pytest tests/test_risk_position_size.py -v

# PnL tracker
python -m pytest tests/test_pnl_tracker.py -v

# Order ID generator
python -m pytest tests/test_order_id_generator.py -v
```

## Troubleshooting

### Service Won't Start
**Issue**: Missing configuration fields
**Solution**: Add new fields to config YAML:
```yaml
perps:
  consecutiveLossLimit: 3
  maxMarginRatio: 0.8
  maxRequestsPerSecond: 5
  maxRequestsPerMinute: 60
```

### Trading Stopped
**Check**:
1. Consecutive losses: Review `pnl_tracker.consecutive_losses`
2. Daily PnL: Check if daily loss limit exceeded
3. Drawdown: Verify current drawdown vs limit
4. Margin ratio: Check if margin too high

**Reset**: Restart service (resets in-memory counters)

### Position Not Detected
**Issue**: Existing position not reconciled
**Check**:
- Position `positionIdx` matches config
- Position is for correct symbol
- API credentials have read permissions

**Logs**: Look for "POSITION RECONCILIATION" messages

### API Rate Limiting
**Issue**: "Too many requests" errors
**Solution**: Reduce rate limits in config:
```yaml
perps:
  maxRequestsPerSecond: 3  # Lower from 5
  maxRequestsPerMinute: 40 # Lower from 60
```

## Best Practices

### Configuration
1. **Start conservative**: Use default risk limits initially
2. **Test on testnet**: Validate configuration before live trading
3. **Monitor logs**: Watch for risk limit warnings
4. **Adjust gradually**: Increase limits slowly based on performance

### Risk Management
1. **Respect circuit breakers**: Don't override risk limits
2. **Monitor drawdown**: Track distance from peak equity
3. **Review daily PnL**: Check performance at end of each day
4. **Analyze losses**: Investigate consecutive loss patterns

### Operations
1. **Regular restarts**: Restart service periodically to clear state
2. **Log monitoring**: Set up alerts for risk limit warnings
3. **Backup configs**: Version control all configuration changes
4. **Test changes**: Validate config changes on testnet first

## API Reference

### PnLTracker
```python
tracker = PnLTracker()

# Update peak equity
tracker.update_peak_equity(current_equity: float)

# Get drawdown percentage
drawdown = tracker.get_drawdown(current_equity: float) -> float

# Record trade outcome
tracker.record_trade(pnl: float, timestamp: Optional[datetime])

# Get daily PnL
pnl = tracker.get_daily_pnl(date: Optional[str]) -> float

# Cleanup old records
tracker.cleanup_old_days(days_to_keep: int = 30)

# Access properties
tracker.peak_equity: float
tracker.consecutive_losses: int
tracker.daily_pnl: Dict[str, float]
tracker.trade_history: List[Dict]
```

### Order ID Generator
```python
from src.engine.order_id_generator import generate_order_id

order_id = generate_order_id(
    symbol: str,
    side: str,
    timestamp: Optional[datetime] = None,
    nonce: Optional[str] = None,
) -> str
```

### ZoomexV3Client (New Methods)
```python
# Get margin information
margin_info = await client.get_margin_info(symbol: str) -> Dict[str, Any]
# Returns: {"marginRatio": 0.75, "availableBalance": 5000.0}

# Get closed PnL
closed_pnl = await client.get_closed_pnl(
    symbol: str,
    start_time: Optional[int] = None,
    limit: int = 50,
) -> Dict[str, Any]
```

## Support

For issues or questions:
1. Check logs for error messages
2. Review configuration against examples
3. Run unit tests to verify installation
4. Consult `docs/PERPS_ENHANCEMENTS.md` for detailed documentation
