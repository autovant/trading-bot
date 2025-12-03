# Strategy Studio Guide

The **Strategy Studio** is a powerful "No-Code" environment within the trading bot that allows you to design, test, and deploy trading strategies without writing a single line of Python code.

## Getting Started

### Prerequisites
- The backend API server must be running: `python src/server.py`
- The frontend must be running: `npm run dev` (inside `frontend/`)

### Accessing the Studio
Navigate to `http://localhost:3000/strategy-studio` in your web browser.

## Using Presets

The Strategy Studio comes with built-in, proven strategies to get you started:
1.  **Trend Surfer (Golden Cross)**: A classic trend-following strategy using EMA 50/200 crossovers and MACD confirmation. Best for trending markets (e.g., Bull Runs).
2.  **Mean Reversion Sniper**: A contrarian strategy using Bollinger Bands and RSI to catch reversals in ranging markets.
3.  **Volatility Breakout**: Captures explosive moves after consolidation (Bollinger Squeeze) with volume confirmation.
4.  **Divergence Master**: Advanced strategy trading Regular (Reversal) and Hidden (Continuation) divergences on RSI.

Select a preset from the "Load Preset..." dropdown to instantly load its configuration.

## Advanced Features

### Divergence Detection
The Strategy Studio now supports advanced divergence detection for any oscillator (RSI, MACD, etc.).
- **Indicator**: Select "Divergence".
- **Params**:
    - `oscillator`: The name of the oscillator to check (e.g., `rsi_14`).
    - `lookback`: Sensitivity of pivot detection (default `3`).
- **Conditions**:
    - `[oscillator]_div_reg_bull`: Regular Bullish (Reversal)
    - `[oscillator]_div_reg_bear`: Regular Bearish (Reversal)
    - `[oscillator]_div_hid_bull`: Hidden Bullish (Continuation)
    - `[oscillator]_div_hid_bear`: Hidden Bearish (Continuation)
    - Set condition to `== 1` to trigger.

## Building a Strategy

The Strategy Builder is divided into four main sections:

### 1. Regime Detection
Define the broad market context. A trade will only be taken if the market regime aligns with the trade direction.
- **Timeframe**: Typically higher than your trading timeframe (e.g., Daily).
- **Conditions**: Define Bullish and Bearish conditions.
    - Example: `Close > EMA(200)` for Bullish.

### 2. Setup Detection
Identify favorable structural conditions for a trade.
- **Timeframe**: Intermediate timeframe (e.g., 4H).
- **Conditions**: Define what constitutes a valid setup.
    - Example: `ADX(14) > 25` (Strong Trend).

### 3. Signals
Define the precise entry triggers. You can add multiple signal types.
- **Signal Type**: Custom name (e.g., "RSI Pullback").
- **Direction**: Long or Short.
- **Timeframe**: Execution timeframe (e.g., 1H).
- **Entry Conditions**: The exact trigger.
    - Example: `RSI(14) < 30` (Oversold).

### 4. Risk Management
Configure how the trade is managed after entry.
- **Stop Loss**:
    - **ATR**: Dynamic stop based on volatility (e.g., 1.5x ATR).
    - **Percent**: Fixed percentage from entry price.
- **Take Profit**:
    - **Risk:Reward**: Multiple of the risk distance (e.g., 2.0x).
    - **Percent**: Fixed percentage from entry price.

## Backtesting

Once your strategy is defined, you can immediately test it against historical data.

1.  **Configure Backtest**:
    - Select the **Symbol** (e.g., BTCUSDT).
    - Set the **Start Date** and **End Date**.
2.  **Run**: Click the "Run Backtest" button.
3.  **Analyze Results**:
    - **Equity Curve**: Visual representation of portfolio growth.
    - **Metrics**: Win Rate, Profit Factor, Max Drawdown, Total PnL.
    - **Trade List**: Detailed log of every trade taken.

## Saving Strategies

You can save your strategies to the local database (JSON file) for later use.
- Enter a **Strategy Name**.
- Click **Save Strategy**.
- Use the dropdown menu to load previously saved strategies.

## Architecture

The Strategy Studio is built on top of the `DynamicStrategyEngine` (`src/dynamic_strategy.py`), which parses the JSON configuration created by the UI and executes the logic using the same robust backend components as the main trading bot.
