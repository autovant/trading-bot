# Microservices Architecture

The trading bot uses a microservices architecture with NATS messaging for communication between services.

## Services Overview

### 1. Feed Handler Service
- **Language**: Go
- **Purpose**: Handles market data ingestion and distribution
- **Communication**: Publishes market data to NATS
- **Docker**: `feed-handler` service

### 2. Execution Service
- **Language**: Go
- **Purpose**: Handles order execution and execution reports
- **Communication**: Subscribes to order requests, publishes execution reports
- **Docker**: `execution-service` service

### 3. Risk State Service
- **Language**: Go
- **Purpose**: Monitors and manages risk state (crisis mode, drawdown, etc.)
- **Communication**: Subscribes to risk management topics, publishes risk state
- **Docker**: `risk-state` service

### 4. Reporter Service
- **Language**: Go
- **Purpose**: Generates performance reports and metrics
- **Communication**: Subscribes to performance metrics, publishes reports
- **Docker**: `reporter` service

### 5. Ops API Service
- **Language**: Go
- **Purpose**: Provides operational APIs for monitoring and control
- **Communication**: HTTP REST API
- **Docker**: `ops-api` service

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
- Feed handler (Go)
- Execution service (Go)
- Risk state service (Go)
- Reporter service (Go)
- Ops API service (Go)

## Health Checks

All services include health checks:
- Python services: Database connectivity
- Go services: Process health
- NATS: HTTP monitoring endpoint

## Configuration

Services are configured through:
- Environment variables
- Configuration files
- NATS messaging for dynamic updates