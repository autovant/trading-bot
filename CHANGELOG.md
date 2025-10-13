# Changelog

## [Unreleased]

### Added
- **Configurable run modes (`APP_MODE`)** with fail-closed Pydantic validation; all services honour `live | paper | replay` and expose the `trading_mode{service,mode}` Prometheus label.
- **High-fidelity PaperBroker** delivering latency/slippage modelling, maker rebates, taker fees, funding accrual, liquidation guardrails, and partial fills with queue simulation. All orders/trades/positions/PnL rows are tagged with `{mode, run_id}`.
- **Margin-aware paper risk** via `paper.max_leverage`, `paper.initial_margin_pct`, and `paper.maintenance_margin_pct`; orders breaching the 4x stop buffer are rejected and surfaced through execution reports and tests.
- **FastAPI microservices**: Python execution, feed, risk, replay, reporter, and ops API applications wired through NATS with Prometheus health/metrics endpoints.
- **Observability upgrades**: reject-rate gauges, spread/ATR% gauges, and circuit-breaker counters labelled by `mode`; feed, execution, and risk services emit the metrics.
- **Fill analytics**: every simulated fill persists `achieved_vs_signal_bps` alongside slippage, and the dashboard/ops API surface the averaged deltas for calibration.
- **Replay engine & dataset**: Python replay service streams historical bars/trades at configurable speeds (1x/5x/10x) with pause/resume control. Bundled dataset `sample_data/btc_eth_4h.parquet` enables deterministic BTC/ETH replays.
- **Shadow mode**: Optional parallel paper execution in live trading writes to shadow tables and surfaces divergence metrics (slippage, PF, expectancy) via ops-api, dashboard, and Prometheus.
- **Ops API & dashboard enhancements**: `/api/mode`, `/api/paper/config`, and paper config editing/visualisation in Streamlit (mode badge, fill-quality histograms, Paper vs Live comparison).
- **CI/CD workflow**: GitHub Actions job covering Ruff, Black, Mypy, Pytest, Docker compose build, and Trivy scanning.

### Changed
- **Docker Compose**: Updated to run all services (Postgres, NATS, strategy, execution, feature-engine, ops-api, dash, reporter, replay, Prometheus, Grafana) on a single Python/uvicorn image with non-root users and read-only mounts where possible.
- **Documentation**: README quickstart, `docs/PAPER_MODE.md`, and sample data instructions now describe paper, replay, shadow workflows, and the FastAPI service endpoints.
