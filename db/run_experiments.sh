#!/bin/bash

# Database Performance Evaluation - Experiment Orchestration Script
# This script runs the complete experimental matrix systematically
# Supports automatic recovery from interruptions via state file

set -e  # Exit on error

# Configuration
CONFIGS=("no_index" "btree_index" "redis_cache")
TABLE_SIZES=(1000000 10000000)
CONCURRENCIES=(10 50 100 200 500)
REPLICATIONS=3
RESULTS_DIR="./results"
STATE_FILE="$RESULTS_DIR/experiment_state.txt"

# Command-line options
SKIP_VALIDATION=false
START_FROM=0
FORCE_RESHUFFLE=false

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-validation)
            SKIP_VALIDATION=true
            shift
            ;;
        --start-from)
            START_FROM="$2"
            shift 2
            ;;
        --force-reshuffle)
            FORCE_RESHUFFLE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-validation    Skip result validation on startup"
            echo "  --start-from N       Start from experiment number N (1-indexed)"
            echo "  --force-reshuffle    Force re-randomization of experiment order"
            echo "  --help               Show this help message"
            echo ""
            echo "Recovery:"
            echo "  The script automatically tracks completed experiments in:"
            echo "  $STATE_FILE"
            echo ""
            echo "  To reconstruct state from existing results, run:"
            echo "  ./validate_results.sh"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

# Graceful shutdown flag
SHUTDOWN_REQUESTED=false

# Signal handler for graceful shutdown
signal_handler() {
    echo ""
    echo ""
    echo -e "${YELLOW}======================================================================"
    echo "Shutdown signal received (Ctrl+C)"
    echo "======================================================================${NC}"
    echo "Finishing current experiment, then exiting..."
    echo "Progress has been saved to: $STATE_FILE"
    echo ""
    SHUTDOWN_REQUESTED=true
}

# Register signal handlers
trap signal_handler SIGINT SIGTERM

# Create results directory
mkdir -p "$RESULTS_DIR"

