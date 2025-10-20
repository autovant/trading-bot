"""
Trading bot control center presented via Streamlit.

The dashboard talks to the ops FastAPI service only (no direct DB access)
so it works identically for Docker and local-hosted deployments.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st


OPS_API_URL = os.getenv("OPS_API_URL", "http://127.0.0.1:8080").rstrip("/")
REPLAY_URL = os.getenv("REPLAY_URL", "http://127.0.0.1:8085").rstrip("/")
API_TIMEOUT = float(os.getenv("OPS_API_TIMEOUT", "8"))

ACCENT_COLOR = "#6366F1"


class ApiError(RuntimeError):
    """Raised when the ops API request fails."""


def _build_url(base: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def api_request(method: str, path: str, **kwargs: Any) -> Any:
    """Perform an HTTP request to the ops API and return decoded data."""

    url = _build_url(OPS_API_URL, path)
    try:
        response = requests.request(method, url, timeout=API_TIMEOUT, **kwargs)
    except requests.RequestException as exc:  # pragma: no cover - network guard
        raise ApiError(str(exc)) from exc

    if response.status_code >= 400:
        detail: Any
        try:
            payload = response.json()
            detail = payload.get("detail", payload)
        except ValueError:
            detail = response.text
        raise ApiError(f"{response.status_code}: {detail}")

    if not response.content:
        return None

    try:
        return response.json()
    except ValueError:
        return response.text


def _clear_caches() -> None:
    """Invalidate cached fetches."""

    get_mode_data.clear()
    get_positions_data.clear()
    get_trades_data.clear()
    get_daily_pnl.clear()
    get_paper_config.clear()
    get_config_snapshot.clear()
    list_config_versions.clear()
    get_backtests.clear()
    get_risk_snapshots.clear()


@st.cache_data(ttl=10)
def get_mode_data() -> Dict[str, Any]:
    return api_request("GET", "/api/mode")


@st.cache_data(ttl=10)
def get_positions_data(limit: int = 100) -> List[Dict[str, Any]]:
    return api_request("GET", "/api/positions", params={"limit": limit})


@st.cache_data(ttl=10)
def get_trades_data(limit: int = 100) -> List[Dict[str, Any]]:
    return api_request("GET", "/api/trades", params={"limit": limit})


@st.cache_data(ttl=15)
def get_daily_pnl(days: int = 30, mode: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"days": days}
    if mode:
        params["mode"] = mode
    return api_request("GET", "/api/pnl/daily", params=params)


@st.cache_data(ttl=20)
def get_paper_config() -> Dict[str, Any]:
    return api_request("GET", "/api/paper/config")


@st.cache_data(ttl=20)
def get_config_snapshot() -> Dict[str, Any]:
    return api_request("GET", "/api/config")


@st.cache_data(ttl=20)
def list_config_versions(limit: int = 5) -> List[Dict[str, Any]]:
    return api_request("GET", "/api/config/versions", params={"limit": limit})


@st.cache_data(ttl=10)
def get_backtests() -> List[Dict[str, Any]]:
    return api_request("GET", "/api/backtests")


@st.cache_data(ttl=10)
def get_risk_snapshots(limit: int = 10) -> List[Dict[str, Any]]:
    return api_request("GET", "/api/risk/snapshots", params={"limit": limit})


def get_replay_status() -> Optional[Dict[str, Any]]:
    if not REPLAY_URL:
        return None
    try:
        response = requests.get(
            _build_url(REPLAY_URL, "/status"),
            timeout=API_TIMEOUT,
        )
        if response.ok:
            return response.json()
    except requests.RequestException:
        return None
    return None


def control_replay(action: str) -> bool:
    try:
        response = requests.post(
            _build_url(REPLAY_URL, "/control"),
            json={"action": action},
            timeout=API_TIMEOUT,
        )
        return response.ok
    except requests.RequestException:
        return False


def _style_app() -> None:
    st.set_page_config(
        page_title="Executive Trading Console",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
        /* Ambient Lighting Effects */
        .ambient-light {
            position: fixed;
            border-radius: 50%;
            filter: blur(100px);
            opacity: 0.4;
            pointer-events: none;
            z-index: -1;
        }
        
        .ambient-light-1 {
            width: 400px;
            height: 400px;
            background: radial-gradient(circle, var(--accent-cyan) 0%, transparent 70%);
            top: 10%;
            right: 10%;
            animation: float 6s ease-in-out infinite;
        }
        
        .ambient-light-2 {
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, var(--accent-blue) 0%, transparent 70%);
            bottom: 20%;
            left: 5%;
            animation: float 8s ease-in-out infinite reverse;
        }
        
        .ambient-light-3 {
            width: 200px;
            height: 200px;
            background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
            top: 60%;
            right: 20%;
            animation: float 10s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px) scale(1); }
            50% { transform: translateY(-20px) scale(1.1); }
        }
        
        /* Frosted Glass Panels */
        .frosted-panel {
            background: linear-gradient(135deg, 
                rgba(255, 255, 255, 0.05) 0%, 
                rgba(255, 255, 255, 0.02) 100%);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 1.5rem;
            margin: 1rem 0;
            position: relative;
            overflow: hidden;
        }
        
        .frosted-panel::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(45deg, transparent 30%, rgba(255, 255, 255, 0.05) 50%, transparent 70%);
            animation: shimmer 3s ease-in-out infinite;
        }
        
        /* Executive Console Header */
        .console-header {
            background: linear-gradient(135deg, 
                rgba(6, 182, 212, 0.15) 0%, 
                rgba(30, 41, 59, 0.9) 50%,
                rgba(59, 130, 246, 0.1) 100%);
            border-radius: 24px;
            padding: 3rem 2rem;
            margin-bottom: 2rem;
            border: 2px solid rgba(6, 182, 212, 0.3);
            box-shadow: 
                0 20px 60px rgba(0, 0, 0, 0.5),
                inset 0 1px 0 rgba(255, 255, 255, 0.2),
                0 0 40px rgba(6, 182, 212, 0.2);
            position: relative;
            overflow: hidden;
        }
        
        .console-header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(from 0deg, transparent, rgba(6, 182, 212, 0.1), transparent);
            animation: rotate 20s linear infinite;
        }
        
        @keyframes rotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        /* Enhanced Typography */
    with col_a:
        mode_color = {
            "live": "#10b981",
            "paper": "#f59e0b", 
            "replay": "#8b5cf6"
        }.get(mode_data.get("mode", "paper"), "#6b7280")
        
        mode_class = {
            "live": "status-live",
            "paper": "status-paper", 
            "replay": "status-replay"
        }.get(mode_data.get("mode", "paper"), "status-paper")
        
        st.markdown(
            f"""
            <div class='metric-card-executive'>
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <div>
                        <p class='metric-label'>Trading Mode</p>
                        <p class='metric-value'>{mode_data.get('mode', '-').upper()}</p>
                    </div>
                    <div class='status-indicator {mode_class}'>
                        <span style='width: 8px; height: 8px; background: {mode_color}; border-radius: 50%; display: inline-block;'></span>
                        ACTIVE
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
            font-size: 2.5rem;
            font-weight: 700;
            line-height: 1;
            margin: 0;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-cyan) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .metric-label {
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0;
        }
        
        /* Executive Status Indicators */
        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
            position: relative;
            overflow: hidden;
        }
        
        .status-live {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.2) 0%, rgba(30, 41, 59, 0.8) 100%);
            color: #10b981;
            border: 1px solid #10b981;
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.3);
        }
        
        .status-paper {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.2) 0%, rgba(30, 41, 59, 0.8) 100%);
            color: #f59e0b;
            border: 1px solid #f59e0b;
            box-shadow: 0 0 20px rgba(245, 158, 11, 0.3);
        }
        
        .status-replay {
            background: linear-gradient(135deg, rgba(139, 92, 246, 0.2) 0%, rgba(30, 41, 59, 0.8) 100%);
            color: #8b5cf6;
            border: 1px solid #8b5cf6;
            box-shadow: 0 0 20px rgba(139, 92, 246, 0.3);
        }
        
        /* Executive Form Elements */
        .stSelectbox > div > div {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            color: var(--text-primary);
        }
        
        .stSelectbox > div > div:hover {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 20px rgba(6, 182, 212, 0.3);
        }
        
        .stNumberInput > div > div {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            color: var(--text-primary);
        }
        
        .stNumberInput > div > div:focus-within {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 20px rgba(6, 182, 212, 0.3);
        }
        
        /* Executive Data Grid */
        .data-grid {
            background: var(--glass-bg);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .data-grid-header {
            background: linear-gradient(135deg, 
                rgba(6, 182, 212, 0.3) 0%, 
                rgba(30, 41, 59, 0.9) 100%);
            color: var(--text-primary);
            font-weight: 600;
            padding: 1rem;
            border-bottom: 2px solid var(--accent-cyan);
        }
        
        .data-grid-row {
            color: var(--text-secondary);
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border-subtle);
            transition: all 0.3s ease;
        }
        
        .data-grid-row:hover {
            background: rgba(6, 182, 212, 0.1);
            color: var(--text-primary);
        }
        
        /* Console-style Terminal */
        .terminal {
            background: linear-gradient(135deg, #000000 0%, #1a1a1a 100%);
            border-radius: 12px;
            padding: 1.5rem;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            color: #00ff00;
            border: 2px solid #333;
            box-shadow: 
                inset 0 0 20px rgba(0, 255, 0, 0.1),
                0 8px 32px rgba(0, 0, 0, 0.5);
            position: relative;
            overflow: hidden;
        }
        
        .terminal::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: 
                repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 255, 0, 0.03) 2px,
                    rgba(0, 255, 0, 0.03) 4px
                );
            pointer-events: none;
        }
        
        .terminal-text {
            color: #00ff00;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.875rem;
            line-height: 1.5;
            margin: 0;
        }
        
        /* Animated Background Elements */
        .bg-animation {
            position: fixed;
            pointer-events: none;
            z-index: -1;
        }
        
        .bg-circle {
            border-radius: 50%;
            background: radial-gradient(circle, rgba(6, 182, 212, 0.1) 0%, transparent 70%);
            animation: pulse 4s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 0.3; }
            50% { transform: scale(1.1); opacity: 0.5; }
        }
        </style>
        
        <!-- Ambient Lighting Elements -->
        <div class="ambient-light ambient-light-1"></div>
        <div class="ambient-light ambient-light-2"></div>
        <div class="ambient-light ambient-light-3"></div>
        
        <!-- Background Animation Elements -->
        <div class="bg-animation bg-circle" style="width: 300px; height: 300px; top: 20%; left: 80%;"></div>
        <div class="bg-animation bg-circle" style="width: 200px; height: 200px; top: 70%; left: 10%;"></div>
        <div class="bg-animation bg-circle" style="width: 150px; height: 150px; top: 40%; left: 60%;"></div>
        
        <!-- Noise Texture Overlay -->
        <div class="noise-overlay"></div>
        """,
        unsafe_allow_html=True,
    )

        /* Form Elements Executive Style */
        .stButton > button {
            background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-blue) 100%);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 0.75rem 2rem;
            font-weight: 600;
            font-size: 1rem;
            box-shadow: 0 4px 20px rgba(6, 182, 212, 0.4);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(6, 182, 212, 0.6);
        }

        .stButton > button:active {
            transform: translateY(0);
        }

        /* Sidebar Glassmorphism */
        .css-1d391kg {
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-right: 1px solid var(--glass-border);
        }

        /* Streamlit Specific Overrides */
        div.block-container {
            padding-top: 3rem;
            padding-left: 3rem;
            padding-right: 3rem;
        }

        .stTabs {
            background: var(--glass-bg);
            border-radius: 16px;
            padding: 2rem;
            border: 1px solid var(--glass-border);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }

        .stTabs [data-baseweb="tab-list"] {
            background: rgba(30, 41, 59, 0.8);
            border-radius: 12px;
            padding: 0.5rem;
            gap: 0.5rem;
        }

        .stTabs [data-baseweb="tab"] {
            background: transparent;
            color: var(--text-secondary);
            border-radius: 8px;
            padding: 0.75rem 1.5rem;
            font-weight: 600;
            border: 1px solid transparent;
            transition: all 0.3s ease;
        }

        .stTabs [data-baseweb="tab"]:hover {
            background: rgba(6, 182, 212, 0.1);
            color: var(--accent-cyan);
        }

        .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-blue) 100%);
            color: white;
            box-shadow: 0 4px 20px rgba(6, 182, 212, 0.4);
        }

        /* Chart Containers */
        .stChart {
            background: var(--glass-bg);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 1.5rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }

        /* Noise Texture Overlay */
        .noise-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            opacity: 0.03;
            background-image: 
                repeating-linear-gradient(45deg, transparent, transparent 2px, rgba(255,255,255,.1) 2px, rgba(255,255,255,.1) 4px),
                repeating-linear-gradient(-45deg, transparent, transparent 2px, rgba(255,255,255,.05) 2px, rgba(255,255,255,.05) 4px);
            z-index: 1000;
        }
        </style>
        <div class="noise-overlay"></div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar(mode_data: Dict[str, Any]) -> None:
    st.sidebar.header("Run Controls")
    current_mode = mode_data.get("mode", "paper")
    shadow_enabled = mode_data.get("shadow", False)

    mode_choice = st.sidebar.selectbox(
        "Deployment Mode",
        options=["paper", "replay", "live"],
        index=["paper", "replay", "live"].index(current_mode)
        if current_mode in ("paper", "replay", "live")
        else 0,
    )

    shadow_choice = st.sidebar.toggle(
        "Shadow Paper (mirror fills in paper broker)",
        value=bool(shadow_enabled),
    )

    if st.sidebar.button("Apply Mode", use_container_width=True):
        try:
            api_request(
                "POST",
                "/api/mode",
                json={"mode": mode_choice, "shadow": shadow_choice},
            )
            st.sidebar.success("Mode updated.")
            get_mode_data.clear()
        except ApiError as exc:
            st.sidebar.error(f"Unable to switch mode: {exc}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Replay Controls")
    replay_state = get_replay_status()
    if replay_state:
        st.sidebar.caption(
            f"Replay status: **{replay_state.get('state', 'unknown').title()}**"
        )
    else:
        st.sidebar.caption("Replay service unreachable.")

    replay_cols = st.sidebar.columns(2)
    if replay_cols[0].button("Pause", use_container_width=True):
        if control_replay("pause"):
            st.sidebar.success("Replay paused.")
        else:
            st.sidebar.warning("Pause command failed.")
    if replay_cols[1].button("Resume", use_container_width=True):
        if control_replay("resume"):
            st.sidebar.success("Replay resumed.")
        else:
            st.sidebar.warning("Resume command failed.")

    st.sidebar.markdown("---")
    if st.sidebar.button("Refresh Data", use_container_width=True):
        _clear_caches()
        st.experimental_rerun()


def _render_overview_tab(mode_data: Dict[str, Any]) -> None:
    col_a, col_b, col_c = st.columns(3)
    col_a.markdown(
        f"<div class='metric-card'><h4>Mode</h4><h2>{mode_data.get('mode', '-').upper()}</h2></div>",
        unsafe_allow_html=True,
    )
    col_b.markdown(
        f"<div class='metric-card'><h4>Shadow Paper</h4><h2>{'ENABLED' if mode_data.get('shadow') else 'DISABLED'}</h2></div>",
        unsafe_allow_html=True,
    )

    try:
        pnl_payload = get_daily_pnl(days=30)
    except ApiError as exc:
        st.error(f"Could not load PnL history: {exc}")
        pnl_payload = {"days": []}

    latest_net = 0.0
    chart_df = pd.DataFrame()
    if pnl_payload.get("days"):
        pnl_df = pd.DataFrame(pnl_payload["days"])
        pnl_df["date"] = pd.to_datetime(pnl_df["date"])
        pnl_df.sort_values("date", inplace=True)
        latest_net = pnl_df.iloc[-1]["net_pnl"]
        chart_df = pnl_df.set_index("date")[["balance", "net_pnl"]]
        chart_df.rename(columns={"balance": "Equity", "net_pnl": "Net PnL"}, inplace=True)

    col_c.markdown(
        f"<div class='metric-card'><h4>Latest Net PnL</h4><h2>${latest_net:,.2f}</h2></div>",
        unsafe_allow_html=True,
    )

    if not chart_df.empty:
        st.markdown("#### Equity Curve")
        st.line_chart(chart_df, height=260)
    else:
        st.info("No PnL history yet. Run the bot to accumulate performance data.")

    st.markdown("---")
    col_positions, col_risk = st.columns([2, 1])

    try:
        positions = get_positions_data(limit=100)
    except ApiError as exc:
        col_positions.error(f"Unable to load positions: {exc}")
        positions = []

    if positions:
        pos_df = pd.DataFrame(positions)
        display_cols = [
            "symbol",
            "side",
            "size",
            "entry_price",
            "mark_price",
            "unrealized_pnl",
            "percentage",
        ]
        col_positions.markdown("#### Open Positions")
        col_positions.dataframe(
            pos_df[display_cols].rename(
                columns={
                    "entry_price": "Entry",
                    "mark_price": "Mark",
                    "unrealized_pnl": "Unrealised PnL",
                    "percentage": "Portfolio %",
                }
            ),
            use_container_width=True,
        )
    else:
        col_positions.info("No open positions.")

    try:
        risk_snapshots = get_risk_snapshots(limit=5)
    except ApiError as exc:
        col_risk.error(f"Unable to fetch risk snapshots: {exc}")
        risk_snapshots = []

    col_risk.markdown("#### Recent Risk Snapshots")
    if risk_snapshots:
        for snapshot in risk_snapshots:
            crisis = "⚠️" if snapshot["crisis_mode"] else "✅"
            col_risk.markdown(
                f"{crisis} {snapshot['created_at'] or '-'} · Drawdown: {snapshot['drawdown']:.2f} · "
                f"Loss streak: {snapshot['consecutive_losses']} · Vol: {snapshot['volatility']:.2f}"
            )
    else:
        col_risk.caption("No risk snapshots recorded yet.")
    # Executive Console Header
    st.markdown(
        """
        <div class="console-header">
            <div style="position: relative; z-index: 2;">
                <h1 class="executive-text" style="font-size: 3.5rem; margin: 0; background: linear-gradient(135deg, #f8fafc 0%, #06b6d4 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                    Executive Trading Console
                </h1>
                <p style="color: #cbd5e1; font-size: 1.25rem; margin: 1rem 0 0 0; font-weight: 500;">
                    Real-time market intelligence & algorithmic trading operations
                </p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        trades = get_trades_data(limit=150)
    except ApiError as exc:
        st.error(f"Unable to load trades: {exc}")
        trades = []

    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])
        trades_df.rename(
            columns={
                "timestamp": "Timestamp",
                "symbol": "Symbol",
                "side": "Side",
                "quantity": "Qty",
                "price": "Price",
                "realized_pnl": "Realised",
                "maker": "Maker",
            },
            inplace=True,
        )
        st.dataframe(
            trades_df[
                [
                    "Timestamp",
                    "Symbol",
                    "Side",
                    "Qty",
                    "Price",
                    "Realised",
                    "slippage_bps",
                    "latency_ms",
                    "Maker",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No trades yet.")


def _render_config_tab() -> None:
    st.subheader("Strategy Configuration")
    try:
        config_snapshot = get_config_snapshot()
    except ApiError as exc:
        st.error(f"Could not load configuration: {exc}")
        return

    config_data = config_snapshot.get("config", {})
    trading = config_data.get("trading", {})
    risk_mgmt = config_data.get("risk_management", {})
    stops = risk_mgmt.get("stops", {})
    paper_defaults = config_data.get("paper", {})
    stage_version = st.session_state.get("last_staged_version")

    with st.form("strategy_knobs_form"):
        col_a, col_b, col_c = st.columns(3)
        risk_per_trade = col_a.number_input(
            "Risk Per Trade",
            min_value=0.001,
            max_value=0.05,
            value=float(trading.get("risk_per_trade", 0.006)),
            step=0.001,
            format="%.3f",
        )
        soft_atr_multiplier = col_b.number_input(
            "Soft ATR Multiplier",
            min_value=0.1,
            max_value=5.0,
            value=float(stops.get("soft_atr_multiplier", 1.5)),
            step=0.1,
        )
        spread_budget_bps = col_c.number_input(
            "Spread Budget (bps)",
            min_value=1,
            max_value=50,
            value=int(paper_defaults.get("max_slippage_bps", 10)),
        )
        submitted = st.form_submit_button("Stage Changes")

        if submitted:
            payload: Dict[str, Any] = {}
            if abs(risk_per_trade - trading.get("risk_per_trade", risk_per_trade)) > 1e-6:
                payload["risk_per_trade"] = float(risk_per_trade)
            if abs(soft_atr_multiplier - stops.get("soft_atr_multiplier", soft_atr_multiplier)) > 1e-6:
                payload["soft_atr_multiplier"] = float(soft_atr_multiplier)
            if int(spread_budget_bps) != int(paper_defaults.get("max_slippage_bps", spread_budget_bps)):
                payload["spread_budget_bps"] = int(spread_budget_bps)

            if not payload:
                st.info("No changes detected.")
def main() -> None:
    _style_app()

    try:
        mode_data = get_mode_data()
    except ApiError as exc:
        st.error(f"Unable to reach ops API: {exc}")
        mode_data = {"mode": "unknown", "shadow": False}

    _render_sidebar(mode_data)

    # Executive Console Header
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, rgba(6, 182, 212, 0.1) 0%, rgba(30, 41, 59, 0.8) 100%);
            border-radius: 20px;
            padding: 2rem;
            margin-bottom: 2rem;
            border: 1px solid rgba(6, 182, 212, 0.3);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
            position: relative;
            overflow: hidden;
        ">
            <div style="
                position: absolute;
                top: -50%;
                left: -50%;
                width: 200%;
                height: 200%;
                background: radial-gradient(circle, rgba(6, 182, 212, 0.1) 0%, transparent 70%);
                animation: ambientGlow 6s ease-in-out infinite alternate;
                pointer-events: none;
            "></div>
            <h1 style="
                font-size: 3rem;
                font-weight: 700;
                background: linear-gradient(135deg, #f8fafc 0%, #06b6d4 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin: 0;
                letter-spacing: -0.02em;
            ">Executive Trading Console</h1>
            <p style="
                color: #cbd5e1;
                font-size: 1.1rem;
                margin: 0.5rem 0 0 0;
                font-weight: 500;
            ">Real-time market intelligence & algorithmic trading operations</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Executive Navigation Tabs
    overview_tab, config_tab, backtest_tab = st.tabs([
        "📊 Market Overview", 
        "⚙️ Strategy Control", 
        "📈 Backtesting Suite"
    ])
                st.success(f"Applied configuration version {stage_version}.")
                st.session_state.pop("last_staged_version", None)
                get_config_snapshot.clear()
                list_config_versions.clear()
                get_mode_data.clear()
            except ApiError as exc:
                st.error(f"Apply failed: {exc}")

    st.markdown("---")
    st.subheader("Paper Broker Settings")
    try:
        paper_config = get_paper_config()
    except ApiError as exc:
        st.error(f"Unable to load paper configuration: {exc}")
        paper_config = {}

    latency_cfg = paper_config.get("latency_ms", {"mean": 120, "p95": 300})
    partial_cfg = paper_config.get(
        "partial_fill", {"enabled": True, "min_slice_pct": 0.15, "max_slices": 4}
    )

    with st.form("paper_config_form"):
        col_1, col_2, col_3 = st.columns(3)
        fee_bps = col_1.number_input(
            "Taker Fee (bps)",
            value=float(paper_config.get("fee_bps", 7)),
            step=0.5,
        )
        maker_rebate_bps = col_2.number_input(
            "Maker Rebate (bps)",
            value=float(paper_config.get("maker_rebate_bps", -1)),
            step=0.5,
        )
        slippage_bps = col_3.number_input(
            "Base Slippage (bps)",
            value=float(paper_config.get("slippage_bps", 3)),
            step=0.5,
        )

        col_4, col_5, col_6 = st.columns(3)
        max_slippage_bps = col_4.number_input(
            "Max Slippage (bps)",
            value=float(paper_config.get("max_slippage_bps", 10)),
            step=0.5,
        )
        spread_coeff = col_5.number_input(
            "Spread Coefficient",
            value=float(paper_config.get("spread_slippage_coeff", 0.5)),
            step=0.05,
        )
        ofi_coeff = col_6.number_input(
            "OFI Coefficient",
            value=float(paper_config.get("ofi_slippage_coeff", 0.35)),
            step=0.05,
        )

        col_7, col_8, col_9 = st.columns(3)
        latency_mean = col_7.number_input(
            "Latency Mean (ms)",
            value=float(latency_cfg.get("mean", 120)),
        )
        latency_p95 = col_8.number_input(
            "Latency P95 (ms)",
            value=float(latency_cfg.get("p95", 300)),
        )
        partial_enabled = col_9.toggle(
            "Partial Fills Enabled",
            value=bool(partial_cfg.get("enabled", True)),
        )

        col_10, col_11, col_12 = st.columns(3)
        min_slice_pct = col_10.number_input(
            "Min Slice %",
            min_value=0.0,
            max_value=1.0,
            value=float(partial_cfg.get("min_slice_pct", 0.15)),
            step=0.01,
        )
        max_slices = col_11.number_input(
            "Max Slices",
            min_value=1,
            max_value=20,
            value=int(partial_cfg.get("max_slices", 4)),
        )
        funding_enabled = col_12.toggle(
            "Funding Enabled",
            value=bool(paper_config.get("funding_enabled", True)),
        )

        price_source = st.selectbox(
            "Price Source",
            options=["live", "replay", "bars"],
            index=["live", "replay", "bars"].index(paper_config.get("price_source", "live"))
            if paper_config.get("price_source") in ("live", "replay", "bars")
            else 0,
        )

        submit_paper = st.form_submit_button("Update Paper Settings")
        if submit_paper:
            payload = {
                "fee_bps": float(fee_bps),
                "maker_rebate_bps": float(maker_rebate_bps),
                "funding_enabled": bool(funding_enabled),
                "slippage_bps": float(slippage_bps),
                "max_slippage_bps": float(max_slippage_bps),
                "spread_slippage_coeff": float(spread_coeff),
                "ofi_slippage_coeff": float(ofi_coeff),
                "latency_ms": {"mean": float(latency_mean), "p95": float(latency_p95)},
                "partial_fill": {
                    "enabled": bool(partial_enabled),
                    "min_slice_pct": float(min_slice_pct),
                    "max_slices": int(max_slices),
                },
                "price_source": price_source,
            }
            try:
                api_request("POST", "/api/paper/config", json=payload)
                st.success("Paper configuration updated.")
                get_paper_config.clear()
            except ApiError as exc:
                st.error(f"Update failed: {exc}")

    st.markdown("---")
    st.subheader("Recent Versions")
    try:
        versions = list_config_versions(limit=5)
    except ApiError as exc:
        st.error(f"Could not load version history: {exc}")
        versions = []

    if versions:
        history_df = pd.DataFrame(versions)
        history_df.rename(
            columns={"version": "Version", "created_at": "Created"},
            inplace=True,
        )
        st.table(history_df)
    else:
        st.caption("No previous versions recorded.")


def _render_backtest_tab() -> None:
    st.subheader("Run Historical Backtests")
    default_start = date.today() - timedelta(days=60)
    default_end = date.today()

    with st.form("backtest_form"):
        symbol = st.text_input("Symbol", value="BTCUSDT").strip().upper()
        col_a, col_b = st.columns(2)
        start_date = col_a.date_input("Start Date", value=default_start, max_value=date.today())
        end_date = col_b.date_input("End Date", value=default_end, max_value=date.today())
        submitted = st.form_submit_button("Launch Backtest")

        if submitted:
            if start_date > end_date:
                st.warning("Start date must be before end date.")
            elif not symbol:
                st.warning("Symbol is required.")
            else:
                payload = {
                    "symbol": symbol,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
                try:
                    job = api_request("POST", "/api/backtests", json=payload)
                    st.success(f"Queued backtest {job['job_id']} for {symbol}.")
                    st.session_state["last_backtest_job"] = job["job_id"]
                    get_backtests.clear()
                except ApiError as exc:
                    st.error(f"Unable to start backtest: {exc}")

    st.markdown("---")
    if st.button("Refresh Backtests"):
        get_backtests.clear()
        st.experimental_rerun()

    try:
        jobs = get_backtests()
    except ApiError as exc:
        st.error(f"Unable to load backtest history: {exc}")
        return

    if not jobs:
        st.caption("No backtests have been launched yet.")
        return

    for job in jobs:
        header = (
            f"{job['symbol']} · {job['start']} → {job['end']} · "
            f"Status: {job['status'].upper()}"
        )
        expanded = (
            "last_backtest_job" in st.session_state
            and job["job_id"] == st.session_state["last_backtest_job"]
        )
        with st.expander(header, expanded=expanded):
            st.write(f"Job ID: `{job['job_id']}`")
            st.write(f"Submitted: {job['submitted_at']}")
            if job.get("started_at"):
                st.write(f"Started: {job['started_at']}")
            if job.get("completed_at"):
                st.write(f"Completed: {job['completed_at']}")
            if job.get("error"):
                st.error(job["error"])
            result = job.get("result")
            if result:
                metrics_row = st.columns(4)
                metrics_row[0].metric("Total Trades", int(result.get("total_trades", 0)))
                metrics_row[1].metric("Win Rate", f"{result.get('win_rate', 0):.1f}%")
                metrics_row[2].metric("Total PnL", f"${result.get('total_pnl', 0):,.2f}")
                metrics_row[3].metric(
                    "Max Drawdown", f"{result.get('max_drawdown', 0):.1f}%"
                )

                st.write(
                    f"Return: {result.get('return_percentage', 0):.1f}% · "
                    f"Sharpe: {result.get('sharpe_ratio', 0):.2f} · "
                    f"Profit Factor: {result.get('profit_factor', 0):.2f}"
                )

                equity = result.get("equity_curve", [])
                if equity:
                    equity_df = pd.DataFrame(equity)
                    equity_df["timestamp"] = pd.to_datetime(equity_df["timestamp"])
                    equity_df.set_index("timestamp", inplace=True)
                    st.line_chart(equity_df[["equity"]], height=220)

                trades_result = result.get("trades", [])
                if trades_result:
                    trades_df = pd.DataFrame(trades_result)
                    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
                    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
                    st.dataframe(
                        trades_df[
                            [
                                "entry_time",
                                "exit_time",
                                "direction",
                                "size",
                                "entry_price",
                                "exit_price",
                                "net_pnl",
                                "reason",
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )


def main() -> None:
    _style_app()

    try:
        mode_data = get_mode_data()
    except ApiError as exc:
        st.error(f"Unable to reach ops API: {exc}")
        mode_data = {"mode": "unknown", "shadow": False}

    _render_sidebar(mode_data)

    st.title("Trading Control Center")
    st.caption("Single-user operations console for monitoring, tuning, and backtesting.")

    overview_tab, config_tab, backtest_tab = st.tabs(
        ["Overview", "Configuration", "Backtesting"]
    )

    with overview_tab:
        _render_overview_tab(mode_data)
    with config_tab:
        _render_config_tab()
    with backtest_tab:
        _render_backtest_tab()


if __name__ == "__main__":
    main()
