# Deployment Guide

## Quick Start

### 1. Environment Setup

```bash
# Clone or navigate to the project
cd trading-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

#### Environment Variables
Create a `.env` file in the project root:

```bash
# Mandatory
POSTGRES_PASSWORD=<secure-password>
API_KEY=<api-key-for-fastapi-auth>

# Exchange API (for live/testnet)
EXCHANGE_API_KEY=<your-api-key>
EXCHANGE_SECRET_KEY=<your-api-secret>

# Optional
APP_MODE=paper                # paper | live | replay
VAULT_MASTER_KEY=<32-byte-key-base64>  # For credential vault encryption
ALERT_WEBHOOK_URL=<discord/slack-webhook>
GEMINI_API_KEY=<for-ai-features>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
LLM_API_KEY=<for-copilot-proxy>
```

#### Strategy Configuration
Edit `config/strategy.yaml` (Pydantic-validated, hot-reloadable):

```yaml
exchange:
  testnet: false  # Set to false for live trading

trading:
  initial_capital: 1000.0
  symbols: ["BTCUSDT", "ETHUSDT"]

strategy:
  confidence:
    min_threshold: 60  # Minimum confidence to trade (50-80)
```

### 3. Testing

```bash
# Run unit tests (60+ test files)
python -m pytest tests/ -v

# Run integration tests
python test_integration.py

# Test configuration
python -c "from src.config import get_config; print('Config OK')"

# Frontend E2E tests (from trading-bot-ai-studio/)
cd ../trading-bot-ai-studio && npm run test:e2e
```

### 4. Deployment Options

#### Option A: Docker Compose (Recommended)

```bash
# Full stack — paper mode
APP_MODE=paper docker compose up --build
```

This starts 13+ services:
- **Infrastructure**: PostgreSQL (TimescaleDB :5432), NATS (:4222)
- **Core Engine**: Strategy engine, Execution (:8080), Feed (:8081)
- **API & Frontend**: FastAPI API (:8000), React frontend via nginx (:8080)
- **Risk & Reporting**: Risk state (:8084), Reporter (:8083)
- **AI & Signals**: Signal engine (:8086), Copilot LLM proxy (:8087), Agent orchestrator (:8088)
- **Replay**: Replay service (:8085)
- **Monitoring**: Prometheus (:9090), Grafana (:3000)
- **Operations**: DB backup (daily encrypted backups)

Access the React UI at `http://localhost:8080`.

#### Option B: VPS Deployment (Latency-Sensitive)

Deploy latency-critical services on a VPS co-located with exchange servers:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

This deploys strategy-engine, execution, feed, NATS (leaf node), and PostgreSQL on the VPS. Frontend, monitoring, and AI services stay local. See `scripts/setup_wireguard.sh` for VPN setup.

#### Option C: Local Development (Without Docker)

```bash
# Terminal 1: Backend API
source venv/bin/activate
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Strategy engine
python src/main.py

# Terminal 3: React frontend (from trading-bot-ai-studio/)
cd ../trading-bot-ai-studio
npm install && npm run dev
```

Visit `http://localhost:5173` for the React UI (Vite dev server).

### 5. Monitoring

#### Service Health
All services expose `/health` endpoints:
- API Server: `http://localhost:8000/health`
- Execution: `http://localhost:8080/health`
- Feed: `http://localhost:8081/health`
- Risk: `http://localhost:8084/health`
- Replay: `http://localhost:8085/health`
- Signal Engine: `http://localhost:8086/health`
- LLM Proxy: `http://localhost:8087/health`
- Agent Orchestrator: `http://localhost:8088/health`

#### Dashboards
- **React UI**: `http://localhost:8080` (or `:5173` in dev)
- **Grafana**: `http://localhost:3000`
- **Prometheus**: `http://localhost:9090`

#### Logs
```bash
# Docker logs
docker compose logs -f api-server
docker compose logs -f strategy-engine
docker compose logs -f execution
```

## Production Checklist

### Security
- [ ] `POSTGRES_PASSWORD` set to a strong value
- [ ] `API_KEY` configured for FastAPI auth
- [ ] `VAULT_MASTER_KEY` set for credential encryption
- [ ] Credentials stored via vault (`/api/vault/credentials`), not in env
- [ ] CORS origins restricted to known hosts
- [ ] TLS termination configured (reverse proxy)

### Risk Management
- [ ] Position sizing validated
- [ ] Crisis mode thresholds set in `config/strategy.yaml`
- [ ] Kill switch tested (`POST /api/risk/kill-switch`)
- [ ] Alert escalation configured (Discord webhook)
- [ ] Per-agent risk guardrails defined

### Monitoring
- [ ] Prometheus scraping all service `/metrics` endpoints
- [ ] Grafana dashboards configured
- [ ] Discord alerts working
- [ ] DB backup cron verified

### Testing
- [ ] `pytest tests/` passes
- [ ] Playwright E2E passes (`npm run test:e2e`)
- [ ] Docker Compose smoke test passes
- [ ] Paper mode end-to-end verified

## Troubleshooting

### Common Issues

#### 1. Configuration Errors
```bash
python -c "from src.config import get_config; print(get_config())"
```

#### 2. Database Connection
```bash
# Check PostgreSQL (Docker)
docker compose exec postgres psql -U tradingbot -c '\dt'

# For local SQLite fallback
python -c "
from src.database import DatabaseManager
import asyncio
asyncio.run(DatabaseManager({'provider': 'sqlite', 'path': 'data/trading.db'}).initialize())
print('DB OK')
"
```

#### 3. NATS Connectivity
```bash
# Check NATS server
curl http://localhost:8222/varz
```

#### 4. Service Not Starting
```bash
# Check logs for a specific service
docker compose logs --tail=50 api-server
docker compose logs --tail=50 execution
```

## Scaling and Optimization

### Performance Tuning
1. **Data Management**
   - Optimize lookback periods
   - Use data compression
   - Implement data cleanup

2. **Strategy Optimization**
   - Backtest parameter combinations
   - Monitor performance metrics
   - Adjust confidence thresholds

3. **System Resources**
   - Monitor CPU/memory usage
   - Optimize database queries
   - Use connection pooling

### Multi-Symbol Trading
1. **Resource Allocation**
   - Balance symbols by volatility
   - Adjust position sizes
   - Monitor correlation

2. **Risk Distribution**
   - Sector exposure limits
   - Currency pair correlation
   - Market cap weighting

## Maintenance

### Daily Tasks
- [ ] Check system health
- [ ] Review trading performance
- [ ] Monitor log files
- [ ] Verify API connectivity

### Weekly Tasks
- [ ] Analyze strategy performance
- [ ] Review risk metrics
- [ ] Update configuration if needed
- [ ] Backup database

### Monthly Tasks
- [ ] Performance review
- [ ] Strategy optimization
- [ ] System updates
- [ ] Security audit

## Support and Updates

### Getting Help
1. Check logs for error messages
2. Review configuration settings
3. Test individual components
4. Consult documentation

### Updates
1. Test in development environment
2. Backup current configuration
3. Update dependencies carefully
4. Monitor after deployment

---

**⚠️ Risk Warning**: This trading bot is for educational and research purposes. Cryptocurrency trading involves substantial risk of loss. Never trade with money you cannot afford to lose. Always test thoroughly before live trading.
