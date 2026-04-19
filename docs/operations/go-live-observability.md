# Go-Live Observability Checklist — v2.0.0

**Version:** v2.0.0  
**Last Updated:** 2026-04-18  
**Owner:** SRE / DevOps Team

---

## Overview

This checklist defines the 8 critical metrics, alerting thresholds, dashboards, and runbooks required for production readiness of Phoenix Trade Bot v2.0.0.

All metrics must be instrumented, dashboards deployed, and runbooks published **before Stage 3 (Full Live Deployment)** is approved.

---

## Metrics Table

| # | Metric | Threshold | Alert Severity | Dashboard | Runbook |
|---|--------|-----------|----------------|-----------|---------|
| 1 | **Discord Ingestion Lag** | < 5s (p95) | Sev-2 if > 10s | Agent Wake Flow | [discord-lag.md](../runbooks/discord-lag.md) |
| 2 | **Agent Wake Success Rate** | > 95% | Sev-1 if < 90% | Agent Wake Flow | [agent-wake-failure.md](../runbooks/agent-wake-failure.md) |
| 3 | **Broker Order Failure Rate** | < 2% | Sev-2 if > 5% | Broker Adapter Health | [broker-order-failure.md](../runbooks/broker-order-failure.md) |
| 4 | **Signal-to-Trade Latency** | < 2s (p95) | Sev-3 if > 5s | Signal Pipeline | [trade-latency.md](../runbooks/trade-latency.md) |
| 5 | **Circuit Breaker State** | CLOSED 99%+ | Sev-2 if OPEN > 5min | Broker Adapter Health | [circuit-breaker-open.md](../runbooks/circuit-breaker-open.md) |
| 6 | **API Error Rate (5xx)** | < 0.5% | Sev-2 if > 1% | API Health | [api-errors.md](../runbooks/api-errors.md) |
| 7 | **DB Connection Pool Saturation** | < 80% | Sev-1 if > 95% | Database Health | [db-pool-saturation.md](../runbooks/db-pool-saturation.md) |
| 8 | **Redis Stream Lag** | < 1s | Sev-2 if > 5s | Redis Health | [redis-lag.md](../runbooks/redis-lag.md) |

---

## Metric Details

### 1. Discord Ingestion Lag

**What:** Time between Discord message timestamp and Phoenix DB insert.

**How to Measure:**
- Prometheus histogram: `discord_ingestion_lag_seconds` (p50, p95, p99).
- Source: `services/message-ingestion/src/main.py` (instrument before DB write).

**Collection:**
```python
# In message-ingestion service
from prometheus_client import Histogram

ingestion_lag = Histogram(
    'discord_ingestion_lag_seconds',
    'Lag between Discord message timestamp and DB insert',
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

# On message insert
lag_seconds = (datetime.utcnow() - message.timestamp).total_seconds()
ingestion_lag.observe(lag_seconds)
```

**Alert Rule (Prometheus):**
```yaml
- alert: DiscordIngestionLagHigh
  expr: histogram_quantile(0.95, discord_ingestion_lag_seconds) > 10
  for: 5m
  labels:
    severity: sev-2
  annotations:
    summary: "Discord ingestion lag p95 > 10s"
    runbook: "https://docs/runbooks/discord-lag.md"
```

---

### 2. Agent Wake Success Rate

**What:** Percentage of agent spawn requests that result in a running agent (not ERROR state).

**How to Measure:**
- Prometheus counter: `agent_wake_total{status="success|failure"}`.
- Source: `apps/api/src/services/agent_gateway.py` (increment on create_live_agent).

**Collection:**
```python
from prometheus_client import Counter

agent_wake_total = Counter(
    'agent_wake_total',
    'Total agent wake attempts',
    labelnames=['status'],
)

# On success
agent_wake_total.labels(status='success').inc()

# On failure
agent_wake_total.labels(status='failure').inc()
```

**Alert Rule:**
```yaml
- alert: AgentWakeFailureRateHigh
  expr: |
    (
      rate(agent_wake_total{status="failure"}[5m]) /
      rate(agent_wake_total[5m])
    ) > 0.10
  for: 5m
  labels:
    severity: sev-1
  annotations:
    summary: "Agent wake failure rate > 10%"
    runbook: "https://docs/runbooks/agent-wake-failure.md"
```

---

### 3. Broker Order Failure Rate

**What:** Percentage of broker order requests that fail (non-filled status).

