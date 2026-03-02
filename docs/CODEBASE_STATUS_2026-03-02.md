# Codebase Status Report (2026-03-02)

Generated on: 2026-03-02 (America/Chicago)

## 1) Local vs GitHub Status

- Branch: `main`
- Tracking: `origin/main`
- Remote fetch: complete
- Pending upstream branch work reviewed and integrated from:
  - `origin/copilot/production-readiness-check`

At generation time, local includes new commits not yet pushed to `origin/main`.

## 2) Current Health Snapshot

## Python tests

Command: `.\.venv\Scripts\python -m pytest -q`

- Collected: `280`
- Passed: `276`
- Skipped: `4`
- Failed: `0`

## Production readiness checks

Commands:
- `python tools/production_readiness_check.py --mode paper --output readiness-report-paper.json`
- `python tools/production_readiness_check.py --mode testnet --output readiness-report-testnet.json`

Results:
- Paper: `53/53` checks passed
- Testnet: `53/53` checks passed

## 3) Changes Applied in This Update

1. Aligned pending GitHub work (production-readiness commits) into local `main`.
2. Fixed container strategy loading method mismatch:
   - `src/container.py` now uses `get_strategies()`.
3. Fixed failing container initialization test and cleanup:
   - `tests/test_container.py`.
4. Fixed risk service config mismatch and made risk snapshot persistence optional-safe:
   - `src/services/risk.py`.
5. Imported and corrected production-readiness tooling:
   - `.github/workflows/production-readiness.yml`
   - `tools/production_readiness_check.py`
   - `tools/update_production_status.py`
   - `tests/test_production_readiness.py`
   - `Makefile`
   - `PRODUCTION_READINESS_QUICK_REF.md`
6. Updated documentation:
   - `README.md` (cleaned duplicate content + added production-readiness section)
   - `PRODUCTION_STATUS.md` (refreshed automated check section)

## 4) Remaining Gaps (Not in Scope of This Sync)

1. Code quality gates still need broader remediation in legacy areas:
   - `ruff`, `mypy`, and `black --check` across the full repository
   - frontend `eslint` cleanup
2. Functional TODOs still present:
   - Backtest route placeholder in `src/api/routes/backtest.py`
   - Mode-switch persistence behavior in `src/api/routes/system.py`
   - Monitor service TODO checks in `src/services/monitor.py`
