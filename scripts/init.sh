#!/usr/bin/env bash
set -euo pipefail

echo "=== Initializing Phoenix Trade Bot ==="

echo "Waiting for Kafka..."
until /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list > /dev/null 2>&1; do
  sleep 2
done

echo "Creating Kafka topics..."
for topic in raw-messages parsed-trades approved-trades execution-results exit-signals trade-events-raw config-updates agent-scores; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --topic "$topic" --partitions 6 --replication-factor 1 --if-not-exists
done

echo "Running database migrations..."
python -c "import asyncio; from shared.models.database import init_db; asyncio.run(init_db())"

echo "=== Initialization complete ==="