**How to Measure:**
- Prometheus counter: `broker_order_total{broker="robinhood|ibkr", status="filled|rejected|timeout"}`.
- Source: `shared/broker_adapters/` (increment in each adapter's `place_order()`).

**Collection:**
```python
from prometheus_client import Counter

broker_order_total = Counter(
    'broker_order_total',
    'Total broker order attempts',
    labelnames=['broker', 'status'],
)

# On order result
broker_order_total.labels(broker='robinhood', status='filled').inc()
broker_order_total.labels(broker='robinhood', status='rejected').inc()
```

**Alert Rule:**
```yaml
- alert: BrokerOrderFailureRateHigh
  expr: |
    (
      rate(broker_order_total{status!="filled"}[5m]) /
      rate(broker_order_total[5m])
    ) > 0.05
  for: 5m
  labels:
    severity: sev-2
  annotations:
    summary: "Broker order failure rate > 5%"
    runbook: "https://docs/runbooks/broker-order-failure.md"
```

---

### 4. Signal-to-Trade Latency

**What:** Time from signal XADD to `agent_trades` INSERT.

**How to Measure:**
- Prometheus histogram: `signal_to_trade_latency_seconds`.
- Source: Pipeline worker (measure timestamp delta).

**Collection:**
```python
from prometheus_client import Histogram

signal_to_trade_latency = Histogram(
    'signal_to_trade_latency_seconds',
    'End-to-end signal processing latency',
    buckets=[0.1, 0.5, 1, 2, 5, 10],
)

# On trade insert
latency = (trade.entry_time - signal.timestamp).total_seconds()
signal_to_trade_latency.observe(latency)
```

**Alert Rule:**
```yaml
- alert: SignalToTradeLatencyHigh
  expr: histogram_quantile(0.95, signal_to_trade_latency_seconds) > 5
  for: 5m
  labels:
    severity: sev-3
  annotations:
    summary: "Signal-to-trade p95 latency > 5s"
    runbook: "https://docs/runbooks/trade-latency.md"
```

---

### 5. Circuit Breaker State

**What:** Time spent in OPEN state (broker unavailable).

**How to Measure:**
- Prometheus gauge: `circuit_breaker_state{broker="robinhood|ibkr", state="CLOSED|HALF_OPEN|OPEN"}`.
- Source: Circuit breaker implementation (update on state transition).

**Collection:**
```python
from prometheus_client import Gauge

circuit_breaker_state = Gauge(
    'circuit_breaker_state',
    'Circuit breaker current state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)',
    labelnames=['broker'],
)

# On state transition
if state == CircuitState.OPEN:
    circuit_breaker_state.labels(broker='robinhood').set(2)
```

**Alert Rule:**
```yaml
- alert: CircuitBreakerOpen
  expr: circuit_breaker_state{state="OPEN"} == 2
  for: 5m
  labels:
    severity: sev-2
  annotations:
    summary: "Circuit breaker OPEN for > 5 minutes"
    runbook: "https://docs/runbooks/circuit-breaker-open.md"
```

---

### 6. API Error Rate (5xx)

**What:** Percentage of HTTP requests returning 500-599 status codes.

**How to Measure:**
- Prometheus counter: `http_requests_total{status="5xx"}`.
- Source: FastAPI middleware (instrument all routes).

**Collection:**
```python
from prometheus_client import Counter

http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    labelnames=['method', 'endpoint', 'status'],
)

# In middleware
@app.middleware("http")
async def metrics_middleware(request, call_next):
    response = await call_next(request)
    status_class = f"{response.status_code // 100}xx"
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=status_class,
    ).inc()
    return response
```

**Alert Rule:**
```yaml
- alert: APIErrorRateHigh
  expr: |
    (
      rate(http_requests_total{status="5xx"}[5m]) /
      rate(http_requests_total[5m])
    ) > 0.01
  for: 5m
  labels:
    severity: sev-2
  annotations:
    summary: "API 5xx error rate > 1%"
    runbook: "https://docs/runbooks/api-errors.md"
```

---

### 7. DB Connection Pool Saturation

**What:** Percentage of DB connection pool in use.

**How to Measure:**
- Prometheus gauge: `db_pool_connections{state="in_use|idle"}`.
- Source: SQLAlchemy pool instrumentation.

**Collection:**
```python
from prometheus_client import Gauge

db_pool_connections = Gauge(
    'db_pool_connections',
    'DB connection pool state',
    labelnames=['state'],
)

# Periodic collection (every 10s)
def collect_pool_metrics():
    pool = engine.pool
    db_pool_connections.labels(state='in_use').set(pool.checkedout())
    db_pool_connections.labels(state='idle').set(pool.size() - pool.checkedout())
```

**Alert Rule:**
```yaml
- alert: DBPoolSaturationHigh
  expr: |
    (
      db_pool_connections{state="in_use"} /
      (db_pool_connections{state="in_use"} + db_pool_connections{state="idle"})
    ) > 0.95
  for: 2m
  labels:
    severity: sev-1
  annotations:
    summary: "DB connection pool > 95% saturated"
    runbook: "https://docs/runbooks/db-pool-saturation.md"
```

---

### 8. Redis Stream Lag

**What:** Time between message XADD and consumer XREAD.

**How to Measure:**
- Prometheus histogram: `redis_stream_lag_seconds{stream="stream:channel:*"}`.
- Source: Redis consumer (measure message timestamp vs read timestamp).

**Collection:**
```python
from prometheus_client import Histogram

redis_stream_lag = Histogram(
    'redis_stream_lag_seconds',
    'Redis stream consumer lag',
    labelnames=['stream'],
    buckets=[0.01, 0.1, 0.5, 1, 2, 5],
)

# On XREAD
for message in messages:
    lag = (time.time() - message.timestamp_ms / 1000.0)
    redis_stream_lag.labels(stream=stream_key).observe(lag)
```

**Alert Rule:**
```yaml
- alert: RedisStreamLagHigh
  expr: histogram_quantile(0.95, redis_stream_lag_seconds) > 5
  for: 5m
  labels:
    severity: sev-2
  annotations:
    summary: "Redis stream lag p95 > 5s"
    runbook: "https://docs/runbooks/redis-lag.md"
```

---

## Dashboards

### 1. Agent Wake Flow
**File:** `infra/observability/grafana/agent-wake-flow.json`  
**Panels:**
- Agent wake success rate (time series)
- Agent wake latency (histogram)
- Agent state distribution (pie chart: running, paused, error)
- Discord ingestion lag (time series)

**Status:** ✅ Already exists (Phase B.6)

### 2. Broker Adapter Health
**Panels:**
- Broker order success/failure rate (stacked bar chart)
- Circuit breaker state by broker (gauge: CLOSED/HALF_OPEN/OPEN)
- Order latency by broker (histogram)

**Status:** 🔨 Create in Phase E.8 implementation

### 3. Signal Pipeline
**Panels:**
- Signal-to-trade latency (p50/p95/p99 time series)
- Pipeline throughput (signals/sec)
- Enrichment + inference latency breakdown

**Status:** 🔨 Create in Phase E.8 implementation

### 4. API Health
**Panels:**
- Request rate by endpoint (top 10)
- Error rate (2xx/4xx/5xx stacked)
- Response time by endpoint (p95)

**Status:** 🔨 Create in Phase E.8 implementation

### 5. Database Health
**Panels:**
- Connection pool saturation (gauge)
- Query latency (p95)
- Active queries count

**Status:** 🔨 Create in Phase E.8 implementation

### 6. Redis Health
**Panels:**
- Stream lag by stream key
- Memory usage (MB)
- Commands/sec

**Status:** 🔨 Create in Phase E.8 implementation

---

## Runbooks

All runbooks stored in `docs/runbooks/`. See individual files for detailed troubleshooting steps.

| Runbook | Triggers | Owner |
|---------|----------|-------|
| [discord-lag.md](../runbooks/discord-lag.md) | Discord ingestion lag > 10s | DevOps |
| [agent-wake-failure.md](../runbooks/agent-wake-failure.md) | Agent wake failure rate > 10% | Eng |
| [broker-order-failure.md](../runbooks/broker-order-failure.md) | Broker order failure rate > 5% | Eng |
| [trade-latency.md](../runbooks/trade-latency.md) | Signal-to-trade p95 > 5s | Eng |
| [circuit-breaker-open.md](../runbooks/circuit-breaker-open.md) | Circuit breaker OPEN > 5min | DevOps |
| [api-errors.md](../runbooks/api-errors.md) | API 5xx rate > 1% | DevOps |
| [db-pool-saturation.md](../runbooks/db-pool-saturation.md) | DB pool > 95% | DBA |
| [redis-lag.md](../runbooks/redis-lag.md) | Redis stream lag > 5s | DevOps |

---

## Pre-Deployment Checklist

Before Stage 3 (Full Live Deployment), verify:

- [ ] All 8 metrics instrumented in code (Prometheus counters/gauges/histograms).
- [ ] Prometheus scraping configured (targets: phoenix-api, message-ingestion, pipeline-worker).
- [ ] All 8 alert rules deployed to Prometheus/Alertmanager.
- [ ] PagerDuty / Slack integration configured for Sev-1 and Sev-2 alerts.
- [ ] All 6 Grafana dashboards deployed and accessible.
- [ ] All 8 runbooks published and linked from this doc.
- [ ] On-call rotation defined (primary + secondary).
- [ ] Test alerts fired successfully (simulate each alert condition).

---

## Sign-Off

| Role | Name | Signature / Date |
|------|------|------------------|
| SRE Lead | | |
| Engineering Lead | | |
| DevOps | | |
| DBA | | |

---

**Document Version:** 1.0  
**Next Review:** Post-Stage 3 deployment (30-day retrospective)
