# Local Windows Deployment Guide

This guide explains how to run the trading platform natively on Windows 10 without Docker or WSL. The `deploy-local.ps1` script orchestrates Python virtual environment management, dependency installation, NATS message bus bootstrap, and multi-service process management.

## Prerequisites
- Windows 10 Home/Pro 22H2 or later.
- Python 3.11 installed (the script falls back to the highest available Python 3.x).
- PowerShell 5.1 or newer (shipped with Windows 10).
- Internet access on first run for Python package installation and optional NATS download.

## First-Time Setup
1. Open **Windows PowerShell** as your user (no admin rights required).
2. Navigate to the repository root:
   ```powershell
   cd path\to\trading-bot
   ```
3. Run the deployment script in paper mode:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action start -Mode paper
   ```
   The script will:
   - Create `.venv`, `logs`, `run`, and `tools\nats` directories if missing.
   - Resolve a Python 3.11+ interpreter (or prompt if none is found).
   - Create/upgrade the virtual environment and install dependencies from `requirements.txt`.
   - Generate `.env` from safe defaults if missing and ensure `.env.example` matches the defaults.
   - Download NATS Server for Windows AMD64 into `tools\nats\` if not already present, then start it.
   - Launch the trading engine, FastAPI microservices, and Streamlit dashboard, writing logs to `logs\*.log` and PID files to `run\*.pid`.
   - Poll the declared health endpoints (including NATS) for up to 60 seconds and report `READY` when all services respond.

## Daily Operations
- **Start services**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action start [-Mode paper|replay|live]
  ```
  Re-running `start` is idempotent; existing PID files are checked before spawning new processes.

- **Stop services**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action stop
  ```
  Gracefully shuts down all child processes and the NATS server, removing PID files.

- **Restart everything**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action restart [-Mode <mode>]
  ```

- **Check process status**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action status
  ```
  Prints a table of services, PID values, and the associated log file path. A warning appears for stopped services or if NATS is down.

- **Run health checks only**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action health
  ```
  Useful for CI/acceptance checks—returns a non-zero exit code if any service health endpoint fails.

- **Cleanup**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action clean
  ```
  Stops all processes, removes log/pid files, and optionally deletes `.venv` after prompting.

The script traps **Ctrl+C**, ensuring all managed processes shut down cleanly on user interruption.

## Modes and Environment Variables
- Modes (`paper`, `replay`, `live`) map to `APP_MODE` and propagate to every process. Edit `.env` to override defaults for ports, database URL, or other settings.
- `.env.example` documents the baseline configuration and can be committed to source control.
- If `DB_URL` is absent, services default to `sqlite+aiosqlite:///./dev.db`, enabling development without PostgreSQL.
- Default port bindings:
  - `OPS_PORT` - Ops API / FastAPI service (default `8080`).
  - `FEED_PORT`, `EXEC_PORT`, `RISK_PORT`, `REPORTER_PORT`, `REPLAY_PORT` - supporting FastAPI microservices (default `8081-8085`).
  - `UI_PORT` - Streamlit dashboard (default `8501`).
- The Streamlit dashboard reads `OPS_API_URL` and `REPLAY_URL` from `.env`. They default to `http://127.0.0.1:8080` and `http://127.0.0.1:8085` so the UI connects to locally hosted services without Docker networking aliases.

## Editing Service Definitions
At the top of `deploy-local.ps1`, the `Get-ServiceDefinitions` function lists all managed services and their commands. Adjust the entries if you:
- Add/remove microservices.
- Need to change ports, command-line options, or health endpoints.
- Replace the Streamlit dashboard with an alternative UI.

Each service entry defines the executable, arguments, log path, PID file, and health check URL. After editing, re-run `-Action start` to apply changes.

## Troubleshooting
- **NATS download fails**: Place a pre-downloaded `nats-server.exe` into `tools\nats\` and rerun `start`. The script prints descriptive errors when downloads fail.
- **Python not detected**: Pass a path via `-Python C:\Python311\python.exe`.
- **Health check fails**: Inspect the corresponding `logs\<service>.log`. The `status` action flags stopped processes and points to log files.
- **Port conflicts**: Update the relevant `*_PORT` variables in `.env`, then restart. The script reloads `.env` on every invocation.
- The Streamlit dashboard now exposes:
  - **Overview**: live equity curve, open positions, recent trades, and risk snapshots (all fetched from the Ops API).
  - **Configuration**: stage/apply strategy risk knobs and tweak paper-broker parameters directly through the API.
  - **Backtesting**: queue historical runs via the Ops API and inspect results (PnL metrics, equity curve, trade list) once they complete.

For additional customization-such as enabling JetStream in NATS or pointing at an external PostgreSQL database-edit `.env` accordingly before running `start`.
