"""
Streamlit dashboard for trading bot monitoring and performance analysis.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import os
from typing import List, Optional
import requests

from src.config import get_config

OPS_API_URL = os.getenv("OPS_API_URL", "http://ops-api:8082")
REPLAY_URL = os.getenv("REPLAY_URL", "http://replay-service:8085")


def fetch_mode():
    try:
        resp = requests.get(f"{OPS_API_URL}/api/mode", timeout=2)
        if resp.ok:
            return resp.json()
    except requests.RequestException:
        return None
    return None


def update_mode(mode: str) -> bool:
    try:
        resp = requests.post(f"{OPS_API_URL}/api/mode", json={"mode": mode}, timeout=2)
        return resp.ok
    except requests.RequestException:
        return False


def fetch_paper_config():
    try:
        resp = requests.get(f"{OPS_API_URL}/api/paper/config", timeout=2)
        if resp.ok:
            return resp.json()
    except requests.RequestException:
        return None
    return None


def update_paper_config(payload: dict) -> bool:
    try:
        resp = requests.post(f"{OPS_API_URL}/api/paper/config", json=payload, timeout=2)
        return resp.ok
    except requests.RequestException:
        return False


def fetch_replay_status() -> Optional[dict]:
    try:
        resp = requests.get(f"{REPLAY_URL}/status", timeout=2)
        if resp.ok:
            return resp.json()
    except requests.RequestException:
        return None
    return None


def control_replay(action: str) -> bool:
    try:
        resp = requests.post(
            f"{REPLAY_URL}/control", json={"action": action}, timeout=2
        )
        return resp.ok
    except requests.RequestException:
        return False


def fetch_risk_snapshots(limit: int = 40) -> List[dict]:
    try:
        resp = requests.get(
            f"{OPS_API_URL}/api/risk/snapshots",
            params={"limit": limit},
            timeout=2,
        )
        if resp.ok:
            return resp.json()
    except requests.RequestException:
        return []
    return []


# Page configuration
st.set_page_config(
    page_title="Crypto Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .positive { color: #00ff00; }
    .negative { color: #ff0000; }
    .neutral { color: #ffa500; }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=30)  # Cache for 30 seconds
def load_data():
    """Load data from database."""
    try:
        config = get_config()

        # This is a simplified sync version for Streamlit
        # In production, you'd want to use async properly
        import sqlite3

        conn = sqlite3.connect(config.database.path)

        # Get recent trades
        trades_df = pd.read_sql_query(
            """
            SELECT * FROM trades 
            ORDER BY timestamp DESC 
            LIMIT 100
        """,
            conn,
        )

        if not trades_df.empty:
            if "maker" in trades_df.columns:
                trades_df["maker"] = trades_df["maker"].astype(bool)
            if "is_shadow" in trades_df.columns:
                trades_df["is_shadow"] = trades_df["is_shadow"].astype(bool)

        # Get positions
        positions_df = pd.read_sql_query(
            """
            SELECT * FROM positions 
            WHERE size > 0
            ORDER BY updated_at DESC
        """,
            conn,
        )

        # Get PnL history
        pnl_df = pd.read_sql_query(
            """
            SELECT * FROM pnl_ledger 
            WHERE timestamp >= datetime('now', '-30 days')
            ORDER BY timestamp ASC
        """,
            conn,
        )

        # Get performance metrics
        performance = pd.read_sql_query(
            """
            SELECT * FROM strategy_performance 
            WHERE id = 1
        """,
            conn,
        )

        conn.close()

        return trades_df, positions_df, pnl_df, performance

    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


def main():
    """Main dashboard function."""

    config = get_config()
    mode_info = fetch_mode() or {}
    current_mode = mode_info.get("mode", config.app_mode)
    shadow_enabled = mode_info.get("shadow", False)

    try:
        paper_defaults = config.paper.model_dump()
    except AttributeError:
        paper_defaults = {
            "fee_bps": config.paper.fee_bps,
            "maker_rebate_bps": config.paper.maker_rebate_bps,
            "slippage_bps": config.paper.slippage_bps,
            "max_slippage_bps": config.paper.max_slippage_bps,
            "funding_enabled": config.paper.funding_enabled,
            "price_source": config.paper.price_source,
            "spread_slippage_coeff": getattr(
                config.paper, "spread_slippage_coeff", 0.5
            ),
            "ofi_slippage_coeff": getattr(config.paper, "ofi_slippage_coeff", 0.35),
            "latency_ms": getattr(
                config.paper, "latency_ms", {"mean": 120, "p95": 300}
            ),
            "partial_fill": getattr(
                config.paper,
                "partial_fill",
                {"enabled": True, "min_slice_pct": 0.15, "max_slices": 4},
            ),
        }
    paper_config = fetch_paper_config() or paper_defaults

    trades_df, positions_df, pnl_df, performance_df = load_data()
    replay_status = fetch_replay_status() or {}
    risk_snapshots = fetch_risk_snapshots()

    st.title("🚀 Crypto Trading Bot Dashboard")
    badge_color = {
        "paper": "#1f8b4c",
        "live": "#d9534f",
        "replay": "#f0ad4e",
    }.get(current_mode, "#6c757d")
    st.markdown(
        f"<span style='display:inline-block;padding:6px 12px;border-radius:4px;background-color:{badge_color};color:white;font-weight:600;'>MODE: {current_mode.upper()}</span>",
        unsafe_allow_html=True,
    )
    if shadow_enabled:
        st.caption("Shadow paper trading enabled")
    st.markdown("---")

    status_col, risk_col = st.columns([1, 1])

    with status_col:
        st.subheader("Replay Service")
        replay_state = replay_status.get("state", "unknown")
        st.metric("State", replay_state.title())
        dataset_size = replay_status.get("dataset_size")
        interval = replay_status.get("interval")
        if dataset_size is not None and interval is not None:
            st.caption(f"{dataset_size} snapshots | interval {interval:.2f}s")
        last_action = replay_status.get("last_control")
        last_action_at = replay_status.get("last_control_at")
        if last_action_at:
            try:
                ts = pd.to_datetime(last_action_at)
                st.caption(
                    f"Last action: {last_action or 'n/a'} @ {ts:%Y-%m-%d %H:%M:%S}"
                )
            except Exception:
                st.caption(f"Last action: {last_action or 'n/a'}")

        replay_controls = st.columns(2)
        with replay_controls[0]:
            if st.button(
                "Pause Replay",
                key="pause_replay",
                disabled=replay_state == "paused",
            ):
                if control_replay("pause"):
                    st.success("Replay paused")
                    st.experimental_rerun()
                else:
                    st.error("Failed to pause replay")
        with replay_controls[1]:
            if st.button(
                "Resume Replay",
                key="resume_replay",
                disabled=replay_state == "running",
            ):
                if control_replay("resume"):
                    st.success("Replay resumed")
                    st.experimental_rerun()
                else:
                    st.error("Failed to resume replay")

    with risk_col:
        st.subheader("Risk Stream")
        if risk_snapshots:
            risk_df = pd.DataFrame(risk_snapshots)
            if "created_at" in risk_df.columns:
                risk_df["created_at"] = pd.to_datetime(risk_df["created_at"])
                risk_df.sort_values("created_at", inplace=True)
            latest = risk_df.iloc[-1]
            st.metric(
                "Crisis Mode",
                "Active" if bool(latest["crisis_mode"]) else "Normal",
            )
            drawdown_pct = float(latest.get("drawdown", 0.0)) * 100
            volatility_pct = float(latest.get("volatility", 0.0)) * 100
            st.metric("Drawdown", f"{drawdown_pct:.1f}%")
            st.metric("Volatility", f"{volatility_pct:.1f}%")
            trend_df = risk_df.tail(60)
            fig_risk = px.line(
                trend_df,
                x="created_at" if "created_at" in trend_df.columns else trend_df.index,
                y="drawdown",
                title="Drawdown (recent snapshots)",
                labels={"created_at": "Timestamp", "drawdown": "Drawdown"},
            )
            fig_risk.update_layout(height=260, showlegend=False)
            st.plotly_chart(fig_risk, use_container_width=True)
        else:
            st.info("Risk stream snapshots not available yet.")

    st.markdown("---")

    has_positions = not positions_df.empty and current_mode != "paper"

    controls_col, refresh_col = st.columns([1, 1])
    with controls_col:
        disabled = current_mode == "paper" or has_positions
        if st.button("Switch to Paper Mode", disabled=disabled):
            if update_mode("paper"):
                st.success("Mode switched to PAPER")
                st.experimental_rerun()
            else:
                st.error("Failed to switch mode")
        if has_positions:
            st.caption("Close positions before switching mode.")

    with refresh_col:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.experimental_rerun()

    st.markdown("---")

    if not performance_df.empty:
        perf = performance_df.iloc[0]
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "💰 Total P&L",
                f"${perf['total_pnl']:.2f}",
                delta=f"{perf['total_pnl']:.2f}",
            )
        with col2:
            st.metric(
                "📈 Win Rate",
                f"{perf['win_rate']:.1f}%",
                delta=f"{perf['win_rate'] - 50:.1f}%",
            )
        with col3:
            st.metric(
                "🎯 Profit Factor",
                f"{perf['profit_factor']:.2f}",
                delta=f"{perf['profit_factor'] - 1:.2f}",
            )
        with col4:
            st.metric(
                "📉 Max Drawdown",
                f"{perf['max_drawdown']:.1f}%",
                delta=f"{perf['max_drawdown']:.1f}%",
                delta_color="inverse",
            )

    st.markdown("---")

    st.subheader("🧪 Paper Trading Insights")
    insight_col1, insight_col2 = st.columns([2, 1])

    with insight_col1:
        if not trades_df.empty and "slippage_bps" in trades_df.columns:
            slippage_fig = px.histogram(
                trades_df,
                x="slippage_bps",
                nbins=20,
                title="Fill Slippage (bps)",
            )
            st.plotly_chart(slippage_fig, use_container_width=True)
        else:
            st.info("No fill data available yet.")

    with insight_col2:
        if not trades_df.empty and "maker" in trades_df.columns:
            maker_ratio = trades_df["maker"].mean()
            st.metric("Maker Ratio", f"{maker_ratio:.1%}")
        if not trades_df.empty and "latency_ms" in trades_df.columns:
            st.metric("Avg Fill Latency", f"{trades_df['latency_ms'].mean():.0f} ms")

    if (
        not trades_df.empty
        and "is_shadow" in trades_df.columns
        and trades_df["is_shadow"].nunique() > 1
    ):
        st.subheader("📊 Live vs Shadow Performance")
        comparison = trades_df.copy()
        comparison["timestamp"] = pd.to_datetime(comparison["timestamp"])
        comparison.sort_values("timestamp", inplace=True)
        comparison["equity"] = comparison.groupby("is_shadow")["realized_pnl"].cumsum()
        fig_shadow = px.line(
            comparison,
            x="timestamp",
            y="equity",
            color=comparison["is_shadow"].map({False: "live", True: "shadow"}),
            labels={"color": "Mode", "equity": "Cumulative PnL"},
        )
        st.plotly_chart(fig_shadow, use_container_width=True)

    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📈 Equity Curve")
        if not pnl_df.empty:
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=pd.to_datetime(pnl_df["timestamp"]),
                    y=pnl_df["balance"],
                    mode="lines",
                    name="Account Balance",
                    line=dict(color="#1f77b4", width=2),
                )
            )
            fig.update_layout(
                title="Account Balance Over Time",
                xaxis_title="Date",
                yaxis_title="Balance ($)",
                hovermode="x unified",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No P&L data available yet.")

    with col2:
        st.subheader("📊 Active Positions")
        if not positions_df.empty:
            for _, pos in positions_df.iterrows():
                pnl_color = "positive" if pos["unrealized_pnl"] > 0 else "negative"
                st.markdown(
                    f"""
                <div class="metric-card">
                    <strong>{pos['symbol']}</strong><br>
                    Side: {pos['side']}<br>
                    Size: {pos['size']:.4f}<br>
                    Entry: ${pos['entry_price']:.2f}<br>
                    Mark: ${pos['mark_price']:.2f}<br>
                    <span class="{pnl_color}">P&L: ${pos['unrealized_pnl']:.2f} ({pos['percentage']:.2f}%)</span>
                </div>
                """,
                    unsafe_allow_html=True,
                )
                st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.info("No active positions.")

    st.markdown("---")

    st.subheader("📋 Recent Trades")
    if not trades_df.empty:
        symbols = ["All"] + sorted(trades_df["symbol"].unique())
        selected_symbol = st.selectbox("Filter by Symbol", symbols)
        trades_view = trades_df.copy()
        if selected_symbol != "All":
            trades_view = trades_view[trades_view["symbol"] == selected_symbol]
        st.dataframe(trades_view.head(50))
    else:
        st.info("No trades recorded yet.")

    st.markdown("---")

    st.subheader("🧮 P&L Breakdown")
    if not pnl_df.empty:
        st.dataframe(pnl_df.tail(30))
    else:
        st.info("No P&L records available.")

    st.markdown("---")

    st.subheader("⚙️ Paper Configuration")
    latency_cfg = paper_config.get("latency_ms", {"mean": 120, "p95": 300})
    partial_cfg = paper_config.get(
        "partial_fill", {"enabled": True, "min_slice_pct": 0.15, "max_slices": 4}
    )

    with st.form("paper_config_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            fee_bps = st.number_input(
                "Fee (bps)", value=float(paper_config.get("fee_bps", 7)), step=0.5
            )
            maker_rebate = st.number_input(
                "Maker Rebate (bps)",
                value=float(paper_config.get("maker_rebate_bps", -1)),
                step=0.5,
            )
            slippage_bps = st.number_input(
                "Base Slippage (bps)",
                value=float(paper_config.get("slippage_bps", 3)),
                step=0.5,
            )
            max_slippage = st.number_input(
                "Max Slippage (bps)",
                value=float(paper_config.get("max_slippage_bps", 10)),
                step=0.5,
            )
            spread_coeff = st.number_input(
                "Spread Coefficient",
                value=float(paper_config.get("spread_slippage_coeff", 0.5)),
                step=0.05,
            )
        with col_b:
            ofi_coeff = st.number_input(
                "OFI Coefficient",
                value=float(paper_config.get("ofi_slippage_coeff", 0.35)),
                step=0.05,
            )
            latency_mean = st.number_input(
                "Latency Mean (ms)", value=float(latency_cfg.get("mean", 120))
            )
            latency_p95 = st.number_input(
                "Latency P95 (ms)", value=float(latency_cfg.get("p95", 300))
            )
            partial_enabled = st.checkbox(
                "Partial Fill Enabled", value=bool(partial_cfg.get("enabled", True))
            )
            min_slice = st.number_input(
                "Min Slice %",
                value=float(partial_cfg.get("min_slice_pct", 0.15)),
                min_value=0.0,
                max_value=1.0,
                step=0.01,
            )
            max_slices = st.number_input(
                "Max Slices", value=int(partial_cfg.get("max_slices", 4)), min_value=1
            )

        submitted = st.form_submit_button("Update Configuration")
        if submitted:
            payload = {
                "fee_bps": fee_bps,
                "maker_rebate_bps": maker_rebate,
                "slippage_bps": slippage_bps,
                "max_slippage_bps": max_slippage,
                "funding_enabled": bool(paper_config.get("funding_enabled", True)),
                "price_source": paper_config.get("price_source", "live"),
                "spread_slippage_coeff": spread_coeff,
                "ofi_slippage_coeff": ofi_coeff,
                "latency_ms": {"mean": latency_mean, "p95": latency_p95},
                "partial_fill": {
                    "enabled": partial_enabled,
                    "min_slice_pct": min_slice,
                    "max_slices": int(max_slices),
                },
            }
            if update_paper_config(payload):
                st.success("Paper configuration updated")
                st.experimental_rerun()
            else:
                st.error("Failed to update paper configuration")

    st.markdown("---")

    st.subheader("📘 Configuration Snapshot")
    st.json(
        {
            "App Mode": current_mode,
            "Shadow": shadow_enabled,
            "Tracked Symbols": config.trading.symbols,
            "Messaging": config.messaging.servers,
            "Database": config.database.path,
        }
    )


if __name__ == "__main__":
    main()
