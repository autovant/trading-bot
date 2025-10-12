# Changelog

## [Unreleased]

### Added
- **Configurable run modes (`APP_MODE`)** with fail-closed Pydantic validation; all services honour `live | paper | replay` and expose the `trading_mode{mode}` Prometheus label.
- **High-fidelity PaperBroker** delivering latency/slippage modelling, maker rebates, taker fees, funding accrual, liquidation guardrails, and partial fills with queue simulation. All orders/trades/positions/PnL rows are tagged with `{mode, run_id}`.
- **Replay engine & dataset**: Go replayer streams historical bars/trades at configurable speeds (1×/5×/10×) with pause/seek control. Bundled dataset `sample_data/btc_eth_4h.parquet` enables deterministic BTC/ETH replays.
- **Shadow mode**: Optional parallel paper execution in live trading writes to shadow tables and surfaces divergence metrics (slippage, PF, expectancy) via ops-api, dashboard, and Prometheus.
- **Ops API & dashboard enhancements**: `/api/mode`, `/api/paper/config`, and paper config editing/visualisation in Streamlit (mode badge, fill-quality histograms, Paper vs Live comparison).
- **CI/CD workflow**: GitHub Actions job covering Ruff, Black, Mypy, Pytest, Go build, Docker compose build, and Trivy scanning.

### Changed
- **Docker Compose**: Updated to run all services (Postgres, NATS, strategy, execution, feature-engine, ops-api, dash, reporter, replay, Prometheus, Grafana) with distroless images, non-root users, and read-only filesystems where possible.
- **Documentation**: README quickstart, `docs/PAPER_MODE.md`, and sample data instructions now describe paper, replay, and shadow workflows.
