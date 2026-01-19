# PostgreSQL Performance Benchmark - Foundation

A comprehensive benchmarking framework for evaluating PostgreSQL performance with and without B-tree indexing under various OLTP workloads.

## Overview

This project implements a systematic approach to compare PostgreSQL tradeoffs between no indexing vs single-column B-tree indexing across variants of OLTP read/write workloads. The foundation includes:

- Docker-based environment with PostgreSQL 15, Prometheus, and Grafana
- Custom Python load generator with configurable workload patterns
- Comprehensive metrics collection and visualization
- Support for different read/write ratios and concurrency levels

## Prerequisites

- Docker with Compose V2 (Docker Desktop or Docker Engine 20.10+)
- At least 8GB RAM and 4 CPU cores available for Docker
- 20GB free disk space

## Quick Start

### 1. Setup the Environment

Run the setup script to initialize all services:

```bash
./setup.sh
```

This will:
- Pull required Docker images
- Start PostgreSQL, Prometheus, Grafana, and postgres_exporter
- Wait for services to be ready

### 2. Access Grafana

Open your browser and navigate to:
- **URL**: http://localhost:3000
- **Username**: admin
- **Password**: admin

The dashboard "PostgreSQL Performance Benchmark" will be automatically loaded.

### 3. Run Your First Test

Execute a benchmark test with the default configuration:

```bash
./run_test.sh
```

The default test runs with:
- 1,000,000 rows (~250MB, memory-resident)
- B-tree index enabled
- 90/10 read/write ratio
- 4 concurrent clients
- 5 minutes duration (1 minute warmup + 5 minutes measurement)

### 4. View Results

Results are exported to the `results/` directory:
- `*.json` - Summary statistics and configuration
- `*_summary.csv` - Per-operation summary statistics
- `*_detailed.csv` - All individual operation latencies

You can also view real-time metrics in Grafana while the test runs.

### 5. Cleanup

To stop and remove all containers and volumes:

```bash
./teardown.sh
```

**Note**: This preserves results in the `results/` directory.

## Configuration

### Modifying Test Parameters

Edit `load_generator/config/test_config.yaml` to customize:

```yaml
workload:
  dataset_size: 1000000           # Number of rows
  indexed: true                   # true = with index, false = no index
  read_write_ratio: [90, 10]      # [read %, write %]
  concurrency: 4                  # Number of concurrent clients
  duration_seconds: 300           # Measurement phase duration
  warmup_seconds: 60              # Warmup phase duration
  statement_timeout_ms: 2000      # Workload statement timeout
  lock_timeout_ms: 200            # Workload lock wait timeout

metrics:
  stream_detailed_csv: true       # Stream per-op latencies to disk
  max_latency_samples: 200000     # 0 = store all latencies (exact percentiles)
```

### Running Tests with Different Configurations

You can create multiple configuration files and run them:

```bash
cp load_generator/config/test_config.yaml load_generator/config/my_test.yaml
# Edit my_test.yaml...
./run_test.sh config/my_test.yaml
```

### Automating Matrix Runs

There are helper scripts under `scripts/` to generate the 30-config matrix, persist a run order, and execute it with resume support.

**1) Generate the 2×3×5 matrix configs**
```bash
python scripts/generate_configs.py
```

This copies `load_generator/config/test_config.yaml` and only overrides:
- `workload.indexed`
- `workload.read_write_ratio`
- `workload.concurrency`

All other fields (database, dataset size, timeouts, operation weights, metrics output) are inherited from the base config. Filenames follow the pattern `indexed|no_index_rw<read>_<write>_c<concurrency>.yaml` under `load_generator/config/generated/`.

**2) Generate a run order (with optional filters and block ordering)**
```bash
python scripts/generate_run_order.py \
  --indexed true,false \
  --read-write-ratios 90:10,50:50,10:90 \
  --concurrency 1,4,8,16,32 \
  --block-by indexed,read_write_ratio,concurrency \
  --output run_orders/run_order.json
```

**3) Execute the run order with state tracking**
```bash
python scripts/run_matrix.py --run-order run_orders/run_order.json
```

Notes:
- The run order file captures filters and ordering so you can rerun partial matrices later.
- A state file is written alongside the run order as `<run_order>.state.json` and is used to resume after interruption.
- Use `--start-index` to restart at a specific 0-based index, or `--dry-run` to preview commands.

## Architecture

### Components

1. **PostgreSQL 15**
   - Resource limits: 4 CPU cores, 8GB RAM
   - Custom tuning for benchmark workloads
   - pg_stat_statements extension enabled

2. **Load Generator (Python)**
   - Multi-threaded workload execution
   - Five operation types:
     - Point lookup: `SELECT * FROM test_table WHERE indexed_col = ?`
     - Range scan: `SELECT * FROM test_table WHERE indexed_col BETWEEN ? AND ? LIMIT 100`
     - Range + ORDER BY: `... ORDER BY indexed_col LIMIT 100`
     - INSERT: Insert new rows
     - UPDATE: Update payload field
   - Per-operation latency tracking
   - Prometheus metrics export

3. **Prometheus**
   - Metrics collection from load generator and PostgreSQL
   - 7-day retention period

4. **Grafana**
   - Pre-configured dashboard with key metrics:
     - P95 latency by operation type
     - Throughput (ops/sec)
     - PostgreSQL buffer hit ratio
     - Index vs sequential scans
     - Operation counts

5. **PostgreSQL Exporter**
   - Exports PostgreSQL internal metrics to Prometheus

### Directory Structure

