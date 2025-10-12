
# Trading Strategy Documentation

## Overview

This document describes the complete trading strategy implementation used by the crypto trading bot. The strategy combines multiple timeframe analysis, regime detection, and sophisticated risk management.

## Strategy Components

### 1. Regime Detection (Daily Timeframe)

**Purpose**: Determine overall market conditions to filter trade direction.

**Indicators**:
- 200-period Exponential Moving Average (EMA)
- MACD (12, 26, 9)

**Logic**:
- **Bullish Regime**: Price > 200 EMA AND MACD > 0
- **Bearish Regime**: Price < 200 EMA AND MACD < 0
- **Neutral Regime**: Mixed conditions

**Weight in Confidence Score**: 25%

### 2. Setup Detection (4-Hour Timeframe)

**Purpose**: Identify favorable market structure for entries.

**Indicators**:
- Moving Average Stack: 8, 21, 55 EMAs
- ADX (14-period) for trend strength
- ATR (14-period) for volatility

**Bullish Setup Requirements**:
- EMA8 > EMA21 > EMA55 (ascending stack)
- ADX > 25 (strong trend)
- Price within 2 ATR of EMA8

**Bearish Setup Requirements**:
- EMA8 < EMA21 < EMA55 (descending stack)
- ADX > 25 (strong trend)
- Price within 2 ATR of EMA8

**Weight in Confidence Score**: 30%

### 3. Signal Generation (1-Hour Timeframe)

**Purpose**: Generate precise entry signals.

**Signal Types**:

#### Pullback Signals
- **Bullish**: Price pulls back to EMA21, RSI(14) < 40, then bounces
- **Bearish**: Price rallies to EMA21, RSI(14) > 60, then rejects

#### Breakout Signals
- **Bullish**: Price breaks above 20-period Donchian high with volume
- **Bearish**: Price breaks below 20-period Donchian low with volume

#### Divergence Signals
- **Bullish**: Price makes lower low, RSI makes higher low (k=3 pivots)
- **Bearish**: Price makes higher high, RSI makes lower high (k=3 pivots)

**Weight in Confidence Score**: 35%

### 4. Confidence Scoring System

**Scale**: 0-100 points

**Components**:
- Regime Alignment: 0-25 points
- Setup Quality: 0-30 points
- Signal Strength: 0-35 points
- Penalty Factors: -10 points maximum

**Penalty Factors**:
- High volatility (ATR > 2x average): -3 points
- Low volume (< 0.8x average): -3 points
- Conflicting timeframes: -4 points

**Trade Execution Thresholds**:
- Confidence ≥ 70: Full position size
- Confidence 50-69: Reduced position size (0.7x)
- Confidence < 50: No trade

### 5. Position Sizing

**Base Capital**: $1000
**Risk Per Trade**: 0.6% ($6)

**Calculation**:
```
Position Size = (Account Balance × Risk %) / (Entry Price - Stop Loss)
```

**Ladder Entry System**:
- Entry 1: 25% of position size at signal
- Entry 2: 35% of position size on confirmation
- Entry 3: 40% of position size on momentum

**Risk Weight Distribution**: [0.25, 0.35, 0.40]

### 6. Risk Management

#### Dual Stop System

**Soft Stop (Composite)**:
- ATR-based: 1.5 × ATR(14) from entry
- Support/Resistance: Key levels
- Time-based: Close after 48 hours if no progress

**Hard Stop (Server-side)**:
- Fixed at 2% account risk
- Cannot be modified once set
- Guaranteed execution

#### Crisis Mode

**Triggers**:
- Account drawdown > 10%
- 3 consecutive losses
- Volatility spike (ATR > 3x average)

**Actions**:
- Reduce position sizes by 50%
- Increase confidence threshold to 80
- Limit to 1 active position
- Daily review required

### 7. Trade Management

#### Entry Rules
1. Wait for all timeframe alignment
2. Confirm with volume analysis
3. Set stops before entry
4. Scale in using ladder system

#### Exit Rules
1. Take profit at 2:1 risk/reward minimum
2. Trail stops using ATR method
3. Close on regime change
4. Time-based exits for stagnant trades

#### Position Monitoring
- Real-time P&L tracking
- Stop loss adjustments
- Correlation analysis
- Exposure limits

## Implementation Notes

### Data Requirements
- 1-minute OHLCV data for signals
- 1-hour data for setup detection
- 4-hour data for regime analysis
- Daily data for long-term context

### Performance Metrics
- **Profit Factor**: Target > 1.5
- **Win Rate**: Target > 45%
- **Average Win/Loss Ratio**: Target > 2.0
- **Maximum Drawdown**: Limit < 15%
- **Sharpe Ratio**: Target > 1.0

### Risk Controls
- Maximum 3 concurrent positions
- Maximum 5% account risk per day
- Maximum 20% sector exposure
- Daily loss limit: 2% of account

## Backtesting Considerations

- Include realistic slippage (0.05%)
- Account for exchange fees (0.1%)
- Model partial fills for large orders
- Consider market impact for position sizes
- Use tick-by-tick data for accuracy

## Future Enhancements

1. Machine learning signal filtering
2. Multi-asset correlation analysis
3. Options hedging strategies
4. Dynamic position sizing
5. Sentiment analysis integration

---

*This strategy is designed for educational and research purposes. Past performance does not guarantee future results. Always test thoroughly before live trading.*
