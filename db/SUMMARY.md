# Project Summary: Database Performance Evaluation Lab

## Overview

This is a comprehensive performance testing laboratory project designed to systematically evaluate and compare the query performance of PostgreSQL under three configurations: (1) No Index (baseline), (2) B-tree Index, and (3) Redis Cache layer. The project follows the systematic 10-step performance evaluation methodology and uses Docker containerization for reproducible testing.

## Technical Architecture

### Physical Topology

The system uses a single-host Docker environment with separated concerns:
- **Database Layer**: PostgreSQL 15 + Redis 7
- **Load Generation**: Python-based custom workload generator
- **Monitoring Stack**: Prometheus + Grafana + cAdvisor + exporters

### System Components

**System Under Test (SUT):**
- PostgreSQL 15 (postgres:15-alpine) - Port 5433
  - Resources: 2 CPU cores, 4GB RAM
  - Configured for performance testing with tuned parameters
- Redis 7 (redis:7-alpine) - Port 6380
  - Resources: 1 CPU core, 2GB RAM
  - LRU eviction policy, 1.5GB max memory

**Load Generator:**
- Python 3.11 application with psycopg2 and redis-py
- Multi-threaded workload execution (ThreadPoolExecutor)
- Zipfian distribution (α=0.99) for hot data access patterns
- Per-second metrics collection and CSV output

**Monitoring Stack:**
- postgres_exporter: Database metrics (connections, queries, cache hits)
- redis_exporter: Cache metrics (keyspace hits/misses, memory usage)
- cAdvisor: Container resource usage (CPU, memory, network)
- Prometheus: Time-series database (5-second scrape interval)
- Grafana: Visualization dashboard (admin/admin)

## Experimental Design

### Methodology

The lab follows a rigorous 10-step performance evaluation methodology:

1. **State Goals and Define System**: Compare PostgreSQL configurations to find scalability limits and identify knee points
2. **List Services and Outcomes**: Query operations (Q1: by user_id, Q2: by email, Q3: range by date) with success/failure criteria
3. **Select Metrics**: Response time percentiles (p50, p95, p99), throughput (QPS), error rate, cache hit rate
4. **List Parameters**: Fixed (hardware, OS, database versions) and variable factors (configuration, table size, concurrency)
5. **Select Factors to Study**: 3 configurations × 2 table sizes × 5 concurrency levels
6. **Select Evaluation Technique**: Measurement on controlled testbed with Docker isolation
7. **Select Workload**: Users table with Zipfian query distribution (80% Q1, 15% Q2, 5% Q3)
8. **Design Experiment**: Full factorial design with 30 experiments × 3 replications
9. **Analyze and Interpret Data**: ANOVA, Tukey HSD, confidence intervals, Little's Law validation
10. **Present Results**: Statistical analysis, capacity curves, knee point identification

### Test Configurations

**Configuration 1: No Index (Baseline)**
- Primary key only (user_id)
- No secondary indexes
- No caching layer
- Purpose: Establish baseline performance

**Configuration 2: B-tree Index**
- Primary key + B-tree indexes on email and created_at
- No caching layer
- Purpose: Measure indexing benefits for point and range queries

**Configuration 3: Redis Cache**
- Primary key + B-tree indexes
- Redis cache layer with 5-minute TTL
- Purpose: Measure caching effectiveness for hot data

### Experimental Variables

**Primary Factors:**
- Configuration: no_index, btree_index, redis_cache
- Table size: 1M, 10M rows
- Concurrency: 10, 50, 100, 200, 500 threads

**Experimental Matrix:**
- 3 configs × 2 table sizes × 5 concurrency = 30 experiments
- 3 replications per experiment = 90 total test runs
- Randomized execution order to avoid time-based confounding

## Load Testing Configuration

### Workload Profile

