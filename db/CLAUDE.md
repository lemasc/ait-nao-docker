# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a systematic database performance evaluation laboratory that compares PostgreSQL query performance across three configurations:
1. **no_index**: Baseline with primary key only
2. **btree_index**: B-tree indexes on email and created_at columns
3. **redis_cache**: B-tree indexes + Redis caching layer with 5-minute TTL

The project uses a rigorous 10-step performance evaluation methodology with full factorial experimental design (3 configs × 2 table sizes × 5 concurrency levels × 3 replications = 90 tests).

## Architecture

### System Components

**Database Layer (SUT):**
- PostgreSQL 15 (port 5433): 2 CPU, 4GB RAM
- Redis 7 (port 6380): 1 CPU, 2GB RAM with LRU eviction

**Load Generator:**
- Python 3.11 multi-threaded workload generator (ThreadPoolExecutor)
- Zipfian distribution (α=0.99) for hot data patterns
- Three query types: Q1 (80% by user_id), Q2 (15% by email), Q3 (5% range by created_at)

**Monitoring Stack:**
- Prometheus (port 9090) + Grafana (port 3000, admin/admin)
- postgres_exporter, redis_exporter, cAdvisor
- Per-second metrics collection to CSV

**Key Scripts:**
- `generate_data.py`: Creates test data with Zipfian distribution
- `setup_config.py`: Manages indexes and cache state per configuration
- `load_test.py`: Main load testing engine with ThreadPoolExecutor
- `run_single_test.sh`: Quick single test execution
- `run_experiments.sh`: Full 90-test orchestration with state tracking
- `analysis.ipynb`: Jupyter notebook for statistical analysis (ANOVA, Tukey HSD)

## Common Commands

### Running Tests

```bash
# Start infrastructure (PostgreSQL + Redis)
docker compose up -d postgres redis

# Generate test data (1M or 10M rows)
docker compose run --rm loadgen python /app/generate_data.py --table-size 1000000
docker compose run --rm loadgen python /app/generate_data.py --table-size 10000000

# Run a single test (for debugging or quick validation)
./run_single_test.sh <config> <table_size> <concurrency>
# Examples:
./run_single_test.sh no_index 1000000 10
./run_single_test.sh btree_index 1000000 100
./run_single_test.sh redis_cache 10000000 500

# Run full experimental suite (90 tests, ~12-16 hours)
./run_experiments.sh

# Resume interrupted experimental run (uses state file)
./run_experiments.sh

# Start from specific experiment number
./run_experiments.sh --start-from 45

# Force re-randomization of experiment order
./run_experiments.sh --force-reshuffle
```

### Data Analysis

```bash
# Launch Jupyter notebook for statistical analysis
jupyter notebook analysis.ipynb

# Access monitoring dashboards
# Grafana: http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
# cAdvisor: http://localhost:8082
```

### Configuration Management

```bash
# Setup specific configuration (creates/drops indexes, flushes cache)
docker compose run --rm loadgen python /app/setup_config.py --config no_index
docker compose run --rm loadgen python /app/setup_config.py --config btree_index
docker compose run --rm loadgen python /app/setup_config.py --config redis_cache
```

### Docker Operations

```bash
# View service logs
docker compose logs postgres
docker compose logs redis
docker compose logs loadgen

# Check service status
docker compose ps

# Stop all services
docker compose down

# Stop and remove all data (volumes)
docker compose down -v

# View real-time container resource usage
docker stats
```

### Database Access

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U testuser -d perftest

# Check table row count
docker compose exec postgres psql -U testuser -d perftest -c "SELECT COUNT(*) FROM users;"

# View query statistics
docker compose exec postgres psql -U testuser -d perftest -c "SELECT * FROM query_stats;"

# Check indexes
docker compose exec postgres psql -U testuser -d perftest -c "SELECT indexname FROM pg_indexes WHERE tablename = 'users';"

# Connect to Redis
docker compose exec redis redis-cli

