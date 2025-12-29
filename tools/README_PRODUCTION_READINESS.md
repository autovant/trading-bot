# Production Readiness Check Tools

This directory contains tools for validating and monitoring the production readiness of the trading bot.

## Tools Overview

### 1. `production_readiness_check.py`

Comprehensive production readiness validation tool that checks:
- Python environment and dependencies
- Configuration files and structure
- Critical source files and directories
- Environment variables
- Safety features implementation
- Test coverage
- Docker configuration
- Documentation completeness
- Version control setup

**Usage:**

```bash
# Basic check (paper mode)
python tools/production_readiness_check.py --mode paper

# Check with custom config
python tools/production_readiness_check.py --mode testnet --config configs/zoomex_example.yaml

# Generate JSON report
python tools/production_readiness_check.py --mode paper --output readiness-report.json

# Strict mode (exit with error if any check fails)
python tools/production_readiness_check.py --mode paper --strict
```

**Output:**
- Console report with summary, category results, errors, and warnings
- Optional JSON report for automation
- Exit code 0 if ready, 1 if critical issues found

### 2. `update_production_status.py`

Updates the PRODUCTION_STATUS.md document based on readiness check results.

**Usage:**

```bash
# Update from a readiness report
python tools/update_production_status.py --report readiness-report.json

# Update phase completion status
python tools/update_production_status.py --update-phases

# Generate summary from multiple reports
python tools/update_production_status.py --reports report1.json report2.json report3.json --summary summary.md
```

**Features:**
- Automatically updates PRODUCTION_STATUS.md with latest check results
- Marks completed phases and tasks
- Generates summary reports from multiple checks
- Updates timestamps and recommendations

### 3. `test_production_readiness.py` (in tests/)

Comprehensive pytest test suite for production readiness validation.

**Usage:**

```bash
# Run all production readiness tests
pytest tests/test_production_readiness.py -v

# Run specific test class
pytest tests/test_production_readiness.py::TestProductionReadiness -v

# Run with detailed output
pytest tests/test_production_readiness.py -v --tb=short
```

**Test Categories:**
- Configuration and file structure
- Safety features
- Monitoring and observability
- Risk management
- Documentation completeness

## CI/CD Integration

The production readiness checks are integrated into the CI/CD pipeline via `.github/workflows/production-readiness.yml`.

This workflow runs on:
- Push to main/develop branches
- Pull requests to main/develop
- Manual trigger with mode selection

**Workflow Jobs:**
1. **production-readiness**: Runs readiness checks for paper and testnet modes
2. **integration-tests**: Runs integration test suite
3. **config-validation**: Validates YAML configs and checks for secrets
4. **documentation-check**: Verifies documentation completeness
5. **security-scan**: Scans for security issues
6. **report-status**: Aggregates and reports overall status

## Production Readiness Criteria

### Critical Checks (Must Pass)
- ✅ Python 3.8+ installed
- ✅ All required packages installed
- ✅ Configuration files present and valid
- ✅ Critical source files exist
- ✅ Directory structure correct
- ✅ For live mode: API credentials set

### Important Checks (Should Pass)
- ✅ Safety features implemented
- ✅ Risk management present
- ✅ Test files exist
- ✅ Docker configuration valid
- ✅ Documentation complete
- ✅ .gitignore properly configured

### Warning Checks (Nice to Have)
- ✅ All optional environment variables set
- ✅ Example configs present
- ✅ Additional documentation

## Recommendations by Mode

### Paper Mode
- All critical and important checks should pass
- No API credentials required
- Can proceed with warnings

### Testnet Mode
- All critical and important checks should pass
- API credentials recommended but optional
- Should minimize warnings

### Live Mode
- **All critical checks MUST pass**
- All important checks should pass
- API credentials REQUIRED
- Zero tolerance for security warnings
- Recommend 95%+ pass rate

## Integration with Development Workflow

### Before Committing
```bash
# Quick check
python tools/production_readiness_check.py --mode paper
```

### Before Pull Request
```bash
# Full check with report
python tools/production_readiness_check.py --mode paper --output pr-readiness.json --strict

# Run tests
pytest tests/test_production_readiness.py -v
```

### Before Deployment
```bash
# Check target mode
python tools/production_readiness_check.py --mode testnet --strict

# Update status document
python tools/update_production_status.py --report readiness-report.json --update-phases

# Review updated PRODUCTION_STATUS.md
```

## Automated Checks in CI

The CI pipeline automatically:
1. Runs readiness checks on every push/PR
2. Uploads readiness reports as artifacts
3. Fails the build if critical checks fail
4. Generates summary reports
5. Validates configurations
6. Scans for security issues

**View Reports:**
- GitHub Actions → Production Readiness Check → Artifacts
- Download `production-readiness-reports.zip`
- Review JSON reports

## Troubleshooting

### "Dependencies not installed" errors
```bash
# Install dependencies
pip install -r requirements.txt

# Or use virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### "Configuration file missing" errors
```bash
# Copy example configs
cp configs/zoomex_example.yaml configs/my_config.yaml

# Edit with your settings
nano configs/my_config.yaml
```

### ".gitignore patterns missing" warnings
The .gitignore already has comprehensive patterns. The warning about `*.pyc` is a false positive as it's covered by `*.py[cod]`.

### "API credentials missing" for paper mode
This is expected and safe. Paper mode doesn't require real API credentials.

## Best Practices

1. **Run checks frequently** during development
2. **Fix critical issues immediately** - don't accumulate technical debt
3. **Review warnings** - they may become errors in stricter environments
4. **Keep documentation updated** when making changes
5. **Test in paper mode first**, then testnet, then live
6. **Use strict mode** (`--strict`) in pre-commit hooks
7. **Generate reports** for audit trails and compliance

## Future Enhancements

Planned improvements:
- [ ] Runtime health checks
- [ ] Performance benchmarking
- [ ] Database integrity checks
- [ ] Network connectivity tests
- [ ] Exchange API validation
- [ ] Strategy backtesting validation
- [ ] Load testing capabilities
- [ ] Automated remediation suggestions

## Support

For issues or questions:
1. Review this README
2. Check PRODUCTION_STATUS.md for current status
3. Review CI logs in GitHub Actions
4. Check test output for detailed errors
5. Consult README_TRADING.md for trading-specific issues

## Contributing

When adding new components:
1. Add corresponding checks to `production_readiness_check.py`
2. Add tests to `tests/test_production_readiness.py`
3. Update this README with any new tools or checks
4. Update PRODUCTION_STATUS.md if completing a phase/task
