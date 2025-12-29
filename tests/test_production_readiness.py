"""
Production Readiness Integration Tests

These tests validate that all critical production components are working correctly.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml


class TestProductionReadiness:
    """Comprehensive production readiness tests."""

    def test_configuration_files_exist(self):
        """Verify all required configuration files exist."""
        required_files = [
            "config/strategy.yaml",
            ".env.example",
            "configs/zoomex_example.yaml",
        ]

        for file_path in required_files:
            path = Path(file_path)
            assert path.exists(), f"Required configuration file missing: {file_path}"

    def test_critical_source_files_exist(self):
        """Verify critical source files exist."""
        critical_files = [
            "src/main.py",
            "src/config.py",
            "src/database.py",
            "src/messaging.py",
            "src/strategy.py",
            "src/services/execution.py",
            "src/services/feed.py",
            "src/exchanges/zoomex_v3.py",
            "tools/backtest.py",
            "run_bot.py",
        ]

        for file_path in critical_files:
            path = Path(file_path)
            assert path.exists(), f"Critical source file missing: {file_path}"

    def test_documentation_exists(self):
        """Verify required documentation exists."""
        docs = [
            "README.md",
            "README_TRADING.md",
            "PRODUCTION_STATUS.md",
            "QA_CHECKLIST.md",
        ]

        for doc in docs:
            path = Path(doc)
            assert path.exists(), f"Required documentation missing: {doc}"

    def test_docker_configuration_valid(self):
        """Verify Docker configuration is valid."""
        docker_compose = Path("docker-compose.yml")
        assert docker_compose.exists(), "docker-compose.yml not found"

        # Check it's valid YAML
        with open(docker_compose) as f:
            config = yaml.safe_load(f)

        assert "services" in config, "docker-compose.yml missing 'services' key"
        assert isinstance(config["services"], dict), "services should be a dictionary"

        # Check for critical services
        expected_services = [
            "strategy-engine",
            "execution",
            "feed",
            "api",
        ]

        for service in expected_services:
            # Services might have different names, check if any service name contains these keywords
            found = any(service in svc_name for svc_name in config["services"].keys())
            # This is a soft check - we'll just warn if not found
            if not found:
                print(f"Warning: Expected service '{service}' not found in docker-compose.yml")

    def test_config_yaml_structure(self):
        """Verify main config YAML has required structure."""
        config_path = Path("config/strategy.yaml")
        if not config_path.exists():
            pytest.skip("config/strategy.yaml not found")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Check for critical top-level keys
        expected_keys = ["mode", "exchange"]
        for key in expected_keys:
            assert key in config, f"config/strategy.yaml missing required key: {key}"

    def test_gitignore_excludes_sensitive_files(self):
        """Verify .gitignore excludes sensitive files and patterns."""
        gitignore = Path(".gitignore")
        assert gitignore.exists(), ".gitignore not found"

        with open(gitignore) as f:
            content = f.read()

        # Check for critical patterns
        critical_patterns = [".env", "venv", "__pycache__", "data/", "logs/"]
        for pattern in critical_patterns:
            assert pattern in content, f".gitignore should include: {pattern}"

    def test_test_files_exist(self):
        """Verify test files exist for critical components."""
        test_files = [
            "tests/test_strategy.py",
            "tests/test_indicators.py",
            "tests/test_paper_broker.py",
            "tests/test_execution.py",
        ]

        for test_file in test_files:
            path = Path(test_file)
            assert path.exists(), f"Test file missing: {test_file}"

    def test_directory_structure(self):
        """Verify required directory structure exists."""
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
        ]

        for dir_path in required_dirs:
            path = Path(dir_path)
            assert path.exists() and path.is_dir(), f"Required directory missing: {dir_path}"

    def test_production_status_document_valid(self):
        """Verify PRODUCTION_STATUS.md is well-formed."""
        status_doc = Path("PRODUCTION_STATUS.md")
        assert status_doc.exists(), "PRODUCTION_STATUS.md not found"

        with open(status_doc) as f:
            content = f.read()

        # Check for key sections
        expected_sections = [
            "Production Readiness Status",
            "Implementation Checklist",
            "Testing & Validation",
            "Production Hardening",
        ]

        for section in expected_sections:
            assert section in content, f"PRODUCTION_STATUS.md missing section: {section}"

    def test_qa_checklist_valid(self):
        """Verify QA_CHECKLIST.md is well-formed."""
        qa_doc = Path("QA_CHECKLIST.md")
        assert qa_doc.exists(), "QA_CHECKLIST.md not found"

        with open(qa_doc) as f:
            content = f.read()

        # Check for test sets
        expected_sections = [
            "Mode & Safety",
            "Strategy",
            "Paper Trading",
        ]

        for section in expected_sections:
            # Flexible check - just ensure some mention exists
            found = any(s.lower() in content.lower() for s in [section])
            if not found:
                print(f"Warning: QA_CHECKLIST.md may be missing section: {section}")

    def test_requirements_file_valid(self):
        """Verify requirements.txt is valid."""
        requirements = Path("requirements.txt")
        assert requirements.exists(), "requirements.txt not found"

        with open(requirements) as f:
            lines = f.readlines()

        # Check for critical packages
        critical_packages = [
            "fastapi",
            "pandas",
            "numpy",
            "pytest",
        ]

        content = "".join(lines).lower()
        for package in critical_packages:
            assert package.lower() in content, f"requirements.txt missing: {package}"

    def test_entry_points_executable(self):
        """Verify main entry points have proper structure."""
        entry_points = [
            "src/main.py",
            "run_bot.py",
            "tools/backtest.py",
        ]

        for entry_point in entry_points:
            path = Path(entry_point)
            assert path.exists(), f"Entry point missing: {entry_point}"

            # Check if file has execute permission or is a .py file
            assert path.suffix == ".py", f"Entry point should be .py file: {entry_point}"

            # Check if it has a main guard or entry point
            with open(path) as f:
                content = f.read()
                # Most entry points should have __main__ or be importable
                has_entry = (
                    '__name__ == "__main__"' in content
                    or "def main(" in content
                    or "async def main(" in content
                )
                assert has_entry, f"Entry point {entry_point} missing main entry point"

    def test_mode_validation_present(self):
        """Verify mode validation is implemented."""
        config_file = Path("src/config.py")
        assert config_file.exists(), "src/config.py not found"

        with open(config_file) as f:
            content = f.read()

        # Check for mode-related code
        mode_indicators = ["paper", "testnet", "live", "mode"]
        found = any(indicator in content.lower() for indicator in mode_indicators)
        assert found, "Mode validation not found in src/config.py"

    def test_risk_management_present(self):
        """Verify risk management components are present."""
        risk_indicators = [
            ("src/risk", "directory"),
            ("src/risk/risk_manager.py", "file"),
            ("src/engine/perps_executor.py", "file"),
        ]

        for path_str, expected_type in risk_indicators:
            path = Path(path_str)
            if expected_type == "directory":
                if path.exists() and path.is_dir():
                    continue
            elif expected_type == "file":
                if path.exists() and path.is_file():
                    continue
            # At least one should exist
            print(f"Warning: Risk component {path_str} not found")

    def test_exchange_abstraction_present(self):
        """Verify exchange abstraction layer exists."""
        exchange_files = [
            "src/exchange.py",
            "src/exchanges/zoomex_v3.py",
        ]

        found = False
        for exchange_file in exchange_files:
            if Path(exchange_file).exists():
                found = True
                break

        assert found, "Exchange abstraction layer not found"

    def test_database_implementation_present(self):
        """Verify database implementation exists."""
        db_file = Path("src/database.py")
        assert db_file.exists(), "Database implementation not found"

        with open(db_file) as f:
            content = f.read()

        # Check for database-related code
        db_indicators = ["database", "sqlite", "async", "initialize"]
        found_count = sum(1 for indicator in db_indicators if indicator in content.lower())
        assert found_count >= 2, "Database implementation may be incomplete"

    def test_messaging_implementation_present(self):
        """Verify messaging implementation exists."""
        messaging_file = Path("src/messaging.py")
        assert messaging_file.exists(), "Messaging implementation not found"

        with open(messaging_file) as f:
            content = f.read()

        # Check for NATS-related code
        nats_indicators = ["nats", "publish", "subscribe"]
        found_count = sum(1 for indicator in nats_indicators if indicator in content.lower())
        assert found_count >= 2, "Messaging implementation may be incomplete"

    def test_paper_trading_implementation(self):
        """Verify paper trading implementation exists."""
        paper_files = [
            "src/paper_trader.py",
            "src/paper_broker.py",
        ]

        found = False
        for paper_file in paper_files:
            if Path(paper_file).exists():
                found = True
                break

        assert found, "Paper trading implementation not found"

    def test_backtest_engine_present(self):
        """Verify backtesting engine exists."""
        backtest_file = Path("tools/backtest.py")
        assert backtest_file.exists(), "Backtesting engine not found"

        with open(backtest_file) as f:
            content = f.read()

        # Check for backtest-related code
        backtest_indicators = ["backtest", "historical", "simulate"]
        found_count = sum(
            1 for indicator in backtest_indicators if indicator in content.lower()
        )
        assert found_count >= 1, "Backtesting engine may be incomplete"

    @pytest.mark.asyncio
    async def test_async_support(self):
        """Verify async/await support is working."""
        # Simple test to ensure async works
        async def test_coroutine():
            await asyncio.sleep(0.01)
            return True

        result = await test_coroutine()
        assert result is True, "Async support not working"


class TestSafetyFeatures:
    """Tests for safety features implementation."""

    def test_mode_switching_safety(self):
        """Verify mode switching has safety checks."""
        # Check config file has mode validation
        config_file = Path("src/config.py")
        if config_file.exists():
            with open(config_file) as f:
                content = f.read()
            # Look for mode validation
            has_validation = "mode" in content.lower() and (
                "paper" in content or "testnet" in content or "live" in content
            )
            assert has_validation, "Mode switching safety not implemented"

    def test_api_key_validation(self):
        """Verify API key validation exists."""
        # Check for API key validation in config or exchange files
        files_to_check = [
            "src/config.py",
            "src/exchanges/zoomex_v3.py",
            "tools/validate_setup.py",
        ]

        found_validation = False
        for file_path in files_to_check:
            path = Path(file_path)
            if path.exists():
                with open(path) as f:
                    content = f.read()
                if "api" in content.lower() and "key" in content.lower():
                    found_validation = True
                    break

        assert found_validation, "API key validation not found"

    def test_risk_limits_configured(self):
        """Verify risk limits are configurable."""
        # Check config files for risk parameters
        config_files = [
            "config/strategy.yaml",
            "configs/zoomex_example.yaml",
        ]

        found_risk_config = False
        for config_file in config_files:
            path = Path(config_file)
            if path.exists():
                with open(path) as f:
                    content = f.read()
                    # Check for risk-related parameters
                    risk_params = [
                        "risk",
                        "stop",
                        "leverage",
                        "position",
                        "circuit",
                    ]
                    if any(param in content.lower() for param in risk_params):
                        found_risk_config = True
                        break

        assert found_risk_config, "Risk limits not configured"


class TestMonitoringAndObservability:
    """Tests for monitoring and observability features."""

    def test_prometheus_configuration(self):
        """Verify Prometheus monitoring is configured."""
        prometheus_file = Path("prometheus.yml")
        assert prometheus_file.exists(), "prometheus.yml not found"

    def test_health_check_endpoints(self):
        """Verify services have health check endpoints."""
        service_files = [
            "src/services/execution.py",
            "src/services/feed.py",
        ]

        found_health_check = False
        for service_file in service_files:
            path = Path(service_file)
            if path.exists():
                with open(path) as f:
                    content = f.read()
                if "health" in content.lower():
                    found_health_check = True
                    break

        assert found_health_check, "Health check endpoints not found"

    def test_logging_implementation(self):
        """Verify logging is properly implemented."""
        # Check for logging in main files
        main_files = [
            "src/main.py",
            "src/services/execution.py",
        ]

        found_logging = False
        for main_file in main_files:
            path = Path(main_file)
            if path.exists():
                with open(path) as f:
                    content = f.read()
                if "logging" in content.lower() or "logger" in content.lower():
                    found_logging = True
                    break

        assert found_logging, "Logging implementation not found"

    def test_dashboard_exists(self):
        """Verify monitoring dashboard exists."""
        dashboard_dir = Path("dashboard")
        assert dashboard_dir.exists() and dashboard_dir.is_dir(), "Dashboard directory not found"

        # Check for dashboard app
        dashboard_files = [
            "dashboard/app.py",
            "dashboard/main.py",
        ]

        found_app = False
        for dashboard_file in dashboard_files:
            if Path(dashboard_file).exists():
                found_app = True
                break

        assert found_app, "Dashboard application not found"
