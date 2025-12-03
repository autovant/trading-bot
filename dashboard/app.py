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


@st.cache_data(ttl=20)
def get_raw_config_yaml() -> str:
    payload = api_request("GET", "/api/config/raw")
    return payload.get("yaml", "")


@st.cache_data(ttl=20)
def get_exchange_settings() -> Dict[str, Any]:
    return api_request("GET", "/api/exchange/config")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert API payload values into floats without raising."""

    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_usd(value: float) -> str:
    return f"${value:,.2f}"


def _alpha_card(title: str, value: str, annotation: str = "", variant: str = "") -> str:
    extra_cls = f" alpha-card--{variant}" if variant else ""
    annotation_block = (
        f"<span class='alpha-card__meta'>{annotation}</span>" if annotation else ""
    )
    return (
        f"<div class='alpha-card{extra_cls}'>"
        f"<span class='alpha-card__label'>{title}</span>"
        f"<span class='alpha-card__value'>{value}</span>"
        f"{annotation_block}</div>"
    )


def _compute_trade_diagnostics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "total": len(trades),
        "win_rate": 0.0,
        "expectancy": 0.0,
        "profit_factor": 0.0,
        "avg_slippage": 0.0,
        "latency_p95": 0.0,
        "maker_ratio": 0.0,
        "volume": 0.0,
        "net_realized": 0.0,
        "active_streak": 0,
        "active_streak_type": None,
    }

    if not trades:
        return stats

    df = pd.DataFrame(trades).copy()
    numeric_cols = ("realized_pnl", "slippage_bps", "latency_ms", "quantity", "price")
    for col in numeric_cols:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = 0.0

    realized = df["realized_pnl"].fillna(0.0)
    stats["net_realized"] = float(realized.sum())
    if len(realized):
        wins = int((realized > 0).sum())
        stats["win_rate"] = (wins / len(realized)) * 100
        stats["expectancy"] = float(realized.mean())
        positive = realized[realized > 0].sum()
        negative = realized[realized < 0].sum()
        if negative != 0:
            stats["profit_factor"] = float(positive / abs(negative))
        elif positive > 0:
            stats["profit_factor"] = float("inf")

    if "slippage_bps" in df:
        slippage_series = df["slippage_bps"].dropna()
        if not slippage_series.empty:
            stats["avg_slippage"] = float(slippage_series.mean())
    if "latency_ms" in df:
        latency_series = df["latency_ms"].dropna()
        if not latency_series.empty:
            stats["latency_p95"] = float(latency_series.quantile(0.95))
    if "maker" in df:
        maker_series = df["maker"].astype(float)
        stats["maker_ratio"] = float(maker_series.mean() * 100)
    if {"price", "quantity"}.issubset(df.columns):
        stats["volume"] = float(
            (df["price"].abs() * df["quantity"].abs()).fillna(0.0).sum()
        )

    streak = 0
    streak_type: Optional[str] = None
    for value in reversed(realized.tolist()):
        if value > 0:
            streak_type = "win"
            streak += 1
        elif value < 0:
            streak_type = "loss"
            streak += 1
        else:
            break
    stats["active_streak"] = streak
    stats["active_streak_type"] = streak_type
    return stats


def _summarize_positions(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "gross_exposure": 0.0,
        "net_exposure": 0.0,
        "long_count": 0,
        "short_count": 0,
        "largest": None,
        "dataframe": None,
    }
    if not positions:
        return summary

    processed: List[Dict[str, Any]] = []
    for pos in positions:
        size = _safe_float(pos.get("size"))
        entry = _safe_float(pos.get("entry_price"))
        mark = _safe_float(pos.get("mark_price"), entry)
        notional = abs(size * mark)
        direction = (pos.get("side") or ("LONG" if size >= 0 else "SHORT")).upper()
        summary["gross_exposure"] += notional
        summary["net_exposure"] += size * mark
        if direction.startswith("LONG"):
            summary["long_count"] += 1
        elif direction.startswith("SHORT"):
            summary["short_count"] += 1

        change_pct = 0.0
        if entry:
            change_pct = ((mark - entry) / entry) * 100
        processed.append(
            {
                "Symbol": pos.get("symbol", "-"),
                "Bias": direction,
                "Size": size,
                "Entry": entry,
                "Mark": mark,
                "Notional": notional,
                "Unrealised": _safe_float(pos.get("unrealized_pnl")),
                "Book %": _safe_float(pos.get("percentage")),
                "Delta %": change_pct,
            }
        )
        if not summary["largest"] or notional > summary["largest"]["notional"]:
            summary["largest"] = {
                "symbol": pos.get("symbol", "-"),
                "notional": notional,
                "side": direction,
            }

    if processed:
        summary["dataframe"] = pd.DataFrame(processed)
    return summary


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
        page_title="Perps Command Center",
        page_icon=">",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    style_block = """
    <style>
    :root {
        --bg-page: #080f1d;
        --bg-panel: #0f1829;
        --bg-panel-alt: #152236;
        --bg-faint: #0b1424;
        --border-subtle: rgba(148, 163, 184, 0.35);
        --border-strong: rgba(148, 163, 184, 0.6);
        --text-primary: #f5f7fb;
        --text-muted: #9db0c9;
        --accent-blue: #2962ff;
        --accent-cyan: #1bdce2;
        --accent-green: #32d48f;
        --accent-amber: #f5c249;
    }
    body,
    .stApp {
        background: var(--bg-page);
        color: var(--text-primary);
        font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    a {
        color: var(--accent-cyan);
    }
    section[data-testid="stSidebar"] > div {
        background: var(--bg-panel-alt);
        border-right: 1px solid var(--border-subtle);
        color: var(--text-primary);
        padding-top: 1rem;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] div {
        color: var(--text-primary) !important;
    }
    section[data-testid="stSidebar"] .stCaption,
    section[data-testid="stSidebar"] .stMarkdown p {
        color: var(--text-muted) !important;
    }
    section[data-testid="stSidebar"] hr {
        border-color: var(--border-subtle) !important;
    }
    section[data-testid="stSidebar"] .stButton > button,
    section[data-testid="stSidebar"] .stFormSubmitButton > button {
        background: linear-gradient(120deg, var(--accent-blue), var(--accent-cyan));
        border: none;
        border-radius: 10px;
        color: #fff;
        font-weight: 600;
    }
    section[data-testid="stSidebar"] .stSelectbox > div > div,
    section[data-testid="stSidebar"] .stNumberInput > div > div,
    section[data-testid="stSidebar"] .stTextInput > div > div {
        background: var(--bg-panel);
        border-radius: 10px;
        border: 1px solid var(--border-subtle);
    }
    .hero-panel {
        display: flex;
        flex-wrap: wrap;
        gap: 1.5rem;
        padding: 2rem 2.4rem;
        background: linear-gradient(120deg, rgba(17, 27, 45, 0.92), rgba(18, 42, 72, 0.92));
        border-radius: 22px;
        border: 1px solid var(--border-strong);
        margin-bottom: 2rem;
    }
    .hero-panel__copy {
        flex: 2 1 320px;
        min-width: 260px;
    }
    .hero-panel__title {
        margin: 0.35rem 0 0.4rem;
        font-size: 2.35rem;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--text-primary);
    }
    .hero-panel__eyebrow {
        text-transform: uppercase;
        font-size: 0.8rem;
        letter-spacing: 0.12em;
        color: var(--text-muted);
        margin: 0;
    }
    .hero-panel__body {
        margin: 0.35rem 0 1.1rem;
        color: var(--text-muted);
        font-size: 1rem;
        line-height: 1.55;
    }
    .hero-panel__meta {
        display: flex;
        gap: 0.65rem;
        flex-wrap: wrap;
    }
    .hero-badge {
        border-radius: 999px;
        padding: 0.25rem 0.85rem;
        border: 1px solid var(--border-strong);
        font-size: 0.8rem;
        font-weight: 600;
        background: rgba(41, 98, 255, 0.15);
    }
    .hero-panel__stats {
        flex: 1 1 220px;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 0.8rem;
    }
    .hero-stat {
        background: var(--bg-panel);
        border-radius: 16px;
        border: 1px solid var(--border-subtle);
        padding: 1rem 1.2rem;
        min-height: 110px;
    }
    .hero-stat span {
        font-size: 0.8rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .hero-stat strong {
        display: block;
        font-size: 1.35rem;
        margin-top: 0.2rem;
    }
    .hero-stat em {
        display: block;
        margin-top: 0.15rem;
        font-style: normal;
        font-size: 0.8rem;
        color: var(--text-muted);
    }
    .alpha-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    .alpha-card {
        padding: 1.35rem 1.5rem;
        background: var(--bg-panel);
        border-radius: 18px;
        border: 1px solid var(--border-subtle);
        box-shadow: 0 18px 35px rgba(3, 12, 24, 0.35);
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
    }
    .alpha-card--compact {
        padding: 1rem 1.2rem;
    }
    .alpha-card__label {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--text-muted);
    }
    .alpha-card__value {
        font-size: 2rem;
        font-weight: 600;
        color: var(--text-primary);
    }
    .alpha-card__meta {
        font-size: 0.85rem;
        color: var(--text-muted);
    }
    .guardrail-card {
        background: var(--bg-panel-alt);
        border-radius: 18px;
        border: 1px solid var(--border-subtle);
        padding: 1rem 1.2rem;
        height: 100%;
    }
    .risk-pill {
        border-radius: 999px;
        padding: 0.25rem 0.9rem;
        border: 1px solid var(--border-subtle);
        background: rgba(255, 255, 255, 0.04);
        color: var(--text-primary);
        font-size: 0.8rem;
    }
    .stButton > button,
    .stFormSubmitButton > button {
        background: linear-gradient(120deg, var(--accent-blue), var(--accent-cyan));
        color: #fff;
        border: none;
        border-radius: 12px;
        padding: 0.5rem 1.4rem;
        font-weight: 600;
    }
    div[data-baseweb="tab-list"] {
        gap: 0.4rem;
        background: var(--bg-panel-alt);
        padding: 0.35rem;
        border-radius: 14px;
        border: 1px solid var(--border-subtle);
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--text-muted);
        font-weight: 600;
        border-radius: 10px;
        padding: 0.35rem 1rem;
        border: 1px solid transparent;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: var(--bg-panel);
        border-bottom: none;
        border: 1px solid var(--border-subtle);
        color: var(--text-primary);
    }
    .stTabs [data-baseweb="tab"]:not([aria-selected="true"]) {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.02);
    }
    .stSelectbox > div > div,
    .stNumberInput > div > div,
    .stTextInput > div > div,
    .stDateInput > div > div {
        background: var(--bg-panel);
        border-radius: 12px;
        border: 1px solid var(--border-subtle);
        color: var(--text-primary);
    }
    div[data-testid="stDataFrame"] {
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: 16px;
        padding: 0.5rem;
    }
    div[data-testid="stDataFrame"] table {
        color: var(--text-primary);
    }
    .stMetric {
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: 14px;
        padding: 0.8rem;
    }
    .noise-overlay {
        display: none;
    }
    @media (max-width: 900px) {
        .hero-panel {
            padding: 1.5rem;
        }
        .hero-panel__stats {
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        }
    }
    </style>
    """

    st.markdown(style_block, unsafe_allow_html=True)
def _render_sidebar(
    mode_data: Dict[str, Any], replay_state: Optional[Dict[str, Any]] = None
) -> None:
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
    if replay_state is None:
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
    try:
        pnl_payload = get_daily_pnl(days=45)
    except ApiError as exc:
        st.error(f"Could not load PnL history: {exc}")
        pnl_payload = {"days": []}

    chart_df = pd.DataFrame()
    rolling_net = 0.0
    latest_net = 0.0
    equity_now = 0.0
    equity_change = 0.0

    if pnl_payload.get("days"):
        pnl_df = pd.DataFrame(pnl_payload["days"])
        pnl_df["date"] = pd.to_datetime(pnl_df["date"])
        pnl_df.sort_values("date", inplace=True)
        rolling_net = float(pnl_df["net_pnl"].sum())
        latest_net = float(pnl_df.iloc[-1]["net_pnl"])
        chart_df = pnl_df.set_index("date")[["balance", "net_pnl"]]
        chart_df.rename(
            columns={"balance": "Equity", "net_pnl": "Net PnL"},
            inplace=True,
        )
        if not chart_df.empty:
            equity_now = float(chart_df["Equity"].iloc[-1])
            lookback_idx = max(len(chart_df) - 7, 0)
            equity_change = float(
                chart_df["Equity"].iloc[-1] - chart_df["Equity"].iloc[lookback_idx]
            )

    positions_error: Optional[ApiError] = None
    try:
        positions = get_positions_data(limit=100)
    except ApiError as exc:
        positions_error = exc
        positions = []

    trades_error: Optional[ApiError] = None
    try:
        trades = get_trades_data(limit=150)
    except ApiError as exc:
        trades_error = exc
        trades = []

    risk_error: Optional[ApiError] = None
    try:
        risk_snapshots = get_risk_snapshots(limit=8)
    except ApiError as exc:
        risk_error = exc
        risk_snapshots = []

    trade_stats = _compute_trade_diagnostics(trades)
    position_summary = _summarize_positions(positions)

    pf = trade_stats["profit_factor"]
    pf_display = "INF" if pf == float("inf") else f"{pf:.2f}"
    win_rate_display = f"{trade_stats['win_rate']:.1f}%"
    expectancy_display = _format_usd(trade_stats["expectancy"])
    top_cards_html = "".join(
        [
            _alpha_card(
                "30D Net",
                _format_usd(rolling_net),
                f"Last day {_format_usd(latest_net)}",
            ),
            _alpha_card(
                "Win Rate",
                win_rate_display,
                f"{trade_stats['total']} trades",
            ),
            _alpha_card(
                "Expectancy",
                expectancy_display,
                "Per closed trade",
            ),
            _alpha_card(
                "Profit Factor",
                pf_display,
                "Quality of edge",
            ),
        ]
    )
    st.markdown(
        f'''<div class="alpha-grid">{top_cards_html}</div>''',
        unsafe_allow_html=True,
    )

    slippage_display = (
        "--" if trade_stats["total"] == 0 else f"{trade_stats['avg_slippage']:.2f} bps"
    )
    latency_display = (
        "--" if trade_stats["total"] == 0 else f"{trade_stats['latency_p95']:.0f} ms"
    )
    gross_display = _format_usd(position_summary["gross_exposure"])
    net_display = _format_usd(position_summary["net_exposure"])
    exposure_annotation = (
        f"{position_summary['long_count']} long / {position_summary['short_count']} short"
    )
    secondary_cards_html = "".join(
        [
            _alpha_card("Gross Exposure", gross_display, exposure_annotation),
            _alpha_card("Net Exposure", net_display, "Directional bias"),
            _alpha_card("Fill Quality", slippage_display, "Avg slippage"),
            _alpha_card("Exec Latency p95", latency_display, "Last 150 fills"),
        ]
    )
    st.markdown(
        f'''<div class="alpha-grid">{secondary_cards_html}</div>''',
        unsafe_allow_html=True,
    )

    st.markdown("#### Equity & Flow")
    if not chart_df.empty:
        st.caption(f"7d change: {_format_usd(equity_change)}")
        st.line_chart(chart_df, height=260)
    else:
        st.info("No PnL history yet. Run the bot to accumulate performance data.")

    st.markdown("#### Guardrail Tracker")
    guard_cols = st.columns([1.5, 1, 1])
    with guard_cols[0]:
        target_pct = st.slider(
            "Daily net target (% of equity)",
            min_value=0.1,
            max_value=5.0,
            value=1.0,
            step=0.1,
            key="guardrail_target_pct",
        )
        loss_pct = st.slider(
            "Max pain per day (% of equity)",
            min_value=0.5,
            max_value=10.0,
            value=3.0,
            step=0.5,
            key="guardrail_loss_pct",
        )
    target_dollars = equity_now * (target_pct / 100) if equity_now else 0.0
    progress_ratio = latest_net / target_dollars if target_dollars else 0.0
    progress_pct = progress_ratio * 100
    with guard_cols[1]:
        st.markdown("##### Daily target progress")
        st.metric("Status", f"{progress_pct:.0f}%", delta=_format_usd(latest_net))
        st.progress(max(0.0, min(progress_ratio, 1.0)))
    loss_threshold = equity_now * (loss_pct / 100) if equity_now else 0.0
    consumed = abs(min(latest_net, 0.0))
    loss_ratio = consumed / loss_threshold if loss_threshold else 0.0
    with guard_cols[2]:
        st.markdown("##### Loss buffer used")
        st.metric("Drawdown", f"{loss_ratio * 100:.0f}%", delta=f"{loss_pct:.1f}% max")
        st.progress(max(0.0, min(loss_ratio, 1.0)))

    exposure_col, diag_col = st.columns([1.9, 1])
    exposure_col.markdown("#### Live Perp Exposure")
    if positions_error:
        exposure_col.error(f"Unable to load positions: {positions_error}")
    elif position_summary["dataframe"] is not None:
        display_df = position_summary["dataframe"].copy()
        numeric_cols = ["Size", "Entry", "Mark", "Notional", "Unrealised", "Book %", "Delta %"]
        display_df[numeric_cols] = display_df[numeric_cols].apply(
            pd.to_numeric, errors="coerce"
        )
        display_df[numeric_cols] = display_df[numeric_cols].round(4)
        exposure_col.dataframe(
            display_df[
                [
                    "Symbol",
                    "Bias",
                    "Size",
                    "Entry",
                    "Mark",
                    "Notional",
                    "Unrealised",
                    "Book %",
                    "Delta %",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
        if position_summary["largest"]:
            largest = position_summary["largest"]
            exposure_col.caption(
                f"Max risk: {largest['symbol']} {largest['side']} ~ {_format_usd(largest['notional'])}"
            )
    else:
        exposure_col.caption("No open perpetual positions.")

    diag_col.markdown("#### Ops Telemetry")
    mode_name = mode_data.get("mode", "paper").upper()
    shadow_state = "Shadow ON" if mode_data.get("shadow") else "Shadow OFF"
    diag_col.caption(f"Mode: {mode_name} | {shadow_state}")
    maker_display = (
        "--" if trade_stats["total"] == 0 else f"{trade_stats['maker_ratio']:.0f}%"
    )
    volume_display = _format_usd(trade_stats["volume"])
    streak_type = trade_stats["active_streak_type"]
    streak_value = (
        f"{trade_stats['active_streak']} trades"
        if trade_stats["active_streak"]
        else "Flat"
    )
    streak_annotation = f"{streak_type} streak" if streak_type else "No active streak"
    diag_col.markdown(
        _alpha_card("Maker share", maker_display, "Participation", variant="compact"),
        unsafe_allow_html=True,
    )
    diag_col.markdown(
        _alpha_card(
            "Flow",
            volume_display,
            "Notional last 150 trades",
            variant="compact",
        ),
        unsafe_allow_html=True,
    )
    diag_col.markdown(
        _alpha_card("Streak", streak_value, streak_annotation, variant="compact"),
        unsafe_allow_html=True,
    )

    risk_col, trades_col = st.columns([1, 2])
    risk_col.markdown("#### Risk Timeline")
    if risk_error:
        risk_col.error(f"Unable to fetch risk snapshots: {risk_error}")
    elif risk_snapshots:
        risk_df = pd.DataFrame(risk_snapshots)
        risk_df["created_at"] = pd.to_datetime(
            risk_df["created_at"], errors="coerce"
        )
        risk_df.sort_values("created_at", inplace=True)
        plot_df = risk_df.dropna(subset=["created_at"]).set_index("created_at")
        if not plot_df.empty:
            chart_data = plot_df[["drawdown", "volatility"]].rename(
                columns={"drawdown": "Drawdown %", "volatility": "Volatility"}
            )
            risk_col.area_chart(chart_data, height=200)
        for snapshot in risk_snapshots[:4]:
            label = snapshot.get("created_at", "-")
            drawdown = _safe_float(snapshot.get("drawdown"))
            vol = _safe_float(snapshot.get("volatility"))
            streak = int(snapshot.get("consecutive_losses", 0) or 0)
            status = "Alert" if snapshot.get("crisis_mode") else "Stable"
            risk_col.markdown(
                f'''
                <div class="guardrail-card" style="margin-bottom:0.5rem;">
                    <div class="alpha-card__label">{label}</div>
                    <div class="alpha-card__value">{drawdown:.2f}%</div>
                    <div class="alpha-card__meta">Drawdown | Vol {vol:.2f} | Loss streak {streak} | {status}</div>
                </div>
                ''',
                unsafe_allow_html=True,
            )
    else:
        risk_col.caption("No risk snapshots recorded yet.")

    trades_col.markdown("#### Trade Tape")
    if trades_error:
        trades_col.error(f"Unable to load trades: {trades_error}")
    elif not trades:
        trades_col.caption("No trades yet.")
    else:
        trades_df = pd.DataFrame(trades)
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])
        trades_df.sort_values("timestamp", ascending=False, inplace=True)
        trades_view = trades_df[
            [
                "timestamp",
                "symbol",
                "side",
                "quantity",
                "price",
                "realized_pnl",
                "slippage_bps",
                "latency_ms",
                "maker",
            ]
        ].head(60).copy()
        trades_view.rename(
            columns={
                "timestamp": "Timestamp",
                "symbol": "Symbol",
                "side": "Side",
                "quantity": "Qty",
                "price": "Price",
                "realized_pnl": "Realised",
                "slippage_bps": "Slippage (bps)",
                "latency_ms": "Latency (ms)",
                "maker": "Maker",
            },
            inplace=True,
        )
        trades_col.dataframe(
            trades_view,
            use_container_width=True,
            hide_index=True,
        )
        trades_col.caption(
            f"{trade_stats['total']} trades | Fill quality {slippage_display}"
        )



def _render_config_tab(mode_data: Dict[str, Any]) -> None:
    st.markdown("### Strategy Control Plane")

    mission_tab, paper_tab, connectivity_tab = st.tabs(
        ["Mission Control", "Paper Broker Lab", "Connectivity & Raw"]
    )

    current_mode = mode_data.get("mode", "paper")
    current_shadow = bool(mode_data.get("shadow", False))
    stage_version = st.session_state.get("last_staged_version")

    with mission_tab:
        st.subheader("Deployment & Shadowing")
        with st.form("mode_switch_form"):
            selector_cols = st.columns(2)
            mode_choice = selector_cols[0].selectbox(
                "Deployment Mode",
                options=["paper", "replay", "live"],
                index=["paper", "replay", "live"].index(current_mode)
                if current_mode in ("paper", "replay", "live")
                else 0,
            )
            shadow_choice = selector_cols[1].toggle(
                "Shadow Paper (mirror fills while live)",
                value=current_shadow,
            )
            mode_submit = st.form_submit_button("Apply Mode", use_container_width=True)
            if mode_submit:
                try:
                    api_request(
                        "POST",
                        "/api/mode",
                        json={"mode": mode_choice, "shadow": shadow_choice},
                    )
                    st.success("Mode updated.")
                    get_mode_data.clear()
                    get_config_snapshot.clear()
                    st.experimental_rerun()
                except ApiError as exc:
                    st.error(f"Unable to switch mode: {exc}")

        st.markdown("---")
        st.subheader("Primary Risk Dials")

        try:
            config_snapshot = get_config_snapshot()
        except ApiError as exc:
            st.error(f"Could not load configuration: {exc}")
            config_snapshot = None

        if config_snapshot:
            config_data = config_snapshot.get("config", {})
            trading = config_data.get("trading", {})
            risk_mgmt = config_data.get("risk_management", {})
            stops = risk_mgmt.get("stops", {})
            paper_defaults = config_data.get("paper", {})

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
                    if abs(
                        risk_per_trade - trading.get("risk_per_trade", risk_per_trade)
                    ) > 1e-6:
                        payload["risk_per_trade"] = float(risk_per_trade)
                    if abs(
                        soft_atr_multiplier
                        - stops.get("soft_atr_multiplier", soft_atr_multiplier)
                    ) > 1e-6:
                        payload["soft_atr_multiplier"] = float(soft_atr_multiplier)
                    if int(spread_budget_bps) != int(
                        paper_defaults.get("max_slippage_bps", spread_budget_bps)
                    ):
                        payload["spread_budget_bps"] = int(spread_budget_bps)

                    if not payload:
                        st.info("No changes detected.")
                    else:
                        try:
                            response = api_request(
                                "POST", "/api/config/stage", json=payload
                            )
                            stage_version = response.get("version")
                            st.success(
                                f"Staged configuration version {stage_version}."
                            )
                            st.session_state["last_staged_version"] = stage_version
                            get_config_snapshot.clear()
                            list_config_versions.clear()
                        except ApiError as exc:
                            st.error(f"Staging failed: {exc}")

        if stage_version:
            st.markdown(
                f'''
                <div class="guardrail-card" style="margin-top: 0.8rem;">
                    <strong>Ready to apply staged config?</strong><br/>
                    Version: <code>{stage_version}</code>
                </div>
                ''',
                unsafe_allow_html=True,
            )
            apply_col_a, apply_col_b = st.columns([1, 3])
            if apply_col_a.button("Apply Staged Version", use_container_width=True):
                try:
                    api_request("POST", f"/api/config/apply/{stage_version}")
                    st.success(f"Applied configuration version {stage_version}.")
                    st.session_state.pop("last_staged_version", None)
                    get_config_snapshot.clear()
                    list_config_versions.clear()
                    get_mode_data.clear()
                except ApiError as exc:
                    st.error(f"Apply failed: {exc}")

        st.markdown("#### Config History")
        try:
            versions = list_config_versions(limit=5)
        except ApiError as exc:
            st.caption(f"Unable to load history: {exc}")
        else:
            if versions:
                for version in versions:
                    st.markdown(
                        f'''
                        <div class="guardrail-card" style="margin-bottom: 0.5rem;">
                            <div class="alpha-card__label">v{version.get('version', '-')}</div>
                            <div class="alpha-card__meta">{version.get('created_at', '-')} | {version.get('author', 'ops')} | {version.get('summary') or 'No summary'}</div>
                        </div>
                        ''',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No saved versions yet.")

    with paper_tab:
        st.subheader("Paper Broker Calibration")
        try:
            paper_config = get_paper_config()
        except ApiError as exc:
            st.error(f"Unable to load paper configuration: {exc}")
            paper_config = None

        if paper_config:
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
                    min_value=0.01,
                    max_value=0.5,
                    value=float(partial_cfg.get("min_slice_pct", 0.15)),
                    step=0.01,
                )
                max_slices = col_11.number_input(
                    "Max Slices",
                    min_value=1,
                    max_value=10,
                    value=int(partial_cfg.get("max_slices", 4)),
                    step=1,
                )
                price_options = ["last", "mark", "index"]
                default_source = paper_config.get("price_source", "last")
                if default_source not in price_options:
                    default_source = "last"
                price_source = col_12.selectbox(
                    "Price Source",
                    options=price_options,
                    index=price_options.index(default_source),
                )

                updated = st.form_submit_button("Update Paper Broker")
                if updated:
                    payload = {
                        "fee_bps": float(fee_bps),
                        "maker_rebate_bps": float(maker_rebate_bps),
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

    with connectivity_tab:
        st.subheader("Exchange Settings")
        try:
            exchange_cfg = get_exchange_settings()
        except ApiError as exc:
            st.error(f"Unable to load exchange configuration: {exc}")
            exchange_cfg = {}

        provider = exchange_cfg.get("provider", "bybit")
        base_url_value = exchange_cfg.get("base_url") or ""
        with st.form("exchange_config_form"):
            col_a, col_b = st.columns(2)
            provider_choice = col_a.selectbox(
                "Provider",
                options=["bybit", "zoomex"],
                index=["bybit", "zoomex"].index(provider)
                if provider in ("bybit", "zoomex")
                else 0,
            )
            testnet_flag = col_b.toggle(
                "Use Testnet",
                value=bool(exchange_cfg.get("testnet", True)),
            )
            name_value = st.text_input(
                "Display Name",
                value=exchange_cfg.get("name", provider_choice.title()),
            )
            base_url_input = st.text_input(
                "Custom Base URL (optional)",
                value=base_url_value,
                placeholder="Leave blank to use the provider default endpoint",
            )
            st.caption(
                "API credentials are stored in plaintext inside `config/strategy.yaml`. "
                "Leave a field blank to keep the current value."
            )
            api_key_input = st.text_input(
                "API Key",
                value="",
                placeholder=exchange_cfg.get("api_key_hint", "****"),
                type="password",
            )
            secret_key_input = st.text_input(
                "Secret Key",
                value="",
                placeholder="Leave blank to keep current secret",
                type="password",
            )
            passphrase_input = st.text_input(
                "Passphrase (optional)",
                value="",
                placeholder="Leave blank to keep current passphrase",
                type="password",
            )
            exchange_submit = st.form_submit_button("Save Exchange Settings")
            if exchange_submit:
                payload: Dict[str, Any] = {}
                if provider_choice != provider:
                    payload["provider"] = provider_choice
                if name_value.strip() and name_value != exchange_cfg.get("name"):
                    payload["name"] = name_value.strip()
                if testnet_flag != bool(exchange_cfg.get("testnet", True)):
                    payload["testnet"] = testnet_flag
                normalized_base = base_url_input.strip()
                if normalized_base != base_url_value:
                    payload["base_url"] = normalized_base
                if api_key_input:
                    payload["api_key"] = api_key_input
                if secret_key_input:
                    payload["secret_key"] = secret_key_input
                if passphrase_input:
                    payload["passphrase"] = passphrase_input
                if not payload:
                    st.info("No changes detected.")
                else:
                    try:
                        api_request("POST", "/api/exchange/config", json=payload)
                        st.success("Exchange settings updated.")
                        get_exchange_settings.clear()
                        get_config_snapshot.clear()
                        st.experimental_rerun()
                    except ApiError as exc:
                        st.error(f"Unable to save exchange settings: {exc}")

        st.markdown("---")
        with st.expander("Advanced: Edit strategy.yaml", expanded=False):
            if "config_raw_editor" not in st.session_state:
                st.session_state["config_raw_editor"] = get_raw_config_yaml()
            st.text_area(
                "strategy.yaml",
                height=420,
                key="config_raw_editor",
                help="Directly edit the full strategy configuration file. Changes are persisted to disk.",
            )
            col_save, col_reload = st.columns([1, 1])
            if col_save.button("Save strategy.yaml", use_container_width=True):
                text = st.session_state.get("config_raw_editor", "")
                try:
                    api_request("POST", "/api/config/raw", json={"yaml": text})
                    st.success("strategy.yaml updated.")
                    get_config_snapshot.clear()
                    get_raw_config_yaml.clear()
                except ApiError as exc:
                    st.error(f"Save failed: {exc}")
            if col_reload.button("Reload from disk", use_container_width=True):
                st.session_state["config_raw_editor"] = get_raw_config_yaml()
                st.experimental_rerun()



def _render_backtest_tab() -> None:
    st.subheader("Research Lab: Backtesting")
    st.caption("Replay and stress-test the perps playbook before committing real margin.")

    today = date.today()
    default_start = today - timedelta(days=30)

    with st.form("backtest_form"):
        col_a, col_b = st.columns(2)
        symbol = col_a.text_input("Symbol", value="BTCUSDT")
        start_date = col_a.date_input(
            "Start Date", value=default_start, max_value=today
        )
        end_date = col_b.date_input(
            "End Date", value=today, min_value=start_date, max_value=today
        )

        submitted = st.form_submit_button("Launch Backtest", use_container_width=True)
        if submitted:
            if not symbol:
                st.warning("Symbol is required.")
            elif end_date < start_date:
                st.warning("End date must be on or after the start date.")
            else:
                payload = {
                    "symbol": symbol.upper(),
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
                try:
                    job = api_request("POST", "/api/backtests", json=payload)
                    st.success(f"Queued backtest {job.get('job_id', '?')}.")
                    get_backtests.clear()
                except ApiError as exc:
                    st.error(f"Unable to start backtest: {exc}")

    st.markdown("---")
    st.subheader("Recent Jobs")
    try:
        jobs = get_backtests()
    except ApiError as exc:
        st.error(f"Unable to load backtests: {exc}")
        return

    if not jobs:
        st.caption("No backtests have been launched yet.")
        return

    completed = [job for job in jobs if job.get("result")]
    if completed:
        best_pnl = max(
            completed,
            key=lambda job: job.get("result", {}).get("total_pnl", float("-inf")),
        )
        best_hit = max(
            completed,
            key=lambda job: job.get("result", {}).get("win_rate", float("-inf")),
        )
        lowest_dd = min(
            completed,
            key=lambda job: job.get("result", {}).get("max_drawdown", float("inf")),
        )
        avg_win = sum(j.get("result", {}).get("win_rate", 0.0) for j in completed) / max(
            len(completed), 1
        )
        summary_cards = "".join(
            [
                _alpha_card(
                    "Top PnL",
                    _format_usd(best_pnl.get("result", {}).get("total_pnl", 0.0)),
                    f"{best_pnl.get('symbol', '-')} {best_pnl.get('start', '?')}->{best_pnl.get('end', '?')}",
                ),
                _alpha_card(
                    "Avg Win Rate",
                    f"{avg_win:.1f}%",
                    f"{len(completed)} completed",
                ),
                _alpha_card(
                    "Tightest DD",
                    f"{lowest_dd.get('result', {}).get('max_drawdown', 0.0):.1f}%",
                    lowest_dd.get("symbol", "-"),
                ),
                _alpha_card(
                    "Best Hit",
                    f"{best_hit.get('result', {}).get('win_rate', 0.0):.1f}%",
                    best_hit.get("symbol", "-"),
                ),
            ]
        )
        st.markdown(
            f'''<div class="alpha-grid">{summary_cards}</div>''',
            unsafe_allow_html=True,
        )

    for job in jobs:
        title = (
            f"{job.get('symbol', '-')}: {job.get('start', '?')} -> {job.get('end', '?')}"
        )
        status = job.get("status", "unknown").upper()
        header = f"{title} - {status}"
        with st.expander(header, expanded=status in {"RUNNING", "QUEUED"}):
            st.write(f"Job ID: `{job.get('job_id')}`")
            st.write(f"Submitted: {job.get('submitted_at', '-')}")
            if job.get("started_at"):
                st.write(f"Started: {job.get('started_at')}")
            if job.get("completed_at"):
                st.write(f"Completed: {job.get('completed_at')}")
            if job.get("error"):
                st.error(job["error"])
            result = job.get("result") or {}
            if result:
                cols = st.columns(4)
                cols[0].metric("Total Trades", int(result.get("total_trades", 0)))
                cols[1].metric("Win Rate", f"{result.get('win_rate', 0):.1f}%")
                cols[2].metric("Total PnL", f"{result.get('total_pnl', 0):,.2f}")
                cols[3].metric(
                    "Max Drawdown", f"{result.get('max_drawdown', 0):.1f}%"
                )
                if "equity_curve" in result:
                    try:
                        curve = pd.DataFrame(result["equity_curve"])
                        curve["timestamp"] = pd.to_datetime(curve["timestamp"])
                        curve.set_index("timestamp", inplace=True)
                        st.line_chart(curve[["equity"]], height=220)
                    except Exception:
                        pass
                trades = result.get("trades") or []
                if trades:
                    trades_df = pd.DataFrame(trades)
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

    replay_state = get_replay_status()
    _render_sidebar(mode_data, replay_state=replay_state)

    hero_net_value = "—"
    hero_equity_value = "—"
    hero_equity_delta = "Δ7d —"
    hero_positions_value = "—"
    hero_positions_meta = "Gross —"
    hero_replay_value = "Offline"
    hero_replay_meta = "—"

    try:
        pnl_snapshot = get_daily_pnl(days=7)
    except ApiError:
        pnl_snapshot = {}

    if pnl_snapshot.get("days"):
        pnl_df = pd.DataFrame(pnl_snapshot["days"])
        pnl_df["date"] = pd.to_datetime(pnl_df["date"])
        pnl_df.sort_values("date", inplace=True)
        latest_row = pnl_df.iloc[-1]
        hero_net_value = _format_usd(float(latest_row.get("net_pnl", 0.0)))
        hero_equity_value = _format_usd(float(latest_row.get("balance", 0.0)))
        reference_idx = max(len(pnl_df) - 7, 0)
        equity_delta = float(latest_row.get("balance", 0.0)) - float(
            pnl_df.iloc[reference_idx].get("balance", 0.0)
        )
        hero_equity_delta = f"Δ7d {_format_usd(equity_delta)}"

    try:
        hero_positions = get_positions_data(limit=100)
    except ApiError:
        hero_positions = []

    if hero_positions:
        hero_positions_value = str(len(hero_positions))
        gross_exposure = 0.0
        for pos in hero_positions:
            size = _safe_float(pos.get("size"))
            entry = _safe_float(pos.get("entry_price"))
            mark = _safe_float(pos.get("mark_price"), entry)
            gross_exposure += abs(size * mark)
        hero_positions_meta = f"Gross {_format_usd(gross_exposure)}"

    if replay_state:
        hero_replay_value = str(replay_state.get("state", "offline")).title()
        hero_replay_meta = (
            replay_state.get("speed")
            or replay_state.get("symbol")
            or replay_state.get("mode")
            or "—"
        )

    mode_label = mode_data.get("mode", "paper").upper()
    shadow_label = "Shadow ON" if mode_data.get("shadow") else "Shadow OFF"
    st.markdown(
        f"""
        <section class="hero-panel">
            <div class="hero-panel__copy">
                <p class="hero-panel__eyebrow">Private desk</p>
                <h1 class="hero-panel__title">Perps Command Center</h1>
                <p class="hero-panel__body">
                    Real-time oversight across execution, risk, and research pipelines designed for a single high-discipline operator.
                </p>
                <div class="hero-panel__meta">
                    <span class="hero-badge">Mode · {mode_label}</span>
                    <span class="hero-badge">{shadow_label}</span>
                </div>
            </div>
            <div class="hero-panel__stats">
                <div class="hero-stat">
                    <span>Net (24h)</span>
                    <strong>{hero_net_value}</strong>
                    <em>{hero_equity_delta}</em>
                </div>
                <div class="hero-stat">
                    <span>Equity</span>
                    <strong>{hero_equity_value}</strong>
                </div>
                <div class="hero-stat">
                    <span>Open positions</span>
                    <strong>{hero_positions_value}</strong>
                    <em>{hero_positions_meta}</em>
                </div>
                <div class="hero-stat">
                    <span>Replay</span>
                    <strong>{hero_replay_value}</strong>
                    <em>{hero_replay_meta}</em>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    overview_tab, config_tab, backtest_tab = st.tabs(
        ["Alpha Pulse", "Control Plane", "Research Lab"]
    )

    with overview_tab:
        _render_overview_tab(mode_data)
    with config_tab:
        _render_config_tab(mode_data)
    with backtest_tab:
        _render_backtest_tab()


if __name__ == "__main__":
    main()



