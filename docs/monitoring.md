# Monitoring Guide

Metrics collection, dashboards, and alerting for the trading bot platform.

## Overview

The monitoring stack consists of:
- **Prometheus** (port 9090) — metrics scraping and storage
- **Grafana** (port 3000) — dashboards and visualization
- **Application metrics** — each service exposes Prometheus-format metrics
- **Structured logging** — JSON logs with correlation IDs across all services

---

## Prometheus

### Configuration

Prometheus is configured via `prometheus.yml` with a global scrape interval of 15 seconds.

### Scrape Targets

| Job Name | Target | Service |
|----------|--------|---------|
| `prometheus` | `localhost:9090` | Prometheus self-monitoring |
| `strategy-engine` | `strategy-engine:8000` | Strategy engine |
| `execution` | `execution:8080` | Execution service |
| `feature-engine` | `feature-engine:8081` | Feed/feature engine |
| `ops-api` | `ops-api:8082` | Operations API |
| `reporter` | `reporter:8083` | Reporter service |
| `risk-state` | `risk-state:8084` | Risk state service |
| `replay` | `replay-service:8085` | Replay service |

### API Server Metrics Endpoint

The API server mounts the Prometheus client ASGI app at `/metrics`:

```bash
curl http://localhost:8000/metrics
```

Returns metrics in Prometheus exposition format.

### Accessing Prometheus

```
http://localhost:9090
```

Example PromQL queries:

```promql
# Active agent count
agent_active_count

# OODA cycle rate per agent
rate(agent_ooda_cycles_total[5m])

# 95th percentile OODA cycle duration
histogram_quantile(0.95, rate(agent_ooda_cycle_seconds_bucket[5m]))

# Total OODA cycles by phase
sum by (phase) (agent_ooda_cycles_total)
```

---

## Grafana

### Access

```
http://localhost:3000
```

Default credentials are configured by the Grafana container (check `grafana/provisioning/` for datasource and dashboard provisioning).

### Dashboard Provisioning

Dashboards are provisioned from:
- `grafana/provisioning/` — datasource and dashboard provider configuration
- `grafana/dashboards/` — JSON dashboard definitions

Prometheus is configured as the default data source.

---

## Application Metrics

### Agent Orchestrator Metrics

Defined in `src/services/agent_orchestrator.py`:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `agent_ooda_cycles_total` | Counter | `agent_id`, `phase` | Total OODA cycles executed. Phases: `observe`, `orient`, `decide`, `act`, `learn`, `strategy` |
| `agent_active_count` | Gauge | — | Number of agent runners currently active |
| `agent_ooda_cycle_seconds` | Histogram | — | Duration of a full OODA cycle. Buckets: 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0 seconds |

### Service Health

All services expose `/health` endpoints. Monitor these with:

```promql
# Check if a target is up
up{job="execution"}

# All targets health
up
```

---

## Recommended Alert Rules

Configure these in Prometheus or Grafana alerting:

### Trading Alerts

```yaml
groups:
  - name: trading
    rules:
      - alert: NoActiveAgents
        expr: agent_active_count == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "No active trading agents"

      - alert: SlowOODACycle
        expr: histogram_quantile(0.95, rate(agent_ooda_cycle_seconds_bucket[5m])) > 30
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Agent OODA cycles taking >30s at p95"

      - alert: AgentCycleStopped
        expr: rate(agent_ooda_cycles_total[15m]) == 0
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Agent {{ $labels.agent_id }} has not completed a cycle in 15 minutes"
```

### Infrastructure Alerts

```yaml
groups:
  - name: infrastructure
    rules:
      - alert: ServiceDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.job }} is down"

      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes > 1e9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.job }} using >1GB memory"
```

### Application Alerts

```yaml
groups:
  - name: application
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High 5xx error rate on {{ $labels.job }}"

      - alert: RateLimitExceeded
        expr: rate(rate_limit_exceeded_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Rate limiting active"
```

---

## Log Management

### Structured JSON Logging

All services use structured JSON logging. Log fields:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `level` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `service` | Service name |
| `name` | Logger name (e.g., `src.services.execution`) |
| `message` | Log message |
| `request_id` | Correlation ID (set by `CorrelationIdMiddleware`) |

### Correlation IDs

Every HTTP request to the API server gets a unique `X-Request-ID` header (auto-generated if not supplied). This ID is:
- Attached to all log entries for that request
- Propagated through service-to-service calls
- Available in the response headers

### Tracing a Request

```bash
# Search all service logs for a correlation ID
docker compose logs --no-log-prefix | grep "request-id-value"

# Filter to a specific service
docker compose logs execution --no-log-prefix | grep "request-id-value"
```

### Log Level Adjustment

```bash
# Restart a service with debug logging
LOG_LEVEL=DEBUG docker compose up -d --no-deps execution
```

### Docker Log Rotation

Configure per-service in `docker-compose.yml`:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### Viewing Logs

```bash
# All services, last 100 lines
docker compose logs --tail 100

# Single service, follow
docker compose logs -f api-server

# Filter errors
docker compose logs --no-log-prefix | grep '"level": "ERROR"'
```

---

## NATS Monitoring

NATS exposes an HTTP monitoring endpoint at port 8222:

| Endpoint | Description |
|----------|-------------|
| `/varz` | Server stats (connections, messages, bytes) |
| `/connz` | Active connections |
| `/routez` | Cluster route info |
| `/subsz` | Subscription details |

```bash
# Server overview
curl -s http://localhost:8222/varz | python3 -m json.tool

# Active connections
curl -s http://localhost:8222/connz | python3 -m json.tool

# Subscription details
curl -s http://localhost:8222/subsz | python3 -m json.tool
```

---

## Quick Reference

| What | Where | Command |
|------|-------|---------|
| Service status | Docker | `docker compose ps` |
| All health checks | Ports 8000-8088 | `curl http://localhost:{port}/health` |
| Prometheus UI | Port 9090 | `http://localhost:9090` |
| Grafana dashboards | Port 3000 | `http://localhost:3000` |
| API metrics | Port 8000 | `curl http://localhost:8000/metrics` |
| NATS stats | Port 8222 | `curl http://localhost:8222/varz` |
| Container resources | Docker | `docker stats` |
| Service logs | Docker | `docker compose logs <service>` |
