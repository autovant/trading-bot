from __future__ import annotations

import argparse
import json
import subprocess
import sys
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

SCENARIO_LOG_DIR = Path("logs/validation")
REPORT_PATH = Path("docs/SAFETY_VALIDATION_REPORT.md")
SCENARIO_TEST_FILE = "tests/test_safety_scenarios.py"


@dataclass
class Scenario:
    name: str
    description: str
    runner: str  # "pytest" or "bot"
    expected_tags: List[str]
    config_overrides: str
    pytest_target: Optional[str] = None
    timeout: int = 60
    additional_notes: Optional[str] = None


SCENARIOS: List[Scenario] = [
    Scenario(
        name="normal_testnet_session",
        description="Baseline simulation with generous limits; expect no SAFETY_* tags.",
        runner="pytest",
        pytest_target="normal_testnet_session",
        expected_tags=[],
        config_overrides="sessionMaxTrades=5, sessionMaxRuntimeMinutes=5",
        timeout=40,
    ),
    Scenario(
        name="session_trade_cap",
        description="sessionMaxTrades=1 should trigger SAFETY_SESSION_TRADES after first trade.",
        runner="pytest",
        pytest_target="session_trade_cap",
        expected_tags=["SAFETY_SESSION_TRADES"],
        config_overrides="sessionMaxTrades=1",
    ),
    Scenario(
        name="session_runtime_cap",
        description="sessionMaxRuntimeMinutes=1 forces SAFETY_SESSION_RUNTIME once elapsed.",
        runner="pytest",
        pytest_target="session_runtime_cap",
        expected_tags=["SAFETY_SESSION_RUNTIME"],
        config_overrides="sessionMaxRuntimeMinutes=1",
    ),
    Scenario(
        name="margin_block",
        description="Very low maxMarginRatio results in SAFETY_MARGIN_BLOCK when entering.",
        runner="pytest",
        pytest_target="margin_block",
        expected_tags=["SAFETY_MARGIN_BLOCK"],
        config_overrides="maxMarginRatio=0.10",
    ),
    Scenario(
        name="risk_limiters",
        description="Simulated PnL exceeds daily and drawdown caps plus circuit breaker.",
        runner="pytest",
        pytest_target="risk_limiters",
        expected_tags=[
            "SAFETY_CIRCUIT_BREAKER",
            "SAFETY_DAILY_LOSS",
            "SAFETY_DRAWDOWN",
        ],
        config_overrides="max_daily_risk=0.05, drawdown_threshold=0.10",
    ),
    Scenario(
        name="reconciliation_guard",
        description="Startup adopts an existing short position and blocks entries.",
        runner="pytest",
        pytest_target="reconciliation_guard",
        expected_tags=["SAFETY_RECON_ADOPT", "SAFETY_RECON_BLOCK"],
        config_overrides="perps.positionIdx=0",
    ),
    Scenario(
        name="reconciliation_adopt",
        description="Adopt a long position without triggering the block.",
        runner="pytest",
        pytest_target="reconciliation_adopt_long",
        expected_tags=["SAFETY_RECON_ADOPT"],
        config_overrides="perps.positionIdx=0",
    ),
    Scenario(
        name="state_persistence",
        description="Persisted risk state is restored on restart.",
        runner="pytest",
        pytest_target="state_persistence",
        expected_tags=["SAFETY_STATE_LOAD", "SAFETY_CIRCUIT_BREAKER"],
        config_overrides="stateFile override, consecutiveLossLimit=1",
    ),
    Scenario(
        name="rate_limit",
        description="Zoomex client throttling emits SAFETY_RATE_LIMIT.",
        runner="pytest",
        pytest_target="rate_limit",
        expected_tags=["SAFETY_RATE_LIMIT"],
        config_overrides="maxRequestsPerSecond=1000",
    ),
]


