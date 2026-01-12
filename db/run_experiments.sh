#!/bin/bash

# Database Performance Evaluation - Experiment Orchestration Script
# This script runs the complete experimental matrix systematically

set -e  # Exit on error

# Configuration
CONFIGS=("no_index" "btree_index" "redis_cache")
TABLE_SIZES=(1000000 10000000)
CONCURRENCIES=(10 50 100 200 500)
REPLICATIONS=3
RESULTS_DIR="./results"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

# Create results directory
mkdir -p "$RESULTS_DIR"

echo "======================================================================"
echo "Database Performance Evaluation - Full Experimental Run"
echo "======================================================================"
echo "Configurations: ${CONFIGS[*]}"
echo "Table sizes: ${TABLE_SIZES[*]}"
echo "Concurrency levels: ${CONCURRENCIES[*]}"
echo "Replications: $REPLICATIONS"
echo ""

# Build experiment list
experiments=()
for config in "${CONFIGS[@]}"; do
    for size in "${TABLE_SIZES[@]}"; do
        for conc in "${CONCURRENCIES[@]}"; do
            for rep in $(seq 1 $REPLICATIONS); do
                experiments+=("$config|$size|$conc|$rep")
            done
        done
    done
done

total_experiments=${#experiments[@]}
echo "Total experiments: $total_experiments"
echo "Estimated time: ~$((total_experiments * 8)) minutes"
echo ""

# Randomize experiment order to avoid time-based confounding
echo "Randomizing experiment order..."
shuffled_experiments=($(printf '%s\n' "${experiments[@]}" | shuf))
echo ""

# Function to run single experiment
run_experiment() {
    local config=$1
    local size=$2
    local conc=$3
    local rep=$4
    local exp_num=$5

    echo "======================================================================"
    echo -e "${GREEN}Experiment $exp_num/$total_experiments${NC}"
    echo "Config: $config | Table: $size rows | Concurrency: $conc | Replication: $rep"
    echo "======================================================================"

    # Reset environment
    echo "Resetting Docker environment..."
    docker compose down -v postgres postgres redis > /dev/null 2>&1 || true
    sleep 2

    # Start core services
    echo "Starting PostgreSQL and Redis..."
    docker compose up -d postgres redis
    echo "Waiting for services to be healthy (30 seconds)..."
    sleep 30

    # Generate data if needed (only once per table size)
    if [ ! -f "$RESULTS_DIR/.data_generated_$size" ]; then
        echo -e "${YELLOW}Generating $size rows of data...${NC}"
        docker compose run --rm loadgen python /app/generate_data.py --table-size $size --seed 42
        touch "$RESULTS_DIR/.data_generated_$size"
        echo "Data generation complete."
    else
        echo "Data already generated for table size $size (skipping)."
    fi

    # Setup configuration (indexes, cache)
    echo "Setting up configuration: $config..."
    docker compose run --rm loadgen python /app/setup_config.py --config $config

    # Start monitoring stack
    echo "Starting monitoring services..."
    docker compose up -d prometheus grafana cadvisor postgres-exporter redis-exporter
    sleep 5

    # Run load test
    echo "Running load test..."
    export TEST_CONFIG=$config
    export TABLE_SIZE=$size
    export CONCURRENCY=$conc
    export WORKLOAD_SEED=$((42 + rep))  # Different seed per replication

    docker compose run --rm loadgen python /app/load_test.py

    echo -e "${GREEN}✓ Experiment $exp_num/$total_experiments completed${NC}"
    echo ""

    # Brief pause between experiments
    sleep 5
}

# Main execution loop
start_time=$(date +%s)
experiment_count=0

for exp in "${shuffled_experiments[@]}"; do
    IFS='|' read -r config size conc rep <<< "$exp"
    ((++experiment_count))

    run_experiment "$config" "$size" "$conc" "$rep" "$experiment_count"
done

# Cleanup
echo "Stopping all services..."
docker compose down

# Calculate total time
end_time=$(date +%s)
duration=$((end_time - start_time))
hours=$((duration / 3600))
minutes=$(((duration % 3600) / 60))

echo ""
echo "======================================================================"
echo -e "${GREEN}All experiments completed successfully!${NC}"
echo "======================================================================"
echo "Total experiments: $total_experiments"
echo "Total time: ${hours}h ${minutes}m"
echo "Results directory: $RESULTS_DIR"
echo ""
echo "Next steps:"
echo "  1. Analyze results: jupyter notebook analysis.ipynb"
echo "  2. View monitoring: http://localhost:3000 (Grafana)"
echo "======================================================================"
