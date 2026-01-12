#!/bin/bash

# Database Performance Evaluation - Single Test Runner
# Usage: ./run_single_test.sh [config] [table_size] [concurrency]

set -e  # Exit on error

# Parse arguments with defaults
CONFIG=${1:-no_index}
TABLE_SIZE=${2:-1000000}
CONCURRENCY=${3:-10}

# Validate configuration
if [[ ! "$CONFIG" =~ ^(no_index|btree_index|redis_cache)$ ]]; then
    echo "Error: Invalid config '$CONFIG'"
    echo "Usage: $0 [config] [table_size] [concurrency]"
    echo "  config: no_index | btree_index | redis_cache"
    echo "  table_size: 1000000 | 10000000"
    echo "  concurrency: positive integer"
    exit 1
fi

echo "======================================================================"
echo "Database Performance Evaluation - Single Test"
echo "======================================================================"
echo "Configuration: $CONFIG"
echo "Table size: $TABLE_SIZE rows"
echo "Concurrency: $CONCURRENCY"
echo ""

# Ensure results directory exists
mkdir -p ./results

# Check if services are running
if ! docker compose ps | grep -q "db-postgres.*Up"; then
    echo "Starting services..."
    docker compose up -d postgres redis
    echo "Waiting for services to be healthy (30 seconds)..."
    sleep 30
fi

# Check if data exists
if [ ! -f "./results/.data_generated_$TABLE_SIZE" ]; then
    echo "Data not found. Generating $TABLE_SIZE rows..."
    docker compose run --rm loadgen python /app/generate_data.py --table-size $TABLE_SIZE --seed 42
    touch "./results/.data_generated_$TABLE_SIZE"
fi

# Setup configuration
echo "Setting up configuration: $CONFIG..."
docker compose run --rm loadgen python /app/setup_config.py --config $CONFIG

# Start monitoring (if not already running)
echo "Starting monitoring services..."
docker compose up -d prometheus grafana cadvisor postgres-exporter redis-exporter

# Run test
echo "Running load test..."
export TEST_CONFIG=$CONFIG
export TABLE_SIZE=$TABLE_SIZE
export CONCURRENCY=$CONCURRENCY

docker compose run --rm loadgen python /app/load_test.py

echo ""
echo "======================================================================"
echo "Test completed!"
echo "======================================================================"
echo "Check results in: ./results/"
echo "View monitoring: http://localhost:3000 (Grafana)"
echo "======================================================================"
