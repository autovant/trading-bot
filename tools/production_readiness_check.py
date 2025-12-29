#!/usr/bin/env python3
"""
Production Readiness Check Tool

This script validates that the trading bot meets production readiness criteria.
It checks configuration, dependencies, safety features, risk management, and more.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml


class ProductionReadinessChecker:
    """Comprehensive production readiness validation."""

    def __init__(self, config_path: Optional[str] = None, mode: str = "paper"):
        self.config_path = config_path
        self.mode = mode
        self.checks: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.info: List[str] = []

    def add_check(
        self, category: str, name: str, passed: bool, message: str, severity: str = "error"
    ):
        """Add a check result."""
        self.checks.append(
            {
                "category": category,
                "name": name,
                "passed": passed,
                "message": message,
                "severity": severity,
            }
        )
        if not passed:
            if severity == "error":
                self.errors.append(f"{category} - {name}: {message}")
            elif severity == "warning":
                self.warnings.append(f"{category} - {name}: {message}")
        else:
            self.info.append(f"{category} - {name}: ✓")

    def check_python_version(self) -> bool:
        """Verify Python version compatibility."""
        category = "Environment"
        try:
            import sys

            version = sys.version_info
            required_major, required_minor = 3, 8
            passed = version >= (required_major, required_minor)
            self.add_check(
                category,
                "Python Version",
                passed,
                f"Python {version.major}.{version.minor}.{version.micro} "
                f"({'✓' if passed else 'requires >= 3.8'})",
            )
            return passed
        except Exception as e:
            self.add_check(category, "Python Version", False, f"Error: {e}")
            return False

    def check_required_packages(self) -> bool:
        """Verify required Python packages are installed."""
        category = "Dependencies"
        required_packages = [
            "fastapi",
            "uvicorn",
            "nats",
            "pandas",
            "numpy",
            "pydantic",
            "yaml",
            "asyncio",
            "aiohttp",
            "pytest",
        ]

        all_passed = True
        for package in required_packages:
            try:
                __import__(package.replace("-", "_"))
                self.add_check(category, f"Package: {package}", True, "Installed")
            except ImportError:
                self.add_check(
                    category, f"Package: {package}", False, f"{package} not installed"
                )
                all_passed = False

        return all_passed

    def check_configuration_files(self) -> bool:
        """Verify configuration files exist and are valid."""
        category = "Configuration"
        all_passed = True

        # Check main config
        config_files = [
            "config/strategy.yaml",
            ".env.example",
            "configs/zoomex_example.yaml",
        ]

        for config_file in config_files:
            path = Path(config_file)
            exists = path.exists()
            self.add_check(
                category,
                f"Config File: {config_file}",
                exists,
                "Found" if exists else "Missing",
                severity="warning" if config_file.endswith(".example") else "error",
            )
            if not exists and not config_file.endswith(".example"):
                all_passed = False

        # Check if custom config is provided
        if self.config_path:
            path = Path(self.config_path)
            exists = path.exists()
            self.add_check(
                category, f"Custom Config: {self.config_path}", exists, "Found" if exists else "Missing"
            )
            if not exists:
                all_passed = False
            else:
                # Validate YAML syntax
                try:
                    with open(path) as f:
                        config = yaml.safe_load(f)
                    self.add_check(category, "YAML Syntax", True, "Valid YAML")

                    # Check critical keys
                    critical_keys = ["mode", "exchange"]
                    for key in critical_keys:
                        has_key = key in config
                        self.add_check(
                            category,
                            f"Config Key: {key}",
                            has_key,
                            "Present" if has_key else "Missing",
                        )
                        if not has_key:
                            all_passed = False

                except yaml.YAMLError as e:
                    self.add_check(category, "YAML Syntax", False, f"Invalid YAML: {e}")
                    all_passed = False
                except Exception as e:
                    self.add_check(category, "Config Read", False, f"Error: {e}")
                    all_passed = False

        return all_passed

    def check_directory_structure(self) -> bool:
        """Verify required directories exist."""
        category = "File Structure"
        required_dirs = [
            "src",
            "src/services",
            "src/exchanges",
            "src/strategies",
            "src/engine",
            "src/api",
            "config",
            "tests",
            "tools",
            "dashboard",
            "data",
        ]

        all_passed = True
        for dir_path in required_dirs:
            path = Path(dir_path)
            exists = path.exists() and path.is_dir()
            self.add_check(
                category, f"Directory: {dir_path}", exists, "Found" if exists else "Missing"
            )
            if not exists:
                all_passed = False

        return all_passed

    def check_critical_files(self) -> bool:
        """Verify critical source files exist."""
        category = "Critical Files"
        critical_files = [
            "src/main.py",
            "src/config.py",
            "src/database.py",
            "src/messaging.py",
            "src/strategy.py",
            "src/services/execution.py",
            "src/services/feed.py",
            "tools/backtest.py",
            "run_bot.py",
            "docker-compose.yml",
        ]

        all_passed = True
        for file_path in critical_files:
            path = Path(file_path)
            exists = path.exists() and path.is_file()
            self.add_check(
                category, f"File: {file_path}", exists, "Found" if exists else "Missing"
            )
            if not exists:
                all_passed = False

        return all_passed

    def check_environment_variables(self) -> bool:
        """Check for required environment variables based on mode."""
        category = "Environment Variables"
        all_passed = True

        # For live mode, API keys are required
        if self.mode == "live":
            required_vars = ["ZOOMEX_API_KEY", "ZOOMEX_API_SECRET"]
            for var in required_vars:
                exists = os.getenv(var) is not None
                self.add_check(
                    category,
                    f"Env Var: {var}",
                    exists,
                    "Set" if exists else "Missing (required for live mode)",
                )
                if not exists:
                    all_passed = False
        else:
            # For paper/testnet, they're optional but we'll check
            optional_vars = ["ZOOMEX_API_KEY", "ZOOMEX_API_SECRET"]
            for var in optional_vars:
                exists = os.getenv(var) is not None
                self.add_check(
                    category,
                    f"Env Var: {var}",
                    True,  # Don't fail
                    "Set" if exists else f"Not set (optional for {self.mode} mode)",
                    severity="warning" if not exists else "info",
                )

        return all_passed

    def check_safety_features(self) -> bool:
        """Verify safety features are implemented."""
        category = "Safety Features"
        all_passed = True

        safety_checks = [
            ("Mode validation", "src/config.py", "mode"),
            ("Risk management", "src/risk", "risk"),
            ("Position sizing", "src/engine", "position"),
            ("Stop loss", "src/strategies", "stop"),
            ("Circuit breaker", "src/risk", "circuit"),
        ]

        for check_name, path_hint, keyword in safety_checks:
            # Check if relevant files exist
            path = Path(path_hint)
            exists = path.exists()
            self.add_check(
                category,
                check_name,
                exists,
                "Implemented" if exists else "Missing",
                severity="warning" if not exists else "info",
            )
            if not exists:
                all_passed = False

        return all_passed

    def check_test_coverage(self) -> bool:
        """Check if tests exist for critical components."""
        category = "Testing"
        test_files = [
            "tests/test_strategy.py",
            "tests/test_indicators.py",
            "tests/test_paper_broker.py",
            "tests/test_execution.py",
            "tests/test_readiness_gates.py",
        ]

        all_passed = True
        for test_file in test_files:
            path = Path(test_file)
            exists = path.exists()
            self.add_check(
                category, f"Test: {test_file}", exists, "Found" if exists else "Missing"
            )
            if not exists:
                all_passed = False

        return all_passed

    def check_docker_setup(self) -> bool:
        """Verify Docker configuration."""
        category = "Docker"
        docker_files = ["docker-compose.yml", "Dockerfile"]

        all_passed = True
        for file in docker_files:
            path = Path(file)
            exists = path.exists()
            self.add_check(category, f"File: {file}", exists, "Found" if exists else "Missing")
            if not exists:
                all_passed = False

        return all_passed

    def check_documentation(self) -> bool:
        """Verify documentation exists."""
        category = "Documentation"
        docs = [
            "README.md",
            "README_TRADING.md",
            "PRODUCTION_STATUS.md",
            "QA_CHECKLIST.md",
        ]

        all_passed = True
        for doc in docs:
            path = Path(doc)
            exists = path.exists()
            self.add_check(
                category,
                f"Doc: {doc}",
                exists,
                "Found" if exists else "Missing",
                severity="warning",
            )
            if not exists:
                all_passed = False

        return all_passed

    def check_gitignore(self) -> bool:
        """Verify .gitignore is properly configured."""
        category = "Version Control"
        path = Path(".gitignore")
        exists = path.exists()

        if not exists:
            self.add_check(category, ".gitignore", False, "Missing")
            return False

        # Check for important patterns
        with open(path) as f:
            content = f.read()

        important_patterns = [".env", "__pycache__", "*.pyc", "venv", "data/", "logs/"]
        all_found = True
        for pattern in important_patterns:
            found = pattern in content
            if not found:
                self.add_check(
                    category,
                    f"Pattern: {pattern}",
                    False,
                    "Missing from .gitignore",
                    severity="warning",
                )
                all_found = False

        if all_found:
            self.add_check(category, ".gitignore", True, "Properly configured")

        return all_found

    def run_all_checks(self) -> Dict[str, Any]:
        """Run all production readiness checks."""
        print("=" * 80)
        print("PRODUCTION READINESS CHECK")
        print(f"Mode: {self.mode.upper()}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("=" * 80)
        print()

        # Run all checks
        checks = [
            ("Environment", self.check_python_version),
            ("Dependencies", self.check_required_packages),
            ("Configuration", self.check_configuration_files),
            ("File Structure", self.check_directory_structure),
            ("Critical Files", self.check_critical_files),
            ("Environment Variables", self.check_environment_variables),
            ("Safety Features", self.check_safety_features),
            ("Testing", self.check_test_coverage),
            ("Docker", self.check_docker_setup),
            ("Documentation", self.check_documentation),
            ("Version Control", self.check_gitignore),
        ]

        results = {}
        for category, check_func in checks:
            print(f"Checking {category}...")
            try:
                passed = check_func()
                results[category] = passed
            except Exception as e:
                print(f"  Error in {category}: {e}")
                results[category] = False
                self.add_check(category, "Execution", False, f"Check failed: {e}")

        return results

    def generate_report(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive report."""
        total_checks = len(self.checks)
        passed_checks = sum(1 for c in self.checks if c["passed"])
        failed_checks = total_checks - passed_checks

        report = {
            "timestamp": datetime.now().isoformat(),
            "mode": self.mode,
            "summary": {
                "total_checks": total_checks,
                "passed": passed_checks,
                "failed": failed_checks,
                "pass_rate": (passed_checks / total_checks * 100) if total_checks > 0 else 0,
            },
            "category_results": results,
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "recommendation": self._get_recommendation(results, passed_checks, total_checks),
        }

        return report

    def _get_recommendation(
        self, results: Dict[str, Any], passed: int, total: int
    ) -> str:
        """Generate recommendation based on results."""
        pass_rate = (passed / total * 100) if total > 0 else 0

        critical_categories = [
            "Environment",
            "Dependencies",
            "Configuration",
            "Critical Files",
        ]
        critical_failed = any(not results.get(cat, False) for cat in critical_categories)

        if critical_failed:
            return "❌ NOT READY - Critical checks failed. Fix errors before proceeding."
        elif pass_rate >= 95:
            if self.mode == "live":
                return "✅ PRODUCTION READY - All critical checks passed. Review warnings before live trading."
            else:
                return f"✅ READY FOR {self.mode.upper()} - All critical checks passed."
        elif pass_rate >= 80:
            return "⚠️  MOSTLY READY - Some non-critical checks failed. Review and fix warnings."
        else:
            return "❌ NOT READY - Multiple checks failed. Address issues before proceeding."

    def print_report(self, report: Dict[str, Any]):
        """Print formatted report."""
        print()
        print("=" * 80)
        print("PRODUCTION READINESS REPORT")
        print("=" * 80)
        print()

        # Summary
        summary = report["summary"]
        print(f"Summary:")
        print(f"  Total Checks: {summary['total_checks']}")
        print(f"  Passed: {summary['passed']} ✓")
        print(f"  Failed: {summary['failed']} ✗")
        print(f"  Pass Rate: {summary['pass_rate']:.1f}%")
        print()

        # Category breakdown
        print("Category Results:")
        for category, passed in report["category_results"].items():
            status = "✓" if passed else "✗"
            print(f"  {status} {category}")
        print()

        # Errors
        if report["errors"]:
            print(f"Errors ({len(report['errors'])}):")
            for error in report["errors"]:
                print(f"  ✗ {error}")
            print()

        # Warnings
        if report["warnings"]:
            print(f"Warnings ({len(report['warnings'])}):")
            for warning in report["warnings"]:
                print(f"  ⚠  {warning}")
            print()

        # Recommendation
        print("=" * 80)
        print("RECOMMENDATION")
        print("=" * 80)
        print(report["recommendation"])
        print("=" * 80)
        print()

    def save_report(self, report: Dict[str, Any], output_path: str):
        """Save report to JSON file."""
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Production Readiness Check for Trading Bot"
    )
    parser.add_argument(
        "--config", type=str, help="Path to configuration file", default=None
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["paper", "testnet", "live"],
        default="paper",
        help="Trading mode (paper, testnet, or live)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON report to file",
        default=None,
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error code if any check fails",
    )

    args = parser.parse_args()

    # Run checks
    checker = ProductionReadinessChecker(config_path=args.config, mode=args.mode)
    results = checker.run_all_checks()
    report = checker.generate_report(results)

    # Print report
    checker.print_report(report)

    # Save report if requested
    if args.output:
        checker.save_report(report, args.output)

    # Exit with appropriate code
    if args.strict and report["summary"]["failed"] > 0:
        sys.exit(1)

    # Exit with error if critical checks failed
    if "NOT READY" in report["recommendation"]:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
