# Microservices Architecture

The trading bot uses a microservices architecture with NATS messaging for communication between services.

## Services Overview

### 1. Feed Service
- **Language**: Python (FastAPI)
- **Purpose**: Handles market data ingestion and replay streaming
- **Communication**: Publishes market data to NATS
- **Docker**: `feature-engine` service (`uvicorn src.services.feed:app`)

### 2. Execution Service
- **Language**: Python (FastAPI)
- **Purpose**: Handles order execution, fills, and paper broker callbacks
- **Communication**: Subscribes to order requests, publishes execution reports
- **Docker**: `execution` service (`uvicorn src.services.execution:app`)

### 3. Risk State Service
- **Language**: Python (FastAPI)
- **Purpose**: Monitors and manages risk state (crisis mode, drawdown, etc.)
- **Communication**: Subscribes to risk management topics, publishes risk state
- **Docker**: `risk-state` service (`uvicorn src.services.risk:app`)

### 4. Reporter Service
- **Language**: Python (FastAPI)
- **Purpose**: Generates performance reports and exposes Prometheus metrics
- **Communication**: Subscribes to performance metrics, publishes reports
- **Docker**: `reporter` service (`uvicorn src.services.reporter:app`)

### 5. Ops API Service
- **Language**: Python (FastAPI)
- **Purpose**: Provides operational APIs for monitoring, mode switching, and config management
- **Communication**: HTTP REST API + NATS notifications
- **Docker**: `ops-api` service (`uvicorn src.ops_api_service:app`)

## NATS Messaging

### Subjects
- `market.data` - Market data updates
- `trading.orders` - Order requests
- `trading.executions` - Execution reports
- `risk.management` - Risk management commands
- `risk.state` - Risk state updates
- `performance.metrics` - Performance metrics
- `reports.performance` - Performance reports

### Message Format
All messages are JSON-encoded with a `type` field indicating the message type.

## Docker Deployment

All services are containerized and can be deployed using docker-compose:

```bash
docker-compose up -d
```

This will start:
- NATS server
- Trading bot (Python)
- Dashboard (Python)
- Feature engine / feed service (FastAPI)
- Execution service (FastAPI)
- Risk state service (FastAPI)
- Reporter service (FastAPI)
- Ops API service (FastAPI)

## Health Checks

All services include health checks:
- Python services: Database connectivity
- FastAPI services: Application and dependency health
- NATS: HTTP monitoring endpoint

## Configuration

Services are configured through:
- Environment variables
- Configuration files
- NATS messaging for dynamic updates
