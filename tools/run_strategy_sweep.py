#!/usr/bin/env python3
"""
Strategy sweep runner for multi-TF ATR perps strategy.

Runs a grid of parameters against local CSV history and generates:
1. JSON results per symbol
2. Ranked profiles (Conservative, Standard, Aggressive)
3. Markdown report
"""

import argparse
import asyncio
import itertools
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import PerpsConfig, get_config
from tools.backtest_perps import CsvDataProvider, PerpsBacktest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/strategy_sweep.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

# Sweep Mode: "production" or "exploration"
# production: strict filters (trades >= 30, PF > 1.1)
# exploration: looser filters (trades >= 10) for short datasets/diagnostics
SWEEP_MODE = "production"


def generate_grid() -> List[Dict[str, Any]]:
    """Define the parameter grid to sweep."""
    # Base grid dimensions
    grid: Dict[str, List[Any]] = {
        "atrPeriod": [14],
        "atrStopMultiple": [1.5, 2.0],
        "hardStopMinPct": [0.008],
        "tp1Multiple": [1.0],
        "tp2Multiple": [2.0, 3.0],
        "minAtrPct": [0.002],
        "maxEmaDistanceAtr": [0.75],
        "maxBarsInTrade": [100],
        "atrRiskScaling": [True],
        "atrRiskScalingThreshold": [0.015],
        "atrRiskScalingFactor": [0.5],
        "breakevenAfterTp1": [True],
        "exitOnTrendFlip": [True, False],
        "useRsiFilter": [True],
        "rsiMin": [40],
        "rsiMax": [70],
    }

    keys = list(grid.keys())
    values = list(grid.values())
    combinations = list(itertools.product(*values))

    params_list: List[Dict[str, Any]] = []
    for combo in combinations:
        params_list.append(dict(zip(keys, combo, strict=False)))

    return params_list


