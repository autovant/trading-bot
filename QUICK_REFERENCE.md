# Quick Reference Card

## 🚀 Getting Started (5 Minutes)

```bash
# 1. Setup
./setup.sh

# 2. Configure API keys
cp .env.example .env
# Edit .env with your Zoomex API credentials

# 3. Validate
python tools/validate_setup.py --config configs/zoomex_example.yaml

# 4. Start paper trading
python run_bot.py --mode paper --config configs/zoomex_example.yaml
```

## 📋 Essential Commands

### Validation
```bash
# Validate testnet setup
python tools/validate_setup.py --config configs/zoomex_example.yaml --mode testnet

# Validate live setup
python tools/validate_setup.py --config configs/zoomex_example.yaml --mode live

# Dry run (test config without starting)
python run_bot.py --mode paper --config configs/zoomex_example.yaml --dry-run
```

### Trading
```bash
# Paper trading (simulated)
python run_bot.py --mode paper --config configs/zoomex_example.yaml

# Testnet trading (fake money)
python run_bot.py --mode testnet --config configs/zoomex_example.yaml

# Live trading (real money - requires confirmation)
python run_bot.py --mode live --config configs/zoomex_example.yaml
```

### Monitoring
```bash
# Real-time dashboard
python tools/monitor.py --config configs/zoomex_example.yaml --mode testnet

# View logs
tail -f logs/trading.log

# View recent logs
tail -n 100 logs/trading.log
```

### Backtesting
```bash
# Basic backtest
python tools/backtest_perps.py --symbol SOLUSDT --start 2024-01-01 --end 2024-12-31

# With custom parameters
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --interval 5 \
  --initial-balance 1000 \
  --output results.json

# View results
cat results.json | jq '.metrics'
```

## ⚙️ Configuration Quick Edit

### Risk Parameters (configs/zoomex_example.yaml)
```yaml
perps:
  riskPct: 0.005          # 0.5% risk per trade
  stopLossPct: 0.01       # 1% stop-loss
  takeProfitPct: 0.03     # 3% take-profit
  leverage: 2             # 2x leverage
  cashDeployCap: 500      # Max $500 per position
  consecutiveLossLimit: 3 # Stop after 3 losses
```

### Strategy Parameters
```yaml
perps:
  fastPeriod: 10          # Fast MA (10 candles)
  slowPeriod: 30          # Slow MA (30 candles)
  rsiPeriod: 14           # RSI period
  rsiThreshold: 50        # RSI entry threshold
  volumeThreshold: 1.2    # Volume multiplier
  earlyExitOnCross: true  # Exit on MA cross
```

## 🔧 Command Line Overrides

```bash
# Override symbol
python run_bot.py --mode testnet --symbol BTCUSDT

# Override leverage
python run_bot.py --mode testnet --leverage 3

# Override risk
python run_bot.py --mode testnet --risk-pct 0.01

# Multiple overrides
python run_bot.py --mode testnet --symbol ETHUSDT --leverage 2 --risk-pct 0.005
```

## 📊 Key Metrics to Monitor

### Account Health
- Equity balance
- Current position size
- Leverage used
- Available margin

### Performance
- Win rate (target: >50%)
- Profit factor (target: >1.5)
- Average win vs average loss
- Maximum drawdown (keep <20%)

### Risk Management
- Consecutive losses (circuit breaker at 3)
- Position size vs equity
- Stop-loss distance
- Risk-reward ratio (3:1)

## 🚨 Safety Checklist

### Before Starting
- [ ] API credentials set in .env
- [ ] Configuration validated
- [ ] Risk parameters reviewed
- [ ] Stop-loss and take-profit set
- [ ] Circuit breaker enabled
- [ ] Testnet tested first

### During Operation
- [ ] Monitor logs regularly
- [ ] Check position sizes
- [ ] Verify stop-loss placement
- [ ] Watch for circuit breaker
- [ ] Track consecutive losses
- [ ] Monitor account balance

### Emergency Procedures
```bash
# Stop the bot
Ctrl+C

# Check current position
python tools/monitor.py --config configs/zoomex_example.yaml --mode testnet

# Manual close (if needed)
# Use Zoomex web interface to close positions manually
```

## 📁 File Locations

### Configuration
- Main config: `configs/zoomex_example.yaml`
- Environment: `.env`
- Example env: `.env.example`

### Logs
- Trading log: `logs/trading.log`
- Error log: Check console output

### Scripts
- Bot runner: `run_bot.py`
- Validation: `tools/validate_setup.py`
- Backtesting: `tools/backtest_perps.py`
- Monitoring: `tools/monitor.py`
- Setup: `setup.sh`

### Documentation
- Trading guide: `README_TRADING.md`
- Main README: `README.md`
- Status: `PRODUCTION_STATUS.md`
- Summary: `IMPLEMENTATION_SUMMARY.md`

## 🔍 Troubleshooting Quick Fixes

### API Connection Failed
```bash
# Check credentials
cat .env | grep ZOOMEX

# Validate setup
python tools/validate_setup.py --config configs/zoomex_example.yaml
```

### No Signals Generated
```bash
# Check if enough data
# Strategy needs 35+ candles for indicators

# Verify symbol is active
python tools/validate_setup.py --config configs/zoomex_example.yaml
```

### Position Size Too Small
```yaml
# Increase risk or check equity
perps:
  riskPct: 0.01  # Increase from 0.005
  cashDeployCap: 1000  # Increase from 500
```

### Circuit Breaker Triggered
```yaml
# Increase limit or disable
perps:
  consecutiveLossLimit: 5  # Increase from 3
  # Or set to null to disable
```

## 📞 Support Resources

- **Configuration Help**: See `configs/zoomex_example.yaml` comments
- **Trading Guide**: See `README_TRADING.md`
- **API Issues**: Check Zoomex API documentation
- **Strategy Details**: See `STRATEGY.md`
- **Troubleshooting**: See `README_TRADING.md` section 9

## 🎯 Recommended Workflow

### Day 1: Setup & Validation
1. Run `./setup.sh`
2. Configure `.env` with API keys
3. Run validation script
4. Review configuration

### Day 2-3: Paper Trading
1. Start paper mode
2. Monitor signals
3. Verify position sizing
4. Check risk calculations

### Day 4-5: Backtesting
1. Run backtests on historical data
2. Analyze performance metrics
3. Optimize parameters if needed
4. Validate strategy logic

### Day 6-7: Testnet Trading
1. Start testnet mode
2. Monitor real orders
3. Verify TP/SL execution
4. Test circuit breaker

### Week 2+: Live Trading (Optional)
1. Start with minimal positions
2. Monitor closely
3. Gradually increase size
4. Keep detailed logs

## ⚖️ Risk Disclaimer

**IMPORTANT**: Trading involves substantial risk of loss. This bot is provided as-is for educational purposes. Always test thoroughly on paper and testnet before risking real capital. Never invest more than you can afford to lose.

---

**Quick Start**: `./setup.sh && python run_bot.py --mode paper`
**Full Guide**: See `README_TRADING.md`
**Status**: See `PRODUCTION_STATUS.md`
