# Work In Progress (2025-10-12)

## Completed Since Last Session
- Replaced all Go microservices with FastAPI equivalents (`src/services/*`) that reuse `PaperBroker`, connect to NATS, and expose Prometheus-friendly health endpoints.
- Removed Go build artefacts (`*.go`, `go.mod`, `Dockerfile.services`) and refactored Docker Compose so every container runs the shared Python image via `uvicorn`.
- Updated the CI pipeline to drop `go build` while keeping lint/type/test stages and Trivy scans against the new Python images.
- Refreshed documentation (README, `docs/PAPER_MODE.md`, `CHANGELOG.md`) to highlight the FastAPI architecture and published service URLs.
- Extended `PaperBroker` with an execution-listener callback so fills are emitted back onto NATS by the execution service.
- Rebuilt the Ops API with config staging/apply endpoints plus positions/trades snapshots backed by SQLite `config_versions` for auditability.
- Hardened the NATS messaging client with exponential backoff, auto-resubscribe, and graceful shutdown so FastAPI services survive transient broker outages.
- Persisted risk snapshots, exposed them via the Ops API, and updated the Streamlit dashboard with replay pause/resume controls plus live risk metrics.

## Pending / Next Steps
1. **Runtime validation**
   - Run `docker compose up --build` to confirm the FastAPI services discover NATS and stream market data/replay flows end-to-end.

## Known Issues / Notes
- Local environment still lacks Docker/NATS, so the new service wiring has not been smoke-tested here; rely on CI or a dev host.
- Replay control currently supports pause/resume only; seek/rewind remains on the backlog.

## Quick Reference
- Validation commands to run post-refactor: `python -m ruff check .`, `python -m black --check .`, `python -m mypy src`, `python -m pytest`, `docker compose build`.
- Key files touched: `src/services/*`, `src/ops_api_service.py`, `src/database.py`, `SERVICES.md`, `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `.github/workflows/ci.yml`, `README.md`, `docs/PAPER_MODE.md`, `CHANGELOG.md`.