# Check Redis keyspace
docker compose exec redis redis-cli DBSIZE
docker compose exec redis redis-cli INFO memory
```

### Cleanup

```bash
# Remove results and start fresh
rm -rf results/*.csv
rm -f results/experiment_state.txt
rm -f results/.experiment_order

# Clean Docker system
docker system prune -f
docker volume prune -f
```

## Architecture Details

### Workload Generation Flow

1. **Data Generation** (`generate_data.py`):
   - Uses Faker to generate realistic user data
   - Creates Zipfian distribution (α=0.99) with top 1% as hot users
   - Saves distribution to `results/hot_users.json` for load test consumption
   - Data verification via SQL query (`SELECT COUNT(*) FROM users`)

2. **Configuration Setup** (`setup_config.py`):
   - **no_index**: Drops all secondary indexes
   - **btree_index**: Creates indexes on email and created_at using CONCURRENTLY
   - **redis_cache**: Creates indexes + flushes Redis cache
   - Runs VACUUM ANALYZE to update PostgreSQL statistics
   - Verifies configuration before returning

3. **Load Testing** (`load_test.py`):
   - Creates PostgreSQL connection pool (size = max(concurrency, 100))
   - Creates Redis connection pool if caching enabled
   - Spawns worker threads using ThreadPoolExecutor
   - Each worker: selects query type → generates params → executes query → records metrics
   - **Cache logic**: Check Redis first (if enabled) → on miss, query PostgreSQL → store in cache
   - Metrics collected per-request, then aggregated to per-second buckets
   - Outputs CSV: timestamp, throughput_qps, response_time_p50/p95/p99, error_rate, cache_hit_rate

4. **Orchestration** (`run_experiments.sh`):
   - Builds experiment list (3 configs × 2 sizes × 5 concurrency × 3 replications)
   - Randomizes execution order to avoid time-based confounding
   - Saves order to `.experiment_order` for resumability
   - Tracks completion in `experiment_state.txt`
   - For each experiment: reset env → start services → generate data (if needed) → setup config → run test → save state
   - Supports graceful shutdown (SIGINT/SIGTERM) with state preservation

### Key Design Patterns

**State Management:**
- Data presence verified via SQL query to actual database (no flag files)
- `experiment_state.txt` tracks completed experiments for recovery
- `.experiment_order` preserves randomized sequence across restarts

**Connection Pooling:**
- PostgreSQL: ThreadedConnectionPool (min=5, max=max(concurrency, 100))
- Redis: ConnectionPool (max=max(concurrency, 50))
- Per-thread seed: `base_seed + worker_id` for reproducibility

**Metrics Pipeline:**
- Per-request: `{timestamp, query_type, response_time, success, cache_hit, is_warmup}`
- Aggregation: Group by second → compute percentiles, throughput, error rate
- Warmup filtering: First 60 seconds marked `is_warmup=True`, excluded from analysis

**Cache Key Format:**
- Q1: `user:id:<user_id>`
- Q2: `user:email:<email>`
- Q3: `users:range:<start_date>:<end_date>`
- TTL: 300 seconds (5 minutes)

### Database Schema

```sql
CREATE TABLE users (
    user_id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,
    status VARCHAR(20) DEFAULT 'active'
);

-- Indexes (managed by setup_config.py):
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created_at ON users(created_at);
```

**Tuning Parameters (init.sql):**
- shared_buffers = 1GB
- effective_cache_size = 3GB
- max_connections = 200
- statement_timeout = 5000ms
- random_page_cost = 1.1 (SSD optimized)

### Experimental Design Rationale

**Why 3 Replications?**
- Provides 95% confidence intervals for statistical testing
- Allows ANOVA and Tukey HSD for configuration comparisons

**Why Randomized Order?**
- Prevents time-based confounding (e.g., thermal throttling, disk wear)
- Distributes systematic errors evenly across configurations

**Why 60s Warmup + 300s Measurement?**
- Warmup: Fills OS cache, PostgreSQL buffers, Redis cache
- Measurement: Ensures steady-state data collection

**Why Zipfian α=0.99?**
- Models realistic workloads where small fraction of data is hot
- Makes Redis caching measurably effective (typically >70% hit rate)

## Results and Analysis

### Output Files

Results are saved to `results/` directory:
- CSV files: `{config}_{table_size}_{concurrency}_{timestamp}.csv`
- Each CSV contains per-second metrics (timestamp, throughput, latencies, error rate, cache hit rate)
- State tracking: `experiment_state.txt`, `.experiment_order`
- Distribution config: `hot_users.json`

### Key Metrics

**Performance:**
- Throughput (QPS): Queries per second
- Response time: p50, p95, p99 latency in milliseconds
- Error rate: Percentage of failed queries

**Cache Effectiveness (redis_cache only):**
- Cache hit rate: Percentage of requests served from Redis
- Expected: >70% with Zipfian distribution

**Statistical Tests (in analysis.ipynb):**
- ANOVA: Test configuration effect significance
- Tukey HSD: Pairwise configuration comparisons
- Little's Law validation: L = λ × W

### Expected Results Pattern

- **no_index**: Highest latency, lowest throughput (baseline)
- **btree_index**: Moderate improvement for Q2/Q3 (email, date range queries)
- **redis_cache**: Significant improvement for hot data (Q1), high cache hit rate

**Capacity curves** identify "knee points" where:
- Throughput plateaus despite increased concurrency
- p95 latency exceeds 500ms threshold

## Troubleshooting

### High Error Rates (>5%)

**Check:**
- Container resources: `docker stats`
- Query timeouts in PostgreSQL logs
- Connection pool exhaustion

**Fix:**
- Increase Docker CPU/memory limits in docker-compose.yml
- Adjust `max_connections` in init.sql
- Lower concurrency level

### Low Cache Hit Rate (<50%)

**Check:**
- Verify `hot_users.json` exists and has Zipfian probabilities
- Confirm Redis is running: `docker compose ps redis`
- Check Redis memory: `docker compose exec redis redis-cli INFO memory`

**Fix:**
- Regenerate data with correct Zipfian distribution
- Ensure Redis maxmemory not exceeded (1536MB limit)

### Data Generation Slow

**Expected:**
- 1M rows: 2-3 minutes
- 10M rows: 15-20 minutes

**Check:**
- PostgreSQL container resources
- Disk I/O performance

### Services Not Starting

**Check:**
- Port conflicts: `netstat -tulpn | grep -E '5433|6380|3000|9090'`
- Docker daemon: `systemctl status docker`

**Fix:**
- Stop conflicting services
- Change port mappings in docker-compose.yml
- Restart Docker: `systemctl restart docker`

## Development Workflow

When modifying this project:

1. **Test incrementally**: Use `run_single_test.sh` for quick validation before full runs
2. **State management**: If changing experiment logic, delete `experiment_state.txt` to start fresh
3. **Data regeneration**: Use `docker compose down -v` to force data regeneration (removes volumes)
4. **Docker rebuilds**: Use `docker compose build --no-cache loadgen` after Python code changes
5. **Statistical validation**: Always run analysis.ipynb to verify results integrity

## Important Notes

- Docker containers use fixed resource limits (see docker-compose.yml deploy.resources)
- PostgreSQL port 5433 (not 5432) to avoid conflicts with host installations
- Redis port 6380 (not 6379) for same reason
- All times are in UTC (container timezone)
- CSV timestamps are ISO 8601 format
- Query timeout is 5 seconds (configured in init.sql)
- Random seeds: data generation (42), workload (42 + replication_number)
