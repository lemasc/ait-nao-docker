# Database Performance Evaluation - Execution Guide

This guide provides step-by-step instructions for running the database performance evaluation experiments.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Full Experimental Run](#full-experimental-run)
4. [Data Analysis](#data-analysis)
5. [Monitoring and Visualization](#monitoring-and-visualization)
6. [Troubleshooting](#troubleshooting)
7. [Configuration Reference](#configuration-reference)

---

## Prerequisites

### System Requirements

- **Operating System**: Linux, macOS, or Windows with WSL2
- **Docker**: Version 20.10+ with Compose V2
- **RAM**: Minimum 8GB available for containers
- **Disk**: 50GB+ free space (for data, containers, results)
- **CPU**: Multi-core processor recommended

### Software Installation

**Install Docker:**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker.io docker-compose-plugin

# macOS (using Homebrew)
brew install --cask docker

# Verify installation
docker --version
docker compose version
```

**Install Jupyter (for local analysis):**
```bash
pip install jupyter pandas numpy matplotlib seaborn scipy statsmodels
```

### Verify Setup

```bash
cd /home/lemasc/projects/nao-docker/db
ls -l

# You should see these files:
# docker-compose.yml, Dockerfile, requirements.txt, prometheus.yml, init.sql
# generate_data.py, setup_config.py, load_test.py
# run_experiments.sh, run_single_test.sh, analysis.ipynb
```

---

## Quick Start

### Run Your First Test (5 commands)

```bash
# 1. Navigate to project directory
cd /home/lemasc/projects/nao-docker/db

# 2. Start PostgreSQL and Redis
docker compose up -d postgres redis

# 3. Wait for services to be healthy (30 seconds)
sleep 30

# 4. Generate test data (1M rows, ~2-3 minutes)
docker compose run --rm loadgen python /app/generate_data.py --table-size 1000000

# 5. Run a single test (no_index, 1M rows, 10 concurrency)
./run_single_test.sh no_index 1000000 10
```

**Expected Output:**
- Data generation progress: `100,000 (XXX rows/sec) 200,000 ...`
- Load test execution: `Warmup phase: Xs / 60s`, `Test progress: Xs / 300s`
- Results saved to: `results/no_index_1000000_10_YYYYMMDD_HHMMSS.csv`

---

## Full Experimental Run

### Understanding the Experimental Matrix

**Total experiments**: 90 test runs
- 3 configurations (no_index, btree_index, redis_cache)
- 2 table sizes (1M, 10M rows)
- 5 concurrency levels (10, 50, 100, 200, 500)
- 3 replications per experiment

**Estimated time**: ~12-16 hours (8 minutes per test × 90 tests)

### Running All Experiments

```bash
# Make sure you're in the db/ directory
cd /home/lemasc/projects/nao-docker/db

# Make scripts executable (if not already)
chmod +x run_experiments.sh run_single_test.sh

# Run full experimental suite (runs in background)
nohup ./run_experiments.sh > experiment_run.log 2>&1 &

# Monitor progress
tail -f experiment_run.log

# Or run in foreground (recommended for first time)
./run_experiments.sh
```

### What Happens During Execution

**For each experiment:**
1. **Reset environment**: `docker compose down -v` (removes previous state)
2. **Start services**: PostgreSQL + Redis
3. **Generate data** (if not already generated for this table size)
4. **Setup configuration**: Create/drop indexes, flush cache
5. **Start monitoring**: Prometheus, Grafana, exporters
6. **Run load test**: 60s warmup + 300s measurement
7. **Save results**: CSV file with per-second metrics

### Monitoring Progress

```bash
# Check how many experiments completed
ls results/*.csv | wc -l

# View recent results
ls -lht results/*.csv | head

# Check experiment log
grep "Experiment.*completed" experiment_run.log
```

### Stopping Experiments Early

```bash
# Find the process
ps aux | grep run_experiments

# Kill gracefully (completes current experiment)
pkill -SIGTERM -f run_experiments.sh

# Force kill (not recommended)
pkill -SIGKILL -f run_experiments.sh

# Clean up Docker
docker compose down
```

---

## Data Analysis

### Launch Jupyter Notebook

```bash
# Start Jupyter from project directory
cd /home/lemasc/projects/nao-docker/db
jupyter notebook analysis.ipynb

# Jupyter will open in your browser at http://localhost:8888
```

### Running the Analysis

**In Jupyter:**

1. **Cell 1-5: Setup and Data Loading**
   - Run these cells first to load all CSV files
   - Verify data loaded correctly (check printed statistics)

2. **Cell 6-8: Descriptive Statistics**
   - Computes mean, std, CI for each experiment
   - Shows summary table and speedup calculations

3. **Cell 9-13: Statistical Tests**
   - ANOVA tests for configuration effect
   - Tukey HSD pairwise comparisons
   - Correlation analysis
   - Little's Law validation

4. **Cell 14-19: Visualizations**
   - Capacity curves (throughput vs concurrency)
   - Response time comparisons (bar charts)
   - Throughput heatmaps
   - Cache effectiveness scatter plots
   - Scalability analysis (log-log)

5. **Cell 20-22: Conclusions**
   - Key findings summary
   - Performance comparison table
   - Export results to CSV

**Generated Files** (in `results/` directory):
- `capacity_curve.png`
- `response_time_comparison.png`
- `throughput_heatmap.png`
- `cache_effectiveness.png`
- `scalability_analysis.png`
- `summary_statistics.csv`

### Interpreting Results

**Key Questions to Answer:**

1. **Which configuration performs best?**
   - Check capacity curves: highest throughput at each concurrency level
   - Compare p95 latency: lower is better

2. **When does Redis caching become worthwhile?**
   - Look at speedup vs concurrency
   - Check cache hit rates (should be >70% with Zipfian)

3. **Where are the knee points?**
   - Identify concurrency level where throughput plateaus
   - Note where p95 latency exceeds 500ms threshold

4. **Is the difference statistically significant?**
   - Check ANOVA p-values (significant if p < 0.05)
   - Review Tukey HSD results for pairwise comparisons

---

## Monitoring and Visualization

### Access Monitoring Dashboards

**Grafana** (Recommended):
```bash
# URL: http://localhost:3000
# Username: admin
# Password: admin

# Import dashboard for container monitoring
# Dashboard ID: 14282 (Docker Container Monitoring)
```

**Prometheus**:
```bash
# URL: http://localhost:9090
# Query examples:
#   - rate(pg_stat_database_xact_commit_total[1m])
#   - redis_keyspace_hits_total
#   - container_cpu_usage_seconds_total{name="db-postgres"}
```

**cAdvisor**:
```bash
# URL: http://localhost:8082
# Shows real-time container resource usage
```

### Useful Grafana Queries

**PostgreSQL Performance:**
```promql
# Query rate
rate(pg_stat_database_xact_commit_total[1m])

# Cache hit ratio
pg_statio_user_tables_heap_blks_hit / (pg_statio_user_tables_heap_blks_read + pg_statio_user_tables_heap_blks_hit)

# Active connections
pg_stat_database_numbackends
```

**Redis Performance:**
```promql
# Hit rate
rate(redis_keyspace_hits_total[1m]) / (rate(redis_keyspace_hits_total[1m]) + rate(redis_keyspace_misses_total[1m]))

# Memory usage
redis_memory_used_bytes

# Commands per second
rate(redis_commands_processed_total[1m])
```

**Container Resources:**
```promql
# CPU usage (%)
rate(container_cpu_usage_seconds_total{name=~"db-.*"}[1m]) * 100

# Memory usage (MB)
container_memory_usage_bytes{name=~"db-.*"} / 1024 / 1024
```

---

## Troubleshooting

### Services Won't Start

**Problem**: `docker compose up` fails

**Solutions**:
```bash
# Check Docker is running
sudo systemctl status docker

# Check port conflicts
sudo netstat -tulpn | grep -E '5433|6380|3000|9090'

# Remove old containers
docker compose down -v
docker system prune -f

# Restart Docker
sudo systemctl restart docker
```

### Data Generation is Slow

**Problem**: `generate_data.py` takes >10 minutes for 1M rows

**Expected Performance**:
- 1M rows: 2-3 minutes
- 10M rows: 15-20 minutes

**Check**:
```bash
# Monitor container resources
docker stats db-postgres

# Check database logs
docker compose logs postgres | tail -n 50
```

### High Error Rates During Tests

**Problem**: `error_rate_pct > 5%` in results

**Possible Causes**:
1. **Query timeouts**: Increase `statement_timeout` in init.sql
2. **Connection exhaustion**: Check `max_connections` setting
3. **Resource limits**: Increase Docker CPU/memory in docker-compose.yml

**Diagnose**:
```bash
# Check container resources
docker stats

# View load test logs
docker compose logs loadgen | grep "Error"

# Query PostgreSQL
docker compose exec postgres psql -U testuser -d perftest -c "SELECT count(*) FROM users;"
```

### Cache Hit Rate is Low (<50%)

**Problem**: Redis cache not effective

**Check**:
1. **Verify hot_users.json exists**: `ls -l results/hot_users.json`
2. **Check Zipfian distribution**: Look for top users in JSON
3. **Verify Redis is running**: `docker compose ps redis`

**Debug**:
```bash
# Check Redis keys
docker compose exec redis redis-cli DBSIZE

# Sample a few keys
docker compose exec redis redis-cli --scan --pattern "user:*" | head -n 10

# Check Redis memory
docker compose exec redis redis-cli INFO memory
```

### Out of Disk Space

**Problem**: Docker volumes consume all disk space

**Clean Up**:
```bash
# Remove old results
rm results/*.csv

# Remove data generation flags
rm results/.data_generated_*

# Stop and remove volumes
docker compose down -v

# Clean Docker system
docker system prune -a --volumes
```

### Jupyter Notebook Won't Start

**Problem**: Analysis notebook fails to load

**Solutions**:
```bash
# Install missing dependencies
pip install jupyter pandas numpy matplotlib seaborn scipy statsmodels

# Start from correct directory
cd /home/lemasc/projects/nao-docker/db
jupyter notebook analysis.ipynb

# If port 8888 is busy, use different port
jupyter notebook --port=8889 analysis.ipynb
```

---

## Configuration Reference

### Environment Variables

**Database Connection**:
- `DB_HOST`: PostgreSQL hostname (default: `postgres`)
- `DB_PORT`: PostgreSQL port (default: `5432`)
- `DB_NAME`: Database name (default: `perftest`)
- `DB_USER`: Database user (default: `testuser`)
- `DB_PASSWORD`: Database password (default: `testpass`)

**Redis Connection**:
- `REDIS_HOST`: Redis hostname (default: `redis`)
- `REDIS_PORT`: Redis port (default: `6379`)

**Test Configuration**:
- `TEST_CONFIG`: Configuration type (`no_index`, `btree_index`, `redis_cache`)
- `TABLE_SIZE`: Number of rows (`1000000` or `10000000`)
- `CONCURRENCY`: Number of concurrent threads (e.g., `10`, `50`, `100`, `200`, `500`)
- `TEST_DURATION`: Measurement phase duration in seconds (default: `300`)
- `WARMUP_DURATION`: Warmup phase duration in seconds (default: `60`)
- `WORKLOAD_SEED`: Random seed for reproducibility (default: `42`)

### Manual Configuration Override

```bash
# Example: Run custom test with environment variables
export TEST_CONFIG=redis_cache
export TABLE_SIZE=1000000
export CONCURRENCY=150
export TEST_DURATION=600

docker compose run --rm loadgen python /app/load_test.py
```

### Docker Resource Limits

Edit `docker-compose.yml` to adjust:
```yaml
services:
  postgres:
    deploy:
      resources:
        limits:
          cpus: "2.0"  # Increase for more powerful machines
          memory: 4G   # Increase for larger datasets
```

---

## Additional Resources

### Project Files

- **README.md**: Comprehensive methodology documentation (10 steps)
- **SUMMARY.md**: Executive project summary
- **proposal.md**: Initial project charter

### Community Dashboards

- **Grafana Dashboard 9628**: PostgreSQL Database
- **Grafana Dashboard 11835**: Redis
- **Grafana Dashboard 14282**: Docker Container Monitoring

### Useful Commands Cheatsheet

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# View logs
docker compose logs -f [service_name]

# Execute command in container
docker compose exec postgres psql -U testuser -d perftest

# View running containers
docker compose ps

# Restart a service
docker compose restart postgres

# Build fresh image
docker compose build --no-cache loadgen

# Remove everything and start fresh
docker compose down -v && docker system prune -af
```

---

## Next Steps

After completing the experiments and analysis:

1. **Review Findings**: Examine key findings in Jupyter notebook
2. **Write Report**: Document conclusions and recommendations
3. **Share Results**: Export visualizations and summary statistics
4. **Experiment Further**: Try different cache TTLs, query distributions, or table sizes

---

**Questions or Issues?**
- Check logs: `docker compose logs [service]`
- Review README.md for methodology details
- Check Docker resources: `docker stats`

**Happy experimenting!**
