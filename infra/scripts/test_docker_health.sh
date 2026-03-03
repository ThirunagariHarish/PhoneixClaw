#!/usr/bin/env bash
# M1.1: Health check for Postgres, Redis (and optionally MinIO).
# Usage: ./infra/scripts/test_docker_health.sh
# Requires: docker compose -f docker-compose.dev.yml up -d (or infra/docker/docker-compose.infra.yml)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

ok() { echo -e "${GREEN}OK${NC} $1"; }
fail() { echo -e "${RED}FAIL${NC} $1"; exit 1; }

# Postgres
if command -v pg_isready &>/dev/null; then
  pg_isready -h localhost -p 5432 -U phoenixtrader &>/dev/null && ok "Postgres" || fail "Postgres not ready"
else
  docker exec postgres pg_isready -U phoenixtrader &>/dev/null && ok "Postgres" || \
  docker exec phoenix-postgres pg_isready -U phoenixtrader &>/dev/null && ok "Postgres" || fail "Postgres not ready"
fi

# Redis
if command -v redis-cli &>/dev/null; then
  redis-cli -h localhost -p 6379 ping | grep -q PONG && ok "Redis" || fail "Redis not ready"
else
  docker exec redis redis-cli ping 2>/dev/null | grep -q PONG && ok "Redis" || \
  docker exec phoenix-redis redis-cli ping 2>/dev/null | grep -q PONG && ok "Redis" || fail "Redis not ready"
fi

echo ""
echo "Infrastructure health check passed."
