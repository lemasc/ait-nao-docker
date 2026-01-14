#!/bin/bash

# Validation script to check experiment results and build state file
# This script can reconstruct the experiment state from existing CSV files

# Don't exit on error - we want to process all files even if some have issues
set +e

# Configuration (must match run_experiments.sh)
CONFIGS=("no_index" "btree_index" "redis_cache")
TABLE_SIZES=(1000000 10000000)
CONCURRENCIES=(10 50 100 200 250)
REPLICATIONS=3
RESULTS_DIR="./results"
STATE_FILE="$RESULTS_DIR/experiment_state.txt"

# Minimum expected rows for a valid result (warmup + test duration in seconds)
# 60s warmup + 300s test = 360 seconds, allow some tolerance
MIN_ROWS=340

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================================================"
echo "Experiment Results Validation & State Reconstruction"
echo "======================================================================"
echo ""

# Create results directory if it doesn't exist
mkdir -p "$RESULTS_DIR"

# Build expected experiments list
declare -A expected_experiments
for config in "${CONFIGS[@]}"; do
    for size in "${TABLE_SIZES[@]}"; do
        for conc in "${CONCURRENCIES[@]}"; do
            for rep in $(seq 1 $REPLICATIONS); do
                key="$config|$size|$conc|$rep"
                expected_experiments[$key]=0
            done
        done
    done
done

total_expected=${#expected_experiments[@]}
echo "Total expected experiments: $total_expected"
echo ""

# Validate a CSV file
validate_csv() {
    local file=$1

    # Check if file exists and is readable
    if [ ! -r "$file" ]; then
        echo "not_readable"
        return 0
    fi

    # Check file size (must be > 1KB for valid results)
    local size=0
    if stat -c%s "$file" >/dev/null 2>&1; then
        # GNU stat (Linux)
        size=$(stat -c%s "$file" 2>/dev/null)
    elif stat -f%z "$file" >/dev/null 2>&1; then
        # BSD stat (macOS)
        size=$(stat -f%z "$file" 2>/dev/null)
    else
        # Fallback: use wc
        size=$(wc -c < "$file" 2>/dev/null || echo 0)
    fi

    if [ "$size" -lt 1000 ]; then
        echo "too_small:$size"
        return 0
    fi

    # Count rows (excluding header)
    local rows=$(tail -n +2 "$file" 2>/dev/null | wc -l 2>/dev/null | tr -d ' ')
    rows=${rows:-0}

    # Check if we have enough data rows
    if [ "$rows" -lt "$MIN_ROWS" ]; then
        echo "incomplete:$rows"
        return 0
    fi

    # Check if CSV is parseable and has expected columns
    local header=$(head -n 1 "$file" 2>/dev/null)
    if ! echo "$header" | grep -q "timestamp.*throughput_qps.*response_time"; then
        echo "invalid_format"
        return 0
    fi

    echo "valid:$rows"
    return 0
}

# Scan results directory for experiment CSV files
echo "Scanning results directory: $RESULTS_DIR"
echo ""

completed_count=0
incomplete_count=0
invalid_count=0

declare -A found_experiments

# Backup existing state file if it exists
if [ -f "$STATE_FILE" ]; then
    echo -e "${YELLOW}Existing state file found, creating backup...${NC}"
    cp "$STATE_FILE" "$STATE_FILE.backup.$(date +%Y%m%d_%H%M%S)"
fi

# Create new state file
> "$STATE_FILE"
echo "# Experiment state file - auto-generated on $(date)" >> "$STATE_FILE"
echo "# Format: config|table_size|concurrency|replication|status|file|rows|timestamp" >> "$STATE_FILE"

# Process each result file
shopt -s nullglob  # Handle case where no CSV files exist
for file in "$RESULTS_DIR"/*.csv; do
    filename=$(basename "$file")

    # Parse filename: {config}_{size}_{concurrency}_{timestamp}.csv
    if [[ $filename =~ ^([a-z_]+)_([0-9]+)_([0-9]+)_([0-9_]+)\.csv$ ]]; then
        config="${BASH_REMATCH[1]}"
        size="${BASH_REMATCH[2]}"
        conc="${BASH_REMATCH[3]}"
        timestamp="${BASH_REMATCH[4]}"

        # Validate the file
        result=$(validate_csv "$file")
        status="${result%%:*}"
        rows="${result##*:}"

        if [ "$status" = "valid" ]; then
            # This is a valid result, but we need to figure out which replication it is
            # We'll count how many valid results we have for this config/size/conc combo
            combo_key="$config|$size|$conc"

            # Count existing valid results for this combination
            existing_count=0
            for rep in $(seq 1 $REPLICATIONS); do
                exp_key="$config|$size|$conc|$rep"
                if [ "${found_experiments[$exp_key]:-0}" -eq 1 ]; then
                    existing_count=$((existing_count + 1))
                fi
            done

            # Assign to next available replication slot
            rep=$((existing_count + 1))
            if [ $rep -le $REPLICATIONS ]; then
                exp_key="$config|$size|$conc|$rep"
                found_experiments[$exp_key]=1

                echo "$exp_key|completed|$filename|$rows|$timestamp" >> "$STATE_FILE" || true
                echo -e "${GREEN}✓${NC} $filename ($rows rows) -> [$config, ${size} rows, conc=$conc, rep=$rep]"
                completed_count=$((completed_count + 1))
            else
                echo -e "${YELLOW}⚠${NC} $filename ($rows rows) -> Extra result (all $REPLICATIONS replications done)"
            fi

        elif [ "$status" = "incomplete" ]; then
            echo -e "${YELLOW}⚠${NC} $filename -> Incomplete ($rows rows, expected >$MIN_ROWS)"
            incomplete_count=$((incomplete_count + 1))
        elif [ "$status" = "too_small" ]; then
            echo -e "${RED}✗${NC} $filename -> Too small (${rows} bytes, likely interrupted)"
            invalid_count=$((invalid_count + 1))
        else
            echo -e "${RED}✗${NC} $filename -> Invalid ($status)"
            invalid_count=$((invalid_count + 1))
        fi
    else
        # Not a result file (might be summary, etc.)
        continue
    fi
done
shopt -u nullglob

echo ""
echo "======================================================================"
echo "Validation Summary"
echo "======================================================================"
echo -e "Valid experiments:      ${GREEN}$completed_count${NC} / $total_expected"
echo -e "Incomplete/truncated:   ${YELLOW}$incomplete_count${NC}"
echo -e "Invalid files:          ${RED}$invalid_count${NC}"
echo ""

pending_count=$((total_expected - completed_count))
echo -e "Pending experiments:    ${YELLOW}$pending_count${NC}"

if [ $pending_count -gt 0 ]; then
    echo ""
    echo "Missing/Pending experiments:"
    for key in "${!expected_experiments[@]}"; do
        if [ "${found_experiments[$key]:-0}" -eq 0 ]; then
            IFS='|' read -r config size conc rep <<< "$key"
            echo "  - Config: $config, Size: $size, Concurrency: $conc, Rep: $rep"
        fi
    done | sort
fi

echo ""
echo "State file: $STATE_FILE"
if [ $completed_count -gt 0 ]; then
    echo -e "${GREEN}✓ State file updated with $completed_count completed experiments${NC}"
    echo ""
    echo "You can now run ./run_experiments.sh to continue from where you left off."
else
    echo -e "${YELLOW}No completed experiments found. State file is empty.${NC}"
fi
echo "======================================================================"
