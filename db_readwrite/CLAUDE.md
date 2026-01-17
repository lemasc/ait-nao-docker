# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a PostgreSQL performance benchmarking framework designed to evaluate B-tree indexing tradeoffs across various OLTP workloads. The system uses Docker Compose to orchestrate PostgreSQL, Prometheus, Grafana, and a custom Python load generator.

## Common Commands

### Environment Management
```bash
# Setup entire stack (PostgreSQL, Prometheus, Grafana)
./setup.sh

# Run benchmark test with default config
./run_test.sh

# Run test with custom config
./run_test.sh config/my_test.yaml

# Teardown stack and cleanup
./teardown.sh
```

### Running Tests Manually
```bash
# Run with data loading (default)
docker compose run --rm load_generator python -m src.main --config /app/config/test_config.yaml

# Skip data loading (reuse existing data)
docker compose run --rm load_generator python -m src.main --config /app/config/test_config.yaml --skip-data-load

# Skip warmup phase (for development)
docker compose run --rm load_generator python -m src.main --config /app/config/test_config.yaml --skip-warmup
```

### Database Access
```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U postgres -d benchmark_db

# Useful queries inside psql:
# - SELECT pg_size_pretty(pg_total_relation_size('test_table'));
# - SELECT * FROM pg_stat_user_indexes WHERE relname = 'test_table';
# - SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
```

### Monitoring
- Grafana: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090
- Load generator metrics: http://localhost:8000
- cAdvisor (container metrics): http://localhost:8080

## Architecture

### Component Interaction Flow

1. **Load Generator** (Python): Multi-threaded workload executor
   - Manages connection pool to PostgreSQL
   - Executes 5 operation types based on configured probabilities
   - Records per-operation latencies and exports to Prometheus
   - Streams detailed latency data to CSV files

2. **PostgreSQL 15**: Benchmark target database
   - Custom tuning: 2GB shared_buffers, 6GB effective_cache_size
   - Resource limits: 4 CPUs, 8GB RAM
   - Extensions: pg_stat_statements for query analysis

3. **Metrics Pipeline**: Load Generator → Prometheus → Grafana
   - Prometheus scrapes metrics from load generator (port 8000), postgres_exporter, and cAdvisor
   - Grafana visualizes P95 latency, throughput, buffer hit ratio, and operation counts

4. **cAdvisor**: Container resource monitoring
   - Tracks CPU, memory, network, and disk I/O for all containers
   - Provides visibility into resource consumption during benchmarks

### Database Schema

```sql
CREATE TABLE test_table (
    id BIGSERIAL PRIMARY KEY,
    indexed_col INTEGER NOT NULL,  -- Target column for indexing
    payload TEXT,                   -- 1KB default, for realistic row size
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_test_table_indexed_col ON test_table (indexed_col);  -- Optional
```

The `indexed_col` is distributed across `[0, dataset_size * 2)` to simulate realistic data distribution.

### Operation Types

**Read Operations** (weighted by config):
1. `point_lookup` (50%): `SELECT * FROM test_table WHERE indexed_col = ?`
2. `range_scan` (30%): `SELECT * FROM test_table WHERE indexed_col BETWEEN ? AND ? LIMIT 100`
3. `range_order` (20%): Same as range_scan with `ORDER BY indexed_col`

**Write Operations** (weighted by config):
1. `insert` (50%): Insert new row with random indexed_col value
2. `update` (50%): Update payload field only (no index update)

Operation selection uses a two-stage weighted random process:
- First, choose read vs write based on `read_write_ratio`
- Then, select specific operation within that category based on operation weights

### Configuration System

Configuration lives in `load_generator/config/test_config.yaml` with three sections:

**database**: Connection parameters and pool size
**workload**: Core test parameters
- `dataset_size`: Number of rows (1M = ~250MB memory-resident, 16M+ = disk-resident)
- `indexed`: true/false to control B-tree index presence
- `read_write_ratio`: [read%, write%] must sum to 100
- `concurrency`: Number of concurrent client threads
- `duration_seconds`: Measurement phase duration
- `warmup_seconds`: Warmup phase to prime caches
- `statement_timeout_ms` / `lock_timeout_ms`: Per-workload-connection timeouts

**metrics**: Output and collection settings
- `stream_detailed_csv`: Whether to write per-operation latencies to disk
- `max_latency_samples`: Reservoir sample size (0 = exact percentiles, stores all)

### Python Module Structure

**main.py**: Entry point orchestrating the full test lifecycle
1. Load config → setup schema → load data → create/skip index
2. Run warmup phase (no metrics collected)
3. Run measurement phase (collect all metrics)
4. Export results to JSON + CSV

**workload.py**: Multi-threaded workload execution
- `WorkloadExecutor`: Manages thread pool, operation selection, and timing
- `_worker_thread`: Each worker gets dedicated DB connection with timeouts set
- Uses `threading.Event` for graceful shutdown

**database.py**: PostgreSQL connection and schema management
- Uses `psycopg` v3 with `psycopg_pool.ConnectionPool`
- Connection pool auto-resizes to match concurrency level
- `setup_schema()`: Creates table (optionally drops existing)
- `load_data()`: Batch inserts with random indexed_col distribution
- `create_index()` / `drop_index()`: Manage B-tree index

