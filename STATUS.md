# Work In Progress (2025-10-12)

## Completed Since Last Session
- PaperBroker test harness updated: stub database now mirrors the async persistence surface (`create_order`, status tracking) and latency sampling assertions use the new `LatencyConfig` model. All unit tests pass (`python -m pytest`).
- Replay service hardened: CSV/Parquet loaders normalise timestamps, infer symbol columns, and synthesise realistic microstructure metrics. Added start/end filtering, deterministic ordering, and support for the bundled Parquet dataset (`sample_data/btc_eth_4h.parquet`).
- Documentation refresh: README quickstart, `docs/PAPER_MODE.md`, and `CHANGELOG.md` now cover paper/replay/shadow workflows, ops-api configuration, and bundled datasets.
- Docker images aligned with deployment requirements: distroless `:nonroot` bases, Python bytecode disabled via docs guidance, and Go binaries produced with `-trimpath -ldflags "-s -w"` in the builder stage.
- Added sample Parquet dataset for BTC/ETH 4h replay and wired README instructions to consume it.

## Pending / Next Steps
1. **Container verification**
   - Run `docker compose up --build` end-to-end once Docker is available to confirm distroless images, read-only mounts, and service wiring (current shell lacks Docker).
2. **Go toolchain validation**
   - Execute `go fmt ./...` and `go build ./...` in an environment with Go ≥1.21 to confirm the updated replay service and other binaries compile cleanly (the present shell does not provide `go`).
3. **Optional polish**
   - Extend dashboard with replay control UI (pause/seek) to match new `replay.control` handler.
   - Replace `datetime.utcnow()` usage in tests and runtime components with timezone-aware variants to clear deprecation warnings.

## Known Issues / Notes
- Docker and Go CLIs are unavailable in the current workspace; CI should run the outstanding container/build steps.
- Replay shadow controls are server-side only; user surface pending.

## Quick Reference
- Verified commands: `ruff`, `black --check`, `mypy`, `pytest` (all passing).
- Key files touched: `tests/test_paper_broker.py`, `src/paper_trader.py`, `replay_service.go`, `Dockerfile*`, `README.md`, `docs/PAPER_MODE.md`, `CHANGELOG.md`, `sample_data/btc_eth_4h.parquet`.
