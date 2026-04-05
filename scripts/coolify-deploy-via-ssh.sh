#!/bin/bash
# Deploy PhoenixTrade to Coolify VPS via SSH
# Usage: ./scripts/coolify-deploy-via-ssh.sh [host]
# Example: ./scripts/coolify-deploy-via-ssh.sh root@69.62.86.166

set -euo pipefail
HOST="${1:-root@69.62.86.166}"
APP_DIR="/data/coolify/applications/tsogksw8kg0kgkgoow048cgk"

echo "=== PhoenixTrade Coolify Deploy via SSH ==="
echo "Host: $HOST"
echo "App dir: $APP_DIR"
echo ""

echo "1. Pulling latest code on server..."
ssh "$HOST" "cd $APP_DIR && git pull origin main 2>/dev/null || echo 'Not a git repo — using compose directly'"

echo ""
echo "2. Pulling latest images..."
ssh "$HOST" "cd $APP_DIR && docker compose -f docker-compose.yaml pull 2>/dev/null || docker compose -f docker-compose.coolify.yml pull 2>/dev/null || echo 'Pull skipped (build from source)'"

echo ""
echo "3. Rebuilding and starting services..."
ssh "$HOST" "cd $APP_DIR && docker compose -f docker-compose.yaml up -d --build --remove-orphans 2>/dev/null || docker compose -f docker-compose.coolify.yml up -d --build --remove-orphans"

echo ""
echo "4. Waiting for services to start (30s)..."
sleep 30

echo ""
echo "5. Checking service health..."
ssh "$HOST" "cd $APP_DIR && docker compose -f docker-compose.yaml ps -a 2>/dev/null || docker compose -f docker-compose.coolify.yml ps -a"

echo ""
echo "6. Checking API health..."
ssh "$HOST" "curl -sf http://localhost:8011/health 2>/dev/null && echo ' API OK' || echo ' API not reachable yet (may still be starting)'"

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Domain: https://cashflowus.com"
echo "API: https://cashflowus.com/api/v2/"
echo ""
echo "To monitor logs:"
echo "  ssh $HOST 'cd $APP_DIR && docker compose logs -f --tail=100'"