# Load completed experiments from state file
declare -A completed_experiments
if [ -f "$STATE_FILE" ] && [ "$SKIP_VALIDATION" = false ]; then
    echo -e "${BLUE}Loading previous state from: $STATE_FILE${NC}"
    while IFS='|' read -r config size conc rep status rest; do
        # Skip comments and empty lines
        [[ $config =~ ^#.*$ ]] && continue
        [[ -z $config ]] && continue

        if [ "$status" = "completed" ]; then
            key="$config|$size|$conc|$rep"
            completed_experiments[$key]=1
        fi
    done < "$STATE_FILE"

    completed_count=${#completed_experiments[@]}
    if [ $completed_count -gt 0 ]; then
        echo -e "${GREEN}✓ Found $completed_count completed experiments${NC}"
        echo ""
    fi
elif [ ! -f "$STATE_FILE" ]; then
    echo -e "${YELLOW}No state file found. Starting fresh run.${NC}"
    echo -e "${YELLOW}Tip: Run ./validate_results.sh to reconstruct state from existing results.${NC}"
    echo ""
fi

echo "======================================================================"
echo "Database Performance Evaluation - Full Experimental Run"
echo "======================================================================"
echo "Configurations: ${CONFIGS[*]}"
echo "Table sizes: ${TABLE_SIZES[*]}"
echo "Concurrency levels: ${CONCURRENCIES[*]}"
echo "Replications: $REPLICATIONS"
echo ""

# Build experiment list (filter out completed ones)
experiments=()
pending_experiments=()
for config in "${CONFIGS[@]}"; do
    for size in "${TABLE_SIZES[@]}"; do
        for conc in "${CONCURRENCIES[@]}"; do
            for rep in $(seq 1 $REPLICATIONS); do
                exp_key="$config|$size|$conc|$rep"
                experiments+=("$exp_key")

                # Check if already completed
                if [ "${completed_experiments[$exp_key]:-0}" -eq 0 ]; then
                    pending_experiments+=("$exp_key")
                fi
            done
        done
    done
done

total_experiments=${#experiments[@]}
pending_count=${#pending_experiments[@]}
completed_count=$((total_experiments - pending_count))

echo "Total experiments: $total_experiments"
echo -e "Completed: ${GREEN}$completed_count${NC}"
echo -e "Pending: ${YELLOW}$pending_count${NC}"

if [ $pending_count -eq 0 ]; then
    echo ""
    echo -e "${GREEN}======================================================================"
    echo "All experiments already completed!"
    echo "======================================================================${NC}"
    echo ""
    echo "To re-run experiments:"
    echo "  1. Delete or rename: $STATE_FILE"
    echo "  2. Run this script again"
    exit 0
fi

echo "Estimated time: ~$((pending_count * 8)) minutes"
echo ""

# Randomize experiment order to avoid time-based confounding
# Use a seed file to maintain order across restarts unless forced
SHUFFLE_SEED_FILE="$RESULTS_DIR/.experiment_order"

if [ -f "$SHUFFLE_SEED_FILE" ] && [ "$FORCE_RESHUFFLE" = false ]; then
    echo "Using existing randomized order from: $SHUFFLE_SEED_FILE"
    shuffled_experiments=()
    while IFS= read -r line; do
        # Only include experiments that are still pending
        if [ "${completed_experiments[$line]:-0}" -eq 0 ]; then
            shuffled_experiments+=("$line")
        fi
    done < "$SHUFFLE_SEED_FILE"
else
    echo "Randomizing experiment order..."
    shuffled_experiments=($(printf '%s\n' "${pending_experiments[@]}" | shuf))

    # Save order for potential restarts
    printf '%s\n' "${shuffled_experiments[@]}" > "$SHUFFLE_SEED_FILE"
fi
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

    # Save state after successful completion
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local latest_result=$(ls -t "$RESULTS_DIR/${config}_${size}_${conc}_"*.csv 2>/dev/null | head -1 || echo "")

    if [ -n "$latest_result" ]; then
        local filename=$(basename "$latest_result")
        local rows=$(tail -n +2 "$latest_result" | wc -l | tr -d ' ')
        echo "$config|$size|$conc|$rep|completed|$filename|$rows|$timestamp" >> "$STATE_FILE"
        echo -e "${GREEN}✓ Experiment $exp_num/$pending_count completed and saved to state${NC}"
    else
        echo -e "${YELLOW}⚠ Experiment completed but result file not found${NC}"
    fi
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

    # Support --start-from flag
    if [ $START_FROM -gt 0 ] && [ $experiment_count -lt $START_FROM ]; then
        echo "Skipping experiment $experiment_count (--start-from $START_FROM)"
        continue
    fi

    # Check for shutdown request
    if [ "$SHUTDOWN_REQUESTED" = true ]; then
        echo ""
        echo -e "${YELLOW}======================================================================"
        echo "Graceful shutdown in progress"
        echo "======================================================================${NC}"
        echo "Experiments completed: $((experiment_count - 1)) / $pending_count"
        echo "State saved to: $STATE_FILE"
        echo ""
        echo "To resume, simply run this script again:"
        echo "  ./run_experiments.sh"
        echo "======================================================================"
        break
    fi

    run_experiment "$config" "$size" "$conc" "$rep" "$experiment_count"
done

# Cleanup
if [ "$SHUTDOWN_REQUESTED" = false ]; then
    echo "Stopping all services..."
    docker compose down
fi

# Calculate total time
end_time=$(date +%s)
duration=$((end_time - start_time))
hours=$((duration / 3600))
minutes=$(((duration % 3600) / 60))

echo ""
if [ "$SHUTDOWN_REQUESTED" = false ]; then
    echo "======================================================================"
    echo -e "${GREEN}All experiments completed successfully!${NC}"
    echo "======================================================================"
    echo "Total experiments: $total_experiments"
    echo "Completed in this run: $experiment_count"
    echo "Total time: ${hours}h ${minutes}m"
    echo "Results directory: $RESULTS_DIR"
    echo "State file: $STATE_FILE"
    echo ""
    echo "Next steps:"
    echo "  1. Analyze results: jupyter notebook analysis.ipynb"
    echo "  2. View monitoring: http://localhost:3000 (Grafana)"
    echo "======================================================================"
else
    echo "======================================================================"
    echo -e "${YELLOW}Experiment run interrupted${NC}"
    echo "======================================================================"
    echo "Completed in this session: $((experiment_count - 1)) experiments"
    echo "Time elapsed: ${hours}h ${minutes}m"
    echo "State file: $STATE_FILE"
    echo ""
    echo "To resume:"
    echo "  ./run_experiments.sh"
    echo ""
    echo "To check progress:"
    echo "  ./validate_results.sh"
    echo "======================================================================"
fi