```
db_readwrite/
├── docker-compose.yml           # Multi-container orchestration
├── .gitignore                   # Git ignore rules
├── PROPOSAL.md                  # Original project proposal
├── README.md                    # This file
├── setup.sh                     # Environment setup script
├── run_test.sh                  # Test execution script
├── teardown.sh                  # Cleanup script
├── postgres/
│   ├── postgresql.conf          # PostgreSQL tuning parameters
│   └── init.sql                 # Database initialization
├── prometheus/
│   └── prometheus.yml           # Prometheus configuration
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/         # Auto-configure Prometheus
│   │   └── dashboards/          # Auto-load dashboards
│   └── dashboards/
│       └── experiment-dashboard.json
├── load_generator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/
│   │   ├── main.py              # Entry point
│   │   ├── config.py            # Configuration loader
│   │   ├── database.py          # Database operations
│   │   ├── queries.py           # Query templates
│   │   ├── workload.py          # Workload execution
│   │   └── metrics.py           # Metrics collection
│   ├── config/
│   │   └── test_config.yaml     # Test configuration
│   └── README.md
├── scripts/
│   ├── generate_configs.py      # Create config matrix
│   ├── generate_run_order.py    # Filter + order configs into a run list
│   └── run_matrix.py            # Execute run order with resume support
└── results/                     # Test results (generated)
```

## Metrics

### Primary Metrics

- **P95 Latency**: 95th percentile latency per operation type (in milliseconds)
- **Throughput**: Operations per second
- If `metrics.max_latency_samples` is set, percentiles are computed from a sample.

### Supporting Metrics

- **Buffer Cache Hit Ratio**: Percentage of reads served from memory
- **Index vs Sequential Scans**: Rate of index scans vs full table scans
- **Operation Counts**: Total operations by type and status (success/error)
- **Active Connections**: Number of active database connections

## Workload Patterns

### Read Operations

1. **Point Lookup** (default weight: 50%)
   - Queries a single row by indexed_col value
   - Tests index efficiency for equality conditions

2. **Range Scan** (default weight: 30%)
   - Queries a range of rows with LIMIT
   - Tests index efficiency for range conditions

3. **Range + ORDER BY** (default weight: 20%)
   - Queries a range with sorting
   - Tests index efficiency for sorted range queries

### Write Operations

1. **INSERT** (default weight: 50%)
   - Inserts new rows
   - Tests index maintenance overhead on writes

2. **UPDATE** (default weight: 50%)
   - Updates payload field only (not indexed_col)
   - Tests write performance without index changes

## Testing Scenarios

### From the Proposal

The full experiment design includes:

**Factor A - Indexing** (2 levels):
- No index (PK only)
- B-tree index on indexed_col

**Factor B - Read/Write Ratio** (3 levels):
- 90/10 (read-heavy)
- 50/50 (balanced)
- 10/90 (write-heavy)

**Factor C - Concurrency** (5 levels):
- 1, 4, 8, 16, 32 clients

**Factor D - Dataset Size** (2 phases):
- Phase 1: Memory-resident (~0.25× RAM)
- Phase 2: Disk-resident (~2× RAM)

### Running Different Scenarios

**No Index Test:**
```yaml
# In test_config.yaml
workload:
  indexed: false
```

**Write-Heavy Test:**
```yaml
# In test_config.yaml
workload:
  read_write_ratio: [10, 90]
```

**High Concurrency Test:**
```yaml
# In test_config.yaml
workload:
  concurrency: 32
```

## Advanced Usage

### Running Without Data Load

If you want to run multiple tests on the same dataset:

```bash
docker compose run --rm load_generator python src/main.py \
    --config /app/config/test_config.yaml \
    --skip-data-load
```

### Skipping Warmup

For faster testing during development:

```bash
docker compose run --rm load_generator python src/main.py \
    --config /app/config/test_config.yaml \
    --skip-warmup
```

### Accessing PostgreSQL Directly

```bash
docker compose exec postgres psql -U postgres -d benchmark_db
```

Useful queries:
```sql
-- Check table size
SELECT pg_size_pretty(pg_total_relation_size('test_table'));

-- Check index usage
SELECT * FROM pg_stat_user_indexes WHERE relname = 'test_table';

-- View query statistics
SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
```

### Viewing Prometheus Metrics

Access Prometheus at http://localhost:9090

Example queries:
```promql
# P95 latency for point lookups
histogram_quantile(0.95, rate(operation_latency_seconds_bucket{operation_type="point_lookup"}[5m]))

# Total throughput
sum(rate(operations_total[1m]))
```

## Performance Tips

### For Faster Tests

- Reduce `duration_seconds` to 60-120 seconds
- Reduce `dataset_size` to 100,000-500,000 rows
- Set `warmup_seconds` to 0 for development

### For Production-Like Tests

- Increase `duration_seconds` to 600-1800 seconds (10-30 minutes)
- Use `dataset_size` of 16M+ rows for disk-resident tests
- Ensure proper warmup period (60-120 seconds)

## Next Steps

After running the foundation tests, you can:

1. **Run the Full Test Matrix**: Automate running all 30 configurations (2 indexing × 3 ratios × 5 concurrencies)
2. **Statistical Analysis**: Process results across multiple runs to calculate confidence intervals
3. **Visualization**: Create comparison plots of indexed vs non-indexed performance
4. **Reporting**: Generate executive summary with recommendations

## References

- [PostgreSQL 15 Documentation](https://www.postgresql.org/docs/15/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- Original proposal: See `PROPOSAL.md`

## License

This project is for educational and research purposes.
