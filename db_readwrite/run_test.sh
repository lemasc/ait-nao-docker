#!/bin/bash
set -e

# Default config file
CONFIG_FILE="${1:-config/test_config.yaml}"

echo "================================"
echo "PostgreSQL Benchmark Test Run"
echo "================================"
echo ""
echo "Configuration: $CONFIG_FILE"
echo ""

# Check if config file exists
if [ ! -f "load_generator/$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: load_generator/$CONFIG_FILE"
    exit 1
fi

# Run the test as a service so Prometheus can scrape it via service alias
echo ""
echo "Starting benchmark test..."
echo "Press Ctrl+C to stop the test"
echo ""

docker compose run --rm \
    -e PYTHONUNBUFFERED=1 \
    --name load_generator \
    load_generator \
    python -m src.main --config /app/$CONFIG_FILE

echo ""
echo "================================"
echo "Test completed!"
echo "================================"
echo ""
echo "Results are available in the ./results directory"
echo "View metrics in Grafana: http://localhost:3000"
echo ""