def run_pytest_scenario(scenario: Scenario, log_path: Path) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        SCENARIO_TEST_FILE,
        "-k",
        scenario.pytest_target or scenario.name,
        "-q",
    ]
    env = dict(**os.environ)
    env["SAFETY_SCENARIO_LOG"] = str(log_path)
    return subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=scenario.timeout,
        text=True,
    )


def parse_log(log_path: Path) -> Dict[str, List[str]]:
    tags: Dict[str, List[str]] = {}
    if not log_path.exists():
        return tags
    tag_regex = re.compile(r"(SAFETY_[A-Z_]+)")
    for line in log_path.read_text().splitlines():
        match = tag_regex.search(line)
        if match:
            tag = match.group(1)
            tags.setdefault(tag, []).append(line)
    return tags


def ensure_dirs():
    SCENARIO_LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def generate_report(results: List[dict]):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    commit = git_commit()

    lines = [
        "# Safety Validation Report",
        "",
        f"- Generated: {timestamp}",
        f"- Commit: `{commit}`",
        "",
        "| Scenario | Config Highlights | Expected SAFETY Tags | Observed Tags | Result |",
        "| --- | --- | --- | --- | --- |",
    ]

    for result in results:
        expected = ", ".join(result["expected_tags"]) or "None"
        observed = ", ".join(sorted(result["observed_tags"])) or "None"
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        lines.append(
            f"| `{result['name']}` | {result['config_overrides']} | {expected} | {observed} | {status} |"
        )

    lines.append("")
    lines.append("## Scenario Details")
    for result in results:
        lines.append(f"### {result['name']}")
        lines.append(result["description"])
        lines.append("")
        lines.append(f"- Config overrides: `{result['config_overrides']}`")
        lines.append(
            f"- Expected tags: {', '.join(result['expected_tags']) or 'None'}"
        )
        lines.append(
            f"- Observed tags: {', '.join(sorted(result['observed_tags'])) or 'None'}"
        )
        lines.append(f"- Log file: `{result['log_path']}`")
        if result.get("notes"):
            lines.append(f"- Notes: {result['notes']}")
        lines.append("")

    lines.append("## Appendix: SAFETY_* Tags")
    lines.append(
        "Each log line carries a `SAFETY_*` tag to indicate which limiter engaged. "
        "Review `docs/TESTNET_SAFETY_RUNBOOK.md` for operational guidance."
    )

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ensure_dirs()
    results = []
    exit_code = 0

    for scenario in SCENARIOS:
        log_path = SCENARIO_LOG_DIR / f"{scenario.name}.log"
        if log_path.exists():
            log_path.unlink()

        print(f"Running scenario: {scenario.name}")
        try:
            completed = run_pytest_scenario(scenario, log_path)
        except subprocess.TimeoutExpired as exc:
            print(f"Scenario {scenario.name} timed out: {exc}")
            completed = None

        tags = parse_log(log_path)
        observed_tags = set(tags.keys())
        missing = [
            tag for tag in scenario.expected_tags if tag not in observed_tags
        ]
        passed = completed is not None and completed.returncode == 0 and not missing
        notes = None
        if completed is None:
            notes = "Scenario timed out."
        elif completed.returncode != 0:
            notes = "Scenario process returned non-zero exit code."
        elif missing:
            notes = f"Missing expected tags: {', '.join(missing)}"

        if not passed:
            exit_code = 1

        results.append(
            {
                "name": scenario.name,
                "description": scenario.description,
                "config_overrides": scenario.config_overrides,
                "expected_tags": scenario.expected_tags,
                "observed_tags": list(observed_tags),
                "passed": passed,
                "log_path": str(log_path),
                "notes": notes,
            }
        )

    generate_report(results)
    print(f"\nReport written to {REPORT_PATH}")
    return exit_code


if __name__ == "__main__":
    import os

    parser = argparse.ArgumentParser(description="Run perps safety validation scenarios.")
    parser.parse_args()
    sys.exit(main())