class StrategySweeper:
    def __init__(self, symbols: List[str], csv_dir: str, output_dir: str):
        self.symbols = symbols
        self.csv_dir = Path(csv_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir = self.output_dir / "backtests"
        self.results_dir.mkdir(exist_ok=True)
        self.profiles_dir = self.output_dir / "profiles"
        self.profiles_dir.mkdir(exist_ok=True)

        self.base_config = get_config()
        # Ensure base config has perps enabled and correct mode
        self.base_config.perps.enabled = True
        self.base_config.perps.useMultiTfAtrStrategy = True

    async def run_sweep(
        self, smoke_test: bool = False
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Run the parameter sweep for all symbols."""
        grid = generate_grid()
        if smoke_test:
            logger.info("SMOKE TEST: Limiting grid to first 2 combinations")
            grid = grid[:2]

        logger.info(f"Starting sweep with {len(grid)} combinations per symbol")

        all_results = {}

        for symbol in self.symbols:
            logger.info(f"Processing symbol: {symbol}")
            symbol_results = []

            # Load data once per symbol
            provider = CsvDataProvider(csv_path=str(self.csv_dir))
            try:
                # Load LTF data (5m)
                # Data seems to start from 2024-04-01 based on inspection
                start_date = "2024-01-01"
                end_date = "2024-05-01"
                ltf_df = await provider.fetch(symbol, "5", start_date, end_date)

                # Resample for HTF (60m)
                # We assume 5m data is sufficient source for 60m resampling
                htf_df = (
                    ltf_df.resample("60min")
                    .agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                        }
                    )
                    .dropna()
                )

                logger.info(
                    f"Loaded data for {symbol}: LTF={len(ltf_df)} rows, HTF={len(htf_df)} rows"
                )
                if ltf_df.empty:
                    logger.warning(f"LTF data is empty for {symbol}")
                if htf_df.empty:
                    logger.warning(f"HTF data is empty for {symbol}")

            except Exception as e:
                logger.error(f"Failed to load data for {symbol}: {e}")
                continue

            for i, params in enumerate(grid):
                if i % 10 == 0:
                    logger.info(f"  Running combination {i+1}/{len(grid)}...")

                # Create a config copy with overrides
                # We can't easily deepcopy Pydantic models with private attributes in some versions,
                # so we'll modify a copy of the perps config.

                # Create a new PerpsConfig with merged values
                perps_dict = self.base_config.perps.model_dump()
                perps_dict.update(params)
                perps_dict["symbol"] = symbol

                # Re-validate
                try:
                    run_config = PerpsConfig(**perps_dict)
                except Exception as e:
                    logger.error(f"Invalid config for params {params}: {e}")
                    continue

                backtest = PerpsBacktest(
                    run_config, initial_balance=1000.0, use_multi_tf=True
                )

                try:
                    metrics = backtest.run_backtest(ltf_df, htf_df)
                    if "error" not in metrics:
                        result = {
                            "params": params,
                            "metrics": metrics,
                            "symbol": symbol,
                        }
                        symbol_results.append(result)
                    else:
                        logger.warning(
                            f"Backtest returned error for {symbol}: {metrics['error']}"
                        )
                except Exception as e:
                    logger.error(f"Backtest failed for {symbol} {params}: {e}")

            # Save raw results
            self._save_symbol_results(symbol, symbol_results)
            all_results[symbol] = symbol_results

        return all_results

    def _save_symbol_results(self, symbol: str, results: List[Dict[str, Any]]):
        path = self.results_dir / f"{symbol}_strategy_sweep.json"
        with open(path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Saved {len(results)} results for {symbol} to {path}")

    def analyze_and_report(self, all_results: Dict[str, List[Dict[str, Any]]]):
        """Analyze results, select profiles, and generate report."""
        report_lines = [
            "# Perps Strategy Sweep Report",
            f"Date: {datetime.now().isoformat()}",
            f"Data Source: CSV ({self.csv_dir})",
            f"Mode: {SWEEP_MODE}",
            "",
            "> [!NOTE]",
            "> To get statistically meaningful results, first run:",
            "> `python tools/fetch_history_all.py`",
            "> then run: `python tools/run_strategy_sweep.py`",
            "> You should have at least 6–12 months of 5m data per symbol.",
            "",
            "## Summary",
            "| Symbol | Profile | PF | Max DD % | Win % | Avg R | Trades | RiskPct |",
            "|--------|---------|----|----------|-------|-------|--------|---------|",
        ]

        if SWEEP_MODE == "exploration":
            report_lines.insert(
                4,
                "\n> [!WARNING]\n> Running in EXPLORATION mode. Filters are relaxed (trades >= 10). Do not use these configs for live trading without further validation.\n",
            )

        for symbol, results in all_results.items():
            logger.info(f"Analyzing {symbol}...")
            valid_configs = self._filter_configs(results)

            profiles = {
                "Conservative": self._select_profile(valid_configs, "conservative"),
                "Standard": self._select_profile(valid_configs, "standard"),
                "Aggressive": self._select_profile(valid_configs, "aggressive"),
            }

            for name, config in profiles.items():
                if config:
                    m = config["metrics"]
                    risk_pct = (
                        0.002
                        if name == "Conservative"
                        else (0.003 if name == "Standard" else 0.004)
                    )

                    # Add to report table
                    report_lines.append(
                        f"| {symbol} | {name} | {m['profit_factor']:.2f} | {m['max_drawdown']:.2f}% | "
                        f"{m['win_rate']:.1f}% | {m['avg_r_multiple']:.2f} | {m['total_trades']} | {risk_pct} |"
                    )

                    # Generate YAML
                    self._generate_yaml_profile(
                        symbol, name, config["params"], risk_pct
                    )
                else:
                    report_lines.append(
                        f"| {symbol} | {name} | N/A | - | - | - | - | - |"
                    )

            # Add detailed section for symbol
            report_lines.extend(
                [
                    "",
                    f"## {symbol} Analysis",
                    "Top 3 Configs by Score:",
                    "",
                    "| Rank | PF | DD% | Trades | Params |",
                    "|------|----|-----|--------|--------|",
                ]
            )

            sorted_configs = sorted(
                valid_configs, key=lambda x: self._calculate_score(x), reverse=True
            )
            for i, cfg in enumerate(sorted_configs[:3]):
                m = cfg["metrics"]
                p_str = ", ".join(
                    f"{k}={v}"
                    for k, v in cfg["params"].items()
                    if k in ["atrStopMultiple", "tp2Multiple", "maxBarsInTrade"]
                )
                report_lines.append(
                    f"| {i+1} | {m['profit_factor']:.2f} | {m['max_drawdown']:.2f} | {m['total_trades']} | {p_str} |"
                )

        # Write report
        report_path = Path("docs/PERPS_STRATEGY_SWEEP_REPORT.md")
        report_path.parent.mkdir(exist_ok=True)
        with open(report_path, "w") as f:
            f.write("\n".join(report_lines))
        logger.info(f"Report generated at {report_path}")

    def _filter_configs(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        valid = []
        min_trades = 30 if SWEEP_MODE == "production" else 10
        min_pf = 1.1 if SWEEP_MODE == "production" else 1.0

        for r in results:
            m = r["metrics"]
            if m.get("error"):
                continue
            if m["total_trades"] < min_trades:
                continue
            if m["profit_factor"] <= min_pf:
                continue
            if m["max_drawdown"] <= 0:  # Should be positive number representing % drop?
                # Backtest returns positive float for max_drawdown (e.g. 15.5 for 15.5%)
                # Wait, let's check backtest_perps.py
                # max_drawdown = drawdown.min() which is negative.
                # But then: "max_drawdown": max_drawdown * 100
                # So if drawdown is -0.15, max_drawdown in metrics is -15.0
                # But usually "Max Drawdown" is referred to as a positive magnitude.
                # Let's check the code again.
                # drawdown = (equity - peak) / peak. This is negative.
                # max_drawdown = drawdown.min(). This is negative.
                # metrics["max_drawdown"] = max_drawdown * 100. This is negative.
                # So -15.0 means 15% drawdown.
                # The requirement says "max_drawdown <= 10%".
                # If the metric is -15, then abs(-15) <= 10 is False.
                pass

            valid.append(r)
        return valid

    def _calculate_score(self, result: Dict[str, Any]) -> float:
        m = result["metrics"]
        pf = m["profit_factor"]
        sharpe = m["sharpe_ratio"]
        dd = abs(m["max_drawdown"])  # Convert to positive for penalty calculation

        sharpe_clipped = min(max(sharpe, 0), 3)

        # score = PF + 0.5 * Sharpe - 0.5 * (DD / 10)
        score = pf + 0.5 * sharpe_clipped - 0.5 * (dd / 10.0)
        return score

    def _select_profile(
        self, configs: List[Dict[str, Any]], profile_type: str
    ) -> Optional[Dict[str, Any]]:
        candidates = []
        for c in configs:
            m = c["metrics"]
            dd = abs(m["max_drawdown"])
            trades = m["total_trades"]
            pf = m["profit_factor"]
            avg_r = m["avg_r_multiple"]

            if profile_type == "conservative":
                if (
                    dd <= 10
                    and trades >= (40 if SWEEP_MODE == "production" else 15)
                    and 0.6 <= avg_r <= 1.5
                ):
                    candidates.append(c)
            elif profile_type == "standard":
                if dd <= 15 and pf >= 1.4:
                    candidates.append(c)
            elif profile_type == "aggressive":
                if dd <= 25 and pf >= 1.6:
                    candidates.append(c)

        if not candidates:
            return None

        return max(candidates, key=self._calculate_score)

    def _generate_yaml_profile(
        self, symbol: str, profile_name: str, params: Dict[str, Any], risk_pct: float
    ):
        profile_slug = profile_name.lower()
        filename = f"profile_{symbol}_{profile_slug}.yaml"
        path = self.profiles_dir / filename

        config_dict = {
            "perps": {
                "enabled": True,
                "symbol": symbol,
                "interval": "5",
                "useMultiTfAtrStrategy": True,
                "htfInterval": "60",
                "riskPct": risk_pct,
                **params,
            }
        }

        with open(path, "w") as f:
            f.write(f"# Auto-generated {profile_name} profile for {symbol}\n")
            yaml.dump(config_dict, f, sort_keys=False)
        logger.info(f"Generated profile: {path}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run a quick smoke test")
    parser.add_argument(
        "--csv-dir", default="data/history", help="Directory containing CSV files"
    )
    parser.add_argument("--output-dir", default="results", help="Directory for results")
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Skip backtest and only analyze existing results",
    )
    parser.add_argument(
        "--mode",
        choices=["production", "exploration"],
        default="production",
        help="Sweep mode",
    )
    args = parser.parse_args()

    global SWEEP_MODE
    SWEEP_MODE = args.mode

    # Discover symbols
    csv_path = Path(args.csv_dir)
    if not csv_path.exists():
        logger.error(f"CSV directory not found: {csv_path}")
        return

    files = list(csv_path.glob("*_5m.csv"))
    symbols = [f.name.replace("_5m.csv", "") for f in files]

    if not symbols:
        logger.error("No *_5m.csv files found in data/history")
        logger.error("To fetch history, run: python tools/fetch_history_all.py")
        return

    logger.info(f"Found symbols: {symbols}")
    logger.info(f"Running in {SWEEP_MODE} mode")

    sweeper = StrategySweeper(symbols, str(csv_path), args.output_dir)

    if args.analyze_only:
        results = {}
        for symbol in symbols:
            path = sweeper.results_dir / f"{symbol}_strategy_sweep.json"
            if path.exists():
                with open(path, "r") as f:
                    results[symbol] = json.load(f)
    else:
        results = await sweeper.run_sweep(smoke_test=args.smoke)

    sweeper.analyze_and_report(results)

    logger.info("Sweep complete.")


if __name__ == "__main__":
    asyncio.run(main())
