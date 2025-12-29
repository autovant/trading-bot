# Production Readiness Quick Reference

## Quick Commands

### Pre-Commit Checks
```bash
# Quick readiness check
python tools/production_readiness_check.py --mode paper

# Run production readiness tests
pytest tests/test_production_readiness.py -v
```

### Before Pull Request
```bash
# Full check with report
python tools/production_readiness_check.py --mode paper --output pr-readiness.json --strict

# Update production status
python tools/update_production_status.py --report pr-readiness.json --update-phases
```

### Before Deployment
```bash
# Check for target environment
python tools/production_readiness_check.py --mode testnet --strict

# Generate comprehensive report
python tools/production_readiness_check.py --mode testnet --output deployment-readiness.json

# Review report
cat deployment-readiness.json | python -m json.tool | less
```

## Pass/Fail Criteria

| Pass Rate | Status | Action |
|-----------|--------|--------|
| ≥ 95% | ✅ Ready | Proceed with deployment |
| 80-94% | ⚠️ Mostly Ready | Review warnings, fix critical |
| < 80% | ❌ Not Ready | Fix errors before proceeding |

## Critical Checks (Must Pass)

- ✅ Python 3.8+
- ✅ Required packages installed
- ✅ Config files present and valid
- ✅ Critical source files exist
- ✅ Directory structure correct
- ✅ For live mode: API credentials set

## Modes

### Paper Mode
- No API credentials required
- Can proceed with warnings
- For development and testing

### Testnet Mode  
- API credentials recommended
- Should minimize warnings
- For pre-production validation

### Live Mode
- All critical checks MUST pass
- API credentials REQUIRED
- Zero tolerance for security issues
- Recommend 95%+ pass rate

## CI/CD Integration

The production readiness workflow runs automatically on:
- Push to main/develop
- Pull requests
- Manual trigger

View results:
1. Go to GitHub Actions
2. Select "Production Readiness Check" workflow
3. Download artifacts for detailed reports

## Troubleshooting

### Dependencies Error
```bash
pip install -r requirements.txt
```

### Config Missing
```bash
cp configs/zoomex_example.yaml configs/my_config.yaml
```

### Permissions
```bash
chmod +x tools/production_readiness_check.py
chmod +x tools/update_production_status.py
```

## Output Files

- `readiness-report.json` - Full check results
- `PRODUCTION_STATUS.md` - Updated status document
- `production_readiness_summary.md` - Multi-report summary

## Integration Points

### Git Hooks (Optional)
Add to `.git/hooks/pre-commit`:
```bash
#!/bin/bash
python tools/production_readiness_check.py --mode paper --strict || exit 1
```

### Make Target (Optional)
Add to `Makefile`:
```makefile
.PHONY: readiness-check
readiness-check:
	python tools/production_readiness_check.py --mode paper --strict
	pytest tests/test_production_readiness.py -v
```

## Documentation

Full documentation: `tools/README_PRODUCTION_READINESS.md`
