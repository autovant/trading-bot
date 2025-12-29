.PHONY: help
help: ## Show this help message
	@echo "Trading Bot - Production Readiness Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies
	python3 -m pip install --upgrade pip
	pip install -r requirements.txt

.PHONY: readiness-check
readiness-check: ## Run production readiness check (paper mode)
	python tools/production_readiness_check.py --mode paper

.PHONY: readiness-check-testnet
readiness-check-testnet: ## Run production readiness check (testnet mode)
	python tools/production_readiness_check.py --mode testnet

.PHONY: readiness-check-live
readiness-check-live: ## Run production readiness check (live mode)
	python tools/production_readiness_check.py --mode live

.PHONY: readiness-check-strict
readiness-check-strict: ## Run production readiness check with strict mode
	python tools/production_readiness_check.py --mode paper --strict

.PHONY: readiness-report
readiness-report: ## Generate production readiness report
	python tools/production_readiness_check.py --mode paper --output readiness-report.json
	@echo ""
	@echo "Report saved to: readiness-report.json"

.PHONY: update-status
update-status: ## Update PRODUCTION_STATUS.md with latest check results
	python tools/production_readiness_check.py --mode paper --output /tmp/readiness-report.json
	python tools/update_production_status.py --report /tmp/readiness-report.json --update-phases
	@echo ""
	@echo "PRODUCTION_STATUS.md updated"

.PHONY: test
test: ## Run all tests
	pytest tests/ -v

.PHONY: test-production
test-production: ## Run production readiness tests only
	pytest tests/test_production_readiness.py -v

.PHONY: test-integration
test-integration: ## Run integration tests
	pytest tests/test_readiness_gates.py -v

.PHONY: lint
lint: ## Run linters (ruff)
	python -m ruff check .

.PHONY: format
format: ## Format code with black
	python -m black .

.PHONY: typecheck
typecheck: ## Run type checker (mypy)
	mypy src

.PHONY: validate-config
validate-config: ## Validate configuration files
	python -c "import yaml; from pathlib import Path; [yaml.safe_load(open(f)) for f in ['config/strategy.yaml', 'docker-compose.yml', 'prometheus.yml'] if Path(f).exists()]"
	@echo "✓ All configuration files are valid"

.PHONY: pre-commit
pre-commit: lint test-production readiness-check-strict ## Run pre-commit checks
	@echo ""
	@echo "✅ Pre-commit checks passed"

.PHONY: pre-deploy
pre-deploy: lint test readiness-check-strict validate-config ## Run pre-deployment checks
	@echo ""
	@echo "✅ Pre-deployment checks passed"

.PHONY: docker-build
docker-build: ## Build Docker images
	docker compose build

.PHONY: docker-up
docker-up: ## Start Docker containers
	docker compose up -d

.PHONY: docker-down
docker-down: ## Stop Docker containers
	docker compose down

.PHONY: docker-logs
docker-logs: ## View Docker logs
	docker compose logs -f

.PHONY: clean
clean: ## Clean temporary files and caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true
	@echo "✓ Cleaned temporary files"

.PHONY: setup
setup: install validate-config ## Initial setup
	mkdir -p data logs configs
	@echo ""
	@echo "✅ Setup complete"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Copy configs/zoomex_example.yaml to your own config"
	@echo "  2. Set API credentials in .env (if needed)"
	@echo "  3. Run: make readiness-check"

.DEFAULT_GOAL := help
