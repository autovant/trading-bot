# VWAP and Order Book Indicators

This document describes the new VWAP and Market Microstructure indicators added to the trading bot.

## 1. VWAP (Volume Weighted Average Price)

VWAP is used as a trend filter and mean reversion baseline.

### Configuration
```yaml
strategy:
  vwap:
    enabled: true
    mode: "session" # or "rolling"
    rolling_window: 20
    require_price_above_vwap_for_longs: true
    require_price_below_vwap_for_shorts: true
```

### Usage
- **Trend Filter**: If enabled, the strategy will only take LONG positions if the price is above VWAP, and SHORT positions if the price is below VWAP.
- **Modes**:
    - `session`: Cumulative VWAP from the start of the data series (or day).
    - `rolling`: VWAP calculated over a moving window (e.g., last 20 bars).

## 2. Order Book Indicators

These indicators analyze the market microstructure using the order book (bids and asks).

### Indicators
1.  **Order Book Imbalance (OBI)**:
    - Measures the pressure between bids and asks.
    - Formula: `(BidVol - AskVol) / (BidVol + AskVol)`
    - Range: `[-1, 1]`. Positive = Bullish (more bids), Negative = Bearish (more asks).

2.  **Spread**:
    - Difference between Best Ask and Best Bid.
    - Large spreads can indicate low liquidity or high volatility.

3.  **Liquidity Walls**:
    - Detects unusually large orders at specific price levels.
    - Configured via `wall_multiplier` (e.g., 3x average size).

### Configuration
```yaml
strategy:
  orderbook:
    enabled: true
    depth: 5
    imbalance_threshold: 0.2
    wall_multiplier: 3.0
    use_for_entry: true
```

### Usage
- **Entry Filter**:
    - **Longs**: Requires OBI > `imbalance_threshold`.
    - **Shorts**: Requires OBI < `-imbalance_threshold`.
- **Logging**: All executed trades log the OBI and Spread at the time of entry.

## 3. Risk Management

Order book metrics can also adjust risk parameters (e.g., widening stops or reducing size).

```yaml
strategy:
  orderbook_risk:
    enabled: true
    widen_sl_on_adverse_imbalance: true
    sl_widen_factor: 1.5
```
*(Note: Full risk integration is pending final wiring in risk module, currently logs metrics).*
