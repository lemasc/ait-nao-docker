#!/bin/bash

# Database Performance Evaluation - Experiment Orchestration Script
# This script runs the complete experimental matrix systematically
# Supports automatic recovery from interruptions via state file
#
# Optimization: Only performs full reset (down -v) when table size changes
# Between other experiments: restarts services keeping data for efficiency

set -e  # Exit on error

# Configuration
CONFIGS=("no_index" "btree_index" "redis_cache")
TABLE_SIZES=(1000000 10000000)
CONCURRENCIES=(10 50 100 200 250)
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

echo "Estimated time: ~$((pending_count * 6)) minutes (optimized with data reuse)"
echo ""

# Block randomization by table size to minimize data regenerations
# Randomizes within each table size block, then runs blocks sequentially
# This reduces data generations from ~49 to 6 (3 reps × 2 sizes)
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
    echo "Randomizing experiment order (block design by table size)..."

    # Separate experiments by table size
    experiments_by_size=()
    for size in "${TABLE_SIZES[@]}"; do
        size_experiments=()
        for exp in "${pending_experiments[@]}"; do
            IFS='|' read -r config exp_size conc rep <<< "$exp"
            if [ "$exp_size" = "$size" ]; then
                size_experiments+=("$exp")
            fi
        done

        # Randomize within this size block
        if [ ${#size_experiments[@]} -gt 0 ]; then
            shuffled_block=($(printf '%s\n' "${size_experiments[@]}" | shuf))
            experiments_by_size+=("${shuffled_block[@]}")
        fi
    done

    shuffled_experiments=("${experiments_by_size[@]}")

    # Save order for potential restarts
    printf '%s\n' "${shuffled_experiments[@]}" > "$SHUFFLE_SEED_FILE"
    echo "✓ Block randomization complete:"
    for size in "${TABLE_SIZES[@]}"; do
        count=$(printf '%s\n' "${shuffled_experiments[@]}" | grep -c "|$size|" || true)
        echo "  - ${size} rows: $count experiments"
    done
fi
echo ""

# Function to run single experiment
run_experiment() {
    local config=$1
    local size=$2
    local conc=$3
    local rep=$4
    local exp_num=$5
    local prev_size=$6

    echo "======================================================================"
    echo -e "${GREEN}Experiment $exp_num/$total_experiments${NC}"
    echo "Config: $config | Table: $size rows | Concurrency: $conc | Replication: $rep"
    echo "======================================================================"

    # Determine if we need full reset (only when table size changes)
    local need_full_reset=false
    if [ "$prev_size" != "$size" ] || [ -z "$prev_size" ]; then
        need_full_reset=true
        echo -e "${YELLOW}Table size change detected ($prev_size → $size): performing full reset${NC}"
    fi

    # Reset environment based on need
    if [ "$need_full_reset" = true ]; then
        echo "Performing full reset (removing volumes)..."
        docker compose down -v postgres redis > /dev/null 2>&1 || true
        sleep 2

        echo "Starting PostgreSQL and Redis..."
        docker compose up -d postgres redis
        echo "Waiting for services to be healthy (30 seconds)..."
        sleep 30
    else
        echo "Restarting services (keeping data for efficiency)..."
        docker compose restart postgres redis > /dev/null 2>&1 || true
        echo "Waiting for services to stabilize (10 seconds)..."
        sleep 10
    fi

    # Generate data if needed (check actual database state)
    local need_data=false

    if [ "$need_full_reset" = true ]; then
        # After full reset, database is empty - always need data
        need_data=true
    else
        # Quick restart - verify data actually exists in database
        local row_count=$(docker compose exec -T postgres psql -U testuser -d perftest -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ' || echo "0")
        if [ "$row_count" -lt "$size" ]; then
            echo -e "${YELLOW}⚠ Database has only $row_count rows (expected $size), regenerating data${NC}"
            need_data=true
        fi
    fi

    if [ "$need_data" = true ]; then
        echo -e "${YELLOW}Generating $size rows of data...${NC}"
        docker compose run --rm loadgen python /app/generate_data.py --table-size $size --seed 42
        echo "Data generation complete."
    else
        echo "Data already exists in database ($size rows, skipping generation)."
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

# Initialize previous_size from last completed experiment (for efficient resumption)
previous_size=""
if [ -f "$STATE_FILE" ]; then
    # Get the size from the last completed experiment
    last_completed=$(grep "|completed|" "$STATE_FILE" | tail -1)
    if [ -n "$last_completed" ]; then
        IFS='|' read -r _ last_size _ <<< "$last_completed"
        previous_size="$last_size"
        echo -e "${BLUE}Resuming from previous session. Last table size: $previous_size${NC}"
        echo ""
    fi
fi

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

    run_experiment "$config" "$size" "$conc" "$rep" "$experiment_count" "$previous_size"
    previous_size="$size"  # Update for next iteration
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
