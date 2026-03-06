"""Enable self-learning on all paper-trading agents."""
import json
import os
import urllib.request
import urllib.error

API_KEY = os.environ.get("API_KEY", "")
if not API_KEY:
    # Try loading from .env
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("API_KEY="):
                    API_KEY = line.strip().split("=", 1)[1]
                    break

BASE = "http://localhost:8000/api/agents"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

SELF_LEARNING_CONFIG = {
    "enabled": True,
    "mini_backtest_days": 7,
    "min_trades_for_evaluation": 2,
    "sharpe_improvement_threshold": 0.1,
    "win_rate_improvement_threshold": 0.05,
    "max_candidates_per_cycle": 5,
    "cross_agent_learning": True,
    "walk_forward_schedule_hours": 24,
    "progressive_risk": {
        "tier1_drawdown_pct": 0.03,
        "tier1_size_reduction": 0.3,
        "tier2_drawdown_pct": 0.05,
        "tier2_size_reduction": 0.5,
        "tier3_drawdown_pct": 0.10,
        "tier3_size_reduction": 0.8,
        "pause_drawdown_pct": 0.15,
        "cooldown_cycles": 5,
        "llm_postmortem_after_losses": 5,
    },
}


def main():
    # Get all agents
    req = urllib.request.Request(BASE, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        agents = json.loads(resp.read())

    print(f"Found {len(agents)} agents\n")

    for agent in agents:
        aid = agent["id"]
        name = agent["name"]
        config = agent.get("config", {})

        config["self_learning"] = SELF_LEARNING_CONFIG

        # Only send config update (not strategy_params to avoid str->dict issue)
        update_payload = {"config": config}
        update_data = json.dumps(update_payload).encode()
        req = urllib.request.Request(
            f"{BASE}/{aid}",
            data=update_data,
            headers=HEADERS,
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                sl = result.get("config", {}).get("self_learning", {})
                print(f"  OK  Agent #{aid} ({name}): self_learning.enabled={sl.get('enabled')}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            print(f"  ERR Agent #{aid} ({name}): {e.code} {body}")

    print("\nDone.")


if __name__ == "__main__":
    main()