**Data Model:**
```sql
users table:
  - user_id: BIGSERIAL PRIMARY KEY
  - email: VARCHAR(255) NOT NULL
  - name: VARCHAR(255)
  - created_at: TIMESTAMP
  - metadata: JSONB
  - status: VARCHAR(20)
```

**Query Templates:**
- Q1 (80%): `SELECT * FROM users WHERE user_id = ?` (point query by ID)
- Q2 (15%): `SELECT * FROM users WHERE email = ?` (point query by email)
- Q3 (5%): `SELECT * FROM users WHERE created_at BETWEEN ? AND ? LIMIT 100` (range query)

**Workload Characteristics:**
- Distribution: Zipfian (α=0.99) - 80% of requests target top 1% of users
- Data generation: Faker library for realistic names, emails, dates
- Query selection: Random selection based on 80/15/5 distribution
- Load model: Closed-loop (fixed number of threads)

### Test Stages

**Warmup Phase (60 seconds):**
- Purpose: Warm OS cache, PostgreSQL buffers, Redis cache
- Data handling: Collected but marked with `is_warmup=True` flag
- Analysis: Excluded from final statistics

**Measurement Phase (300 seconds):**
- Purpose: Collect steady-state performance data
- Sampling: Per-second aggregation of metrics
- Data quality: Validate stationarity (stable metrics over time)

### Execution Commands

**Single Test (Manual):**
```bash
./run_single_test.sh redis_cache 1000000 100
```

**Full Experimental Run:**
```bash
./run_experiments.sh
# Runs all 90 tests (30 experiments × 3 replications)
# Estimated time: ~12 hours
```

## Metrics and Analysis

### Performance Metrics

**Response Time (Time):**
- p50, p95, p99 latency in milliseconds
- Collected per-second and aggregated per experiment

**Throughput (Rate):**
- Successful queries per second (QPS)
- Excludes failed queries from throughput calculation

**Resource Utilization:**
- CPU usage (%) for PostgreSQL and Redis containers
- Memory usage (MB)
- Collected via cAdvisor and exporters

**Cache Metrics (redis_cache only):**
- Cache hit rate (%)
- Cache misses per second
- Keyspace operations

**Error Metrics:**
- Error rate (% of failed requests)
- Query timeouts (5-second threshold)
- Connection failures

### Statistical Analysis

**Confidence Intervals:**
- 95% CI using t-distribution
- Formula: CI = x̄ ± t₍₁₋α/₂₎ × (s/√n)

**Hypothesis Testing:**
- ANOVA: Test if configuration has significant effect on throughput
- Tukey HSD: Pairwise comparisons between configurations
- Significance level: α = 0.05

**Validation:**
- Little's Law: L = λ × W (average concurrent requests = throughput × avg response time)
- Tolerance: Error < 10%

### Capacity Planning

**Capacity Curve Components:**
1. Throughput vs Concurrency graph (identify knee points)
2. Response time (p95) vs Concurrency graph
3. Response time threshold: p95 ≤ 500ms for usable capacity
4. Knee point identification: Where throughput plateaus and latency spikes

## Deployment Instructions

### File Structure

```
db/
├── docker-compose.yml      # Orchestrate all 8 services
├── Dockerfile              # Python load generator container
├── requirements.txt        # Python dependencies
├── prometheus.yml          # Monitoring configuration
├── init.sql                # Database schema initialization
├── generate_data.py        # Data generation with Zipfian distribution
├── setup_config.py         # Index and cache configuration management
├── load_test.py            # Main load testing engine
├── run_experiments.sh      # Full experimental orchestration
├── run_single_test.sh      # Single test runner (debugging)
├── analysis.ipynb          # Jupyter notebook for statistical analysis
├── results/                # CSV output files and figures
├── README.md               # Comprehensive methodology document
├── SUMMARY.md              # This file
└── GUIDE.md                # Step-by-step execution guide
```

### Prerequisites