**queries.py**: Query templates and execution
- `QueryExecutor`: Stateful executor holding data ranges and parameters
- Each `execute_*` method: Returns `(latency_seconds, success, error_type)` tuple
- Uses `time.perf_counter()` for high-resolution latency measurement
- Handles transaction commit/rollback for writes
- Tracks error types: timeout, lock_timeout, other database errors

**metrics.py**: Prometheus metrics and result export
- Prometheus histograms for latency (with configurable buckets)
- Counters for operation counts by type, status, and error type
- Throughput gauges per operation type
- Exports to JSON (summary stats) and CSV (per-operation data)
- Implements reservoir sampling when `max_latency_samples` > 0

**config.py**: Configuration loading and validation
- Validates that all weight distributions sum to 100
- Provides CLI argument parsing (`--skip-warmup`, `--skip-data-load`)

## Results Output

After each test, results are written to `./results/`:
- `{indexed}_{ratio}_{concurrency}_{duration}.json`: Summary statistics and config
- `*_summary.csv`: Per-operation-type summary statistics
- `*_detailed.csv`: All individual operation latencies (if `stream_detailed_csv: true`)

## Matrix Automation Scripts

The `scripts/` directory contains tools for automating the full 2×3×5 experiment matrix:

### Generating Config Files
```bash
python scripts/generate_configs.py
```
Creates 30 config files in `load_generator/config/generated/` by varying:
- `indexed`: true/false (2 levels)
- `read_write_ratio`: 90:10, 50:50, 10:90 (3 levels)
- `concurrency`: 1, 4, 8, 16, 32 (5 levels)

Files are named: `{indexed|no_index}_rw{read}_{write}_c{concurrency}.yaml`

### Creating Run Orders
```bash
python scripts/generate_run_order.py \
  --indexed true,false \
  --read-write-ratios 90:10,50:50,10:90 \
  --concurrency 1,4,8,16,32 \
  --block-by indexed,read_write_ratio,concurrency \
  --output run_orders/run_order.json
```
Generates a filtered and ordered list of configs to execute. The `--block-by` parameter controls execution order (e.g., run all concurrency levels for each ratio before moving to the next).

### Executing Matrix Runs
```bash
python scripts/run_matrix.py --run-order run_orders/run_order.json
```
Key features:
- **State tracking**: Creates `<run_order>.state.json` to track completed tests
- **Auto-resume**: Restarts from last incomplete test after interruption
- **Smart data loading**: Automatically skips data load if dataset size hasn't changed
- **Manual restart**: Use `--start-index N` to restart at specific position
- **Dry run**: Use `--dry-run` to preview commands without execution

The script checks existing row count before each test and reuses data when possible to save time.

## Development Notes

### Adding New Operation Types

1. Add new operation type to `OperationType` literal in `queries.py`
2. Implement `execute_<operation>()` method in `QueryExecutor` class
3. Add weight configuration in `test_config.yaml` under `read_operations` or `write_operations`
4. Update weight validation in `config.py`

### Modifying PostgreSQL Configuration

Edit `postgres/postgresql.conf` and restart:
```bash
docker compose restart postgres
```

Key parameters for tuning:
- `shared_buffers`: Affects memory-resident dataset threshold
- `work_mem`: Affects sort and hash operations in queries
- `random_page_cost`: Lower for SSD (1.1) vs HDD (4.0)

### Understanding Timeouts

- **Workload connections**: Set `statement_timeout_ms` and `lock_timeout_ms` to prevent operations from hanging indefinitely under contention
- **Data loading / index creation**: Use unbounded timeouts (not applied during prep phase)
- If you see timeout errors in results, increase these values in config

### Connection Pooling

The pool size is automatically adjusted to match concurrency level if the configured `pool_size` is too small. Each worker thread acquires a dedicated connection for its entire lifetime to minimize connection overhead.

### Warmup Phase Importance

The warmup phase primes PostgreSQL's buffer cache and ensures stable measurements. Skipping warmup (`--skip-warmup`) is only recommended for:
- Development/debugging
- Memory-resident datasets where caching is less critical
- Follow-up tests on the same data without restart

## Troubleshooting

### High Timeout Rates
If you see many timeout errors in results:
- Increase `statement_timeout_ms` in config (currently defaults to 30000ms)
- Reduce concurrency level to decrease lock contention
- Check PostgreSQL logs: `docker compose logs postgres`

### Data Loading Fails
If data loading is interrupted or fails:
- Check available disk space
- Verify PostgreSQL container has enough memory (8GB limit in docker-compose)
- Manually drop table and restart: `docker compose exec postgres psql -U postgres -d benchmark_db -c "DROP TABLE IF EXISTS test_table;"`

### Metrics Not Appearing in Grafana
- Verify Prometheus is scraping: http://localhost:9090/targets
- Check load generator is exposing metrics: http://localhost:8000
- Ensure test is running (not just warmup phase) for measurement metrics

### Container Resource Issues
- Monitor with cAdvisor: http://localhost:8080
- Check Docker resource limits in docker-compose.yml
- Ensure host has enough available resources (4 CPUs, 8GB RAM minimum)
