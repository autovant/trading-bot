# Windows Local Deployment Guide

The `scripts\deploy-local.ps1` script launches the entire trading stack natively on Windows (no Docker/WSL). It manages the Python environment, spins up NATS, and starts every service (engine, ops API, feed/replay, execution, risk, reporter, and Streamlit dashboard) as independent processes with PID/log tracking.

## Requirements
- Windows 10 Home/Pro 22H2+
- Python 3.11 (preferred). The script falls back to the highest available Python 3.x.
- PowerShell 5.1+ (ships with Windows 10)
- Outbound HTTPS access on first run (Python packages + optional NATS download)

## First-Time Startup
```powershell
cd path\to\trading-bot
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action start -Mode paper
```
The script will:
1. Create `.venv`, `logs`, `run`, and `tools\nats`.
2. Resolve the best Python interpreter (or use `-Python C:\Path\python.exe`).
3. Create/refresh the virtual environment, upgrade `pip`, and install `requirements.txt` (or baseline FastAPI/Streamlit/nats packages).
4. Generate `.env` from safe defaults if missing and ensure `.env.example` matches those defaults. Existing files are left untouched.
5. Ensure `tools\nats\nats-server.exe` exists. If not, it downloads the current Windows AMD64 build, extracts it, and caches the binary (see `tools\nats\README.txt`).
6. Load `.env`, fall back to SQLite when `DB_URL` is empty, and set `APP_MODE`, `OPS_API_URL`, and `REPLAY_URL` automatically.
7. Start NATS plus every service command listed in `Get-ServiceDefinitions`, writing `logs\<service>.log` and `run\<service>.pid` for observability.
8. Poll each /health endpoint (and NATS `/healthz`) for up to 60 seconds before printing `READY`.

## Daily Operations
- **Start / switch modes**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action start -Mode live`  
  The replay service only runs when `-Mode replay`; the synthetic feed covers paper/live. The last successful mode is recorded in `run\active-mode.txt` so subsequent commands reuse it automatically unless you pass `-Mode`.

- **Stop everything**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action stop`  
  Gracefully terminates services/NATS, removes PID files, and clears the recorded mode.

- **Restart**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action restart -Mode paper`

- **Status table**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action status`  
  Shows each service name, PID, port, log file, and whether it is `RUNNING`, `STOPPED`, or `SKIPPED (<mode>)`.

- **Health-only probe**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action health`  
  Returns a non-zero exit code if any expected service or NATS is down.

- **Clean workspace**  
  `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-local.ps1 -Action clean`  
  Stops everything, clears `logs\*.log` and `run\*.pid`, deletes `run\active-mode.txt`, and optionally removes `.venv`.

Ctrl+C is trapped so child processes and NATS are shut down before the PowerShell host exits.

### Self-healing behavior
- **NATS auto-retries**: If the Windows firewall dialog delays the first bind, the script restarts `nats-server` up to three times and reminds you to approve the prompt. Health is verified via `http://127.0.0.1:8222/healthz` before services come up.
- **Service warmup checks**: Each FastAPI/Streamlit process must answer its `/health` endpoint within ~45 seconds. If it fails (crash, missing dependency, port already bound), the script tears down the process and retries once before giving up with a precise pointer to `logs\<service>.log`.
- **Idempotent restarts**: Already-running, healthy processes are left untouched; unhealthy-but-running ones are restarted in place so you don’t end up with ghosts after a partial crash.

## Service Map & Customization
`Get-ServiceDefinitions` near the top of the script is the single place to adjust commands, ports, or health endpoints. Each entry specifies:
- `Arguments` (e.g., `python -m uvicorn src.services.execution:app ...`)
- `Port` for status display
- `Modes` array, so you can limit services to subsets of `paper|replay|live`

If you add/remove services (for example a new analytics UI), add another hashtable entry and optionally extend `.env` with a new `*_PORT`.

## Environment & Database
- `.env` fields (see `.env.example`) include `API_PORT`, `UI_PORT`, `FEED_PORT`, `EXEC_PORT`, `RISK_PORT`, `REPORTER_PORT`, `REPLAY_PORT`, and `LOG_LEVEL`.
- `DB_URL` defaults to `sqlite+aiosqlite:///./dev.db`. Set it to a PostgreSQL URL when you have Postgres available; the script simply exports whatever you set.
- `OPS_API_URL` and `REPLAY_URL` are auto-derived from the ports unless you override them.

## Troubleshooting
- **Python not found**: Install Python 3.11 and re-run, or pass `-Python`.
- **NATS download blocked**: Manually copy `nats-server.exe` into `tools\nats\` and retry.
- **Service crash**: Check `logs\<service>.log`. `-Action status` points to the relevant file and shows whether the PID exited.
- **Health check fails**: Make sure the service command/port is correct in `Get-ServiceDefinitions` and that the `/health` route exists.
- **Replay data**: Paper/live modes run the synthetic feed; replay mode launches `src.services.replay` (ensure `sample_data` has the parquet/CSV referenced in your config).

The script is idempotent: re-running `start` keeps existing processes alive, while `stop`/`clean` only affects locally managed children and never touches your source files.