- Docker and Docker Compose V2
- Python 3.11+ (for local analysis with Jupyter)
- 8GB+ RAM available for containers
- 50GB+ disk space for data and results

### Quick Start

```bash
# 1. Start infrastructure
cd db/
docker compose up -d postgres redis

# 2. Generate test data (1M rows)
docker compose run --rm loadgen python /app/generate_data.py --table-size 1000000

# 3. Run a single test
./run_single_test.sh redis_cache 1000000 100

# 4. Analyze results
jupyter notebook analysis.ipynb
```

## Expected Outcomes

The lab enables students to:

- **Compare configurations**: Quantify performance differences between no_index, btree_index, and redis_cache
- **Understand scalability**: Analyze how throughput and latency change with increasing concurrency
- **Identify system limits**: Find knee points where performance degrades
- **Perform statistical testing**: Use ANOVA and Tukey HSD for significance testing
- **Create capacity models**: Determine usable capacity within acceptable response time thresholds
- **Analyze cache effectiveness**: Measure speedup from Redis caching under Zipfian workload
- **Validate theoretical models**: Use Little's Law to validate throughput/latency relationship

## Technical Considerations

### Reproducibility

- **Containerization**: Isolated environment with fixed resource limits
- **Random seeds**: Configurable seeds for data generation and workload
- **Randomization**: Experiment order randomized to avoid time-based bias
- **Replication**: 3 replications per experiment for statistical validity

### Limitations

- **Single-host deployment**: No network latency, all services on same machine
- **Read-only workload**: Write penalty not measured (simplifies cache logic)
- **Fixed cache TTL**: 5-minute TTL not optimized per scenario
- **Table size limit**: Maximum 10M rows (smaller than production systems)
- **No cache warming optimization**: Cold start included in measurement

### Data Collection

- **Time resolution**: Per-second metrics aggregation
- **CSV output**: Portable format for analysis
- **Grafana dashboards**: Real-time monitoring during tests
- **File naming**: `{config}_{table_size}_{concurrency}_{timestamp}.csv`

### Monitoring Access

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **cAdvisor**: http://localhost:8082
- **PostgreSQL**: localhost:5433
- **Redis**: localhost:6380

## Results Interpretation

### Key Metrics to Analyze

1. **Throughput Improvement**: Speedup factor = Throughput(config) / Throughput(no_index)
2. **Latency Reduction**: Improvement % = (1 - Latency(config) / Latency(no_index)) × 100%
3. **Cache Hit Rate**: Correlation with throughput for redis_cache
4. **Resource Efficiency**: Throughput per CPU unit
5. **Knee Point**: Concurrency level where throughput plateaus

### Visualization Types

- **Capacity Curve**: Line chart of throughput vs concurrency
- **Response Time Comparison**: Bar chart of p50/p95/p99 by configuration
- **Heatmap**: Configuration × Concurrency interaction effects
- **Scalability Analysis**: Log-log plot to identify scaling behavior
- **Cache Effectiveness**: Scatter plot of hit rate vs throughput

## Support and Troubleshooting

### Common Issues

1. **Services not starting**: Check Docker resources, ensure ports not in use
2. **Data generation slow**: Normal for 10M rows (~10-15 minutes)
3. **High error rates**: May indicate resource exhaustion, check logs
4. **Cache hit rate low**: Verify Zipfian distribution loaded correctly

### Log Access

```bash
# View service logs
docker compose logs postgres
docker compose logs loadgen

# Real-time monitoring
docker compose logs -f prometheus
```

### Cleanup

```bash
# Stop all services and remove volumes
docker compose down -v

# Remove generated data flags
rm results/.data_generated_*
```

---

**Project**: Database Performance Evaluation Lab
**Course**: NSPNAO2025 Lab Week 06-07
**Methodology**: 10-Step Systematic Performance Evaluation
**Technologies**: PostgreSQL 15, Redis 7, Python 3.11, Docker Compose, Jupyter
