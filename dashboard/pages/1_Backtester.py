import asyncio
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.tools.backtest_engine import BacktestEngine

# Basic setup
st.set_page_config(page_title="Backtester", layout="wide")
st.title("Strategy Backtester")

if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = []

# Sidebar Inputs
with st.sidebar:
    st.header("Configuration")
    symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    interval = st.selectbox(
        "Interval", ["1", "5", "15", "30", "60", "240", "D"], index=2
    )

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", datetime.now() - timedelta(days=7))
    with col2:
        end_date = st.date_input("End Date", datetime.now())

    initial_capital = st.number_input("Initial Capital ($)", value=10000.0, step=1000.0)
    risk_pct = st.slider("Risk per Trade (%)", 0.1, 5.0, 1.0, 0.1) / 100.0
    leverage = st.slider("Leverage", 1, 20, 5)

    st.divider()
    st.subheader("Strategy Logic")
    strategy_type = st.radio("Strategy Type", ["Simple Cross", "Multi-TF ATR"], index=0)
    use_multi_tf = strategy_type == "Multi-TF ATR"

    run_btn = st.button("Run Backtest", type="primary")


async def run_backtest():
    engine = BacktestEngine()
    with st.spinner(f"Backtesting {symbol} from {start_date} to {end_date}..."):
        # Convert date to datetime
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        result = await engine.run(
            symbol=symbol,
            interval=interval,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=initial_capital,
            risk_pct=risk_pct,
            leverage=leverage,
            use_multi_tf=use_multi_tf,
        )

        return result


if run_btn:
    # Run async function in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_backtest())

        if "error" in result:
            st.error(result["error"])
        else:
            st.session_state.backtest_results.append(result)
            st.success("Backtest Complete!")
    finally:
        loop.close()

# Results Display
if st.session_state.backtest_results:
    # Summary Metrics of the LATEST run
    latest = st.session_state.backtest_results[-1]

    st.divider()
    st.subheader(f"Results: {latest['symbol']} ({latest['interval']})")

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "Final Equity",
        f"${latest['final_equity']:,.2f}",
        delta=f"{latest['total_return']*100:.2f}%",
    )
    m2.metric("Total Return", f"{latest['total_return']*100:.2f}%")
    m3.metric("Initial Capital", f"${latest['initial_capital']:,.2f}")

    # Charts
    df_equity = latest["equity_curve"]
    if not df_equity.empty:
        fig = px.line(df_equity, y="equity", title="Equity Curve")
        st.plotly_chart(fig, use_container_width=True)

    # Comparison Section
    if len(st.session_state.backtest_results) > 1:
        st.divider()
        st.subheader("Strategy Comparison")

        # Combine all equity curves
        combined_data = []
        for i, res in enumerate(st.session_state.backtest_results):
            name = f"Run {i+1}: {res['symbol']} {res['interval']} (Risk {res.get('risk_pct', 'N/A')})"
            # We just take the final equity for bar chart comparison?
            # Or plot all lines?

            # Let's plot all lines. Need to align them or just plot against time
            df = res["equity_curve"].copy()
            df["Run"] = f"Run {i+1}"
            combined_data.append(df)

        if combined_data:
            all_df = pd.concat(combined_data)
            # Reset index to get time as column
            all_df = all_df.reset_index()

            comp_fig = px.line(
                all_df,
                x="time",
                y="equity",
                color="Run",
                title="Comparative Equity Curves",
            )
            st.plotly_chart(comp_fig, use_container_width=True)

        # Table comparison
        summary_rows = []
        for i, res in enumerate(st.session_state.backtest_results):
            # Check strategy type from a custom field if I saved it, or infer
            # BacktestEngine returns whatever it wants. I should probably add 'strategy' to the result.
            # For now I can't easily "infer" unless I update BacktestEngine again.
            # Let's just label it broadly.
            summary_rows.append(
                {
                    "Run": i + 1,
                    "Strategy": res.get("strategy", "Unknown"),
                    "Symbol": res["symbol"],
                    "Interval": res["interval"],
                    "Return": f"{res['total_return']*100:.2f}%",
                    "Final Equity": f"${res['final_equity']:.2f}",
                }
            )
        st.table(pd.DataFrame(summary_rows))

    if st.button("Clear History"):
        st.session_state.backtest_results = []
        st.rerun()
