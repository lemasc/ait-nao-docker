# Database Performance Evaluation Project: Indexing vs. Redis Caching

## 1. State Goals and Define the System

### Goals (Specific and Measurable)

**Primary Goal:**

> "Compare the query response time and throughput of a PostgreSQL database under three configurations: (1) no index, (2) B-tree index on frequently queried columns, and (3) Redis cache layer, when handling 250 concurrent read requests for user lookup queries."

**Secondary Goals:**

- Determine the optimal cache TTL (Time-To-Live) that balances hit rate and data freshness
- Find the "knee" point where each configuration's throughput saturates
- Measure the write penalty introduced by indexing and cache invalidation

### System Boundaries

**Inside the System:**

- PostgreSQL database server (single instance)
- Redis cache server (single instance)
- Application layer (query router)
- Network connection between components (localhost or LAN)

**Outside the System:**

- Client load generator (treated as external workload)
- Operating system overhead (measured but not optimized)
- Disk I/O subsystem details (abstracted)

```
┌─────────────────────────────────────────────────────────────┐
│                      SYSTEM BOUNDARY                         │
│  ┌──────────┐      ┌──────────────┐      ┌──────────────┐   │
│  │  Client  │─────▶│  App Layer   │─────▶│  PostgreSQL  │   │
│  │ (Load    │      │  (Router)    │      │  (with/without│   │
│  │Generator)│      │              │      │   index)      │   │
│  └──────────┘      └──────┬───────┘      └──────────────┘   │
│       ▲                   │                                  │
│       │                   ▼                                  │
│       │            ┌──────────────┐                         │
│       └────────────│    Redis     │                         │
│                    │   (Cache)    │                         │
│                    └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. List Services and Outcomes

### Services Provided

| Service                 | Description                                |
| ----------------------- | ------------------------------------------ |
| **User Lookup (Read)**  | Query user record by user_id or email      |
| **User Search (Read)**  | Search users by name pattern or date range |
| **User Insert (Write)** | Add new user record                        |
| **User Update (Write)** | Modify existing user record                |

### Possible Outcomes

| Service     | Outcome        | Description                                |
| ----------- | -------------- | ------------------------------------------ |
| Read Query  | **Success**    | Correct data returned within timeout       |
| Read Query  | **Cache Hit**  | Data served from Redis (fast path)         |
| Read Query  | **Cache Miss** | Data fetched from PostgreSQL               |
| Read Query  | **Timeout**    | Query exceeds maximum wait time            |
| Read Query  | **Error**      | Connection failure or query error          |
| Write Query | **Success**    | Data written and indexes/cache updated     |
| Write Query | **Partial**    | Data written but cache invalidation failed |
| Write Query | **Failure**    | Write operation failed                     |

---

## 3. Select Metrics

### Primary Metrics

| Metric Type              | Metric                        | Definition                                      | Unit         | Classification               |
| ------------------------ | ----------------------------- | ----------------------------------------------- | ------------ | ---------------------------- |
| **Time/Responsiveness**  | Response Time (p50, p95, p99) | Time from query submission to response received | milliseconds | LB (Lower is Better)         |
| **Rate/Productivity**    | Throughput                    | Successful queries completed per second         | queries/sec  | HB (Higher is Better)        |
| **Resource/Utilization** | CPU Utilization               | Database server CPU usage during test           | percentage   | NB (Nominal is Best: 50-75%) |
| **Reliability**          | Error Rate                    | Fraction of queries that failed or timed out    | percentage   | LB                           |
| **Cache-specific**       | Cache Hit Rate                | Fraction of reads served from Redis             | percentage   | HB                           |

### Secondary Metrics

| Metric                     | Definition                             | Relevance        |
| -------------------------- | -------------------------------------- | ---------------- |
| Write Amplification        | Extra I/O due to index maintenance     | Index overhead   |
| Memory Usage               | RAM consumed by indexes/cache          | Resource cost    |
| Cache Invalidation Latency | Time to invalidate stale cache entries | Data consistency |

### Metric Selection Criteria

Following the document's guidance on **low variability**, **nonredundancy**, and **completeness**:

- **Low variability**: Use percentiles (p50, p95, p99) instead of just mean response time
- **Nonredundancy**: Throughput and response time may be redundant at steady state; consider using **Power = Throughput / Response Time** as a combined metric
- **Completeness**: Metrics cover all outcomes (success via throughput, errors via error rate, performance via response time)

---

## 4. List Parameters

### System Parameters

| Parameter            | Symbol  | Description                     | Typical Values   |
| -------------------- | ------- | ------------------------------- | ---------------- |
| Database engine      | -       | PostgreSQL version              | 15.x             |
| Index type           | I       | B-tree, Hash, GIN, etc.         | B-tree           |
| Index columns        | -       | Columns with indexes            | user_id, email   |
| Table size           | N       | Number of records               | 1M, 10M, 100M    |
| Redis memory limit   | M_redis | Max cache memory                | 1GB, 4GB         |
| Cache TTL            | TTL     | Time-to-live for cached entries | 60s, 300s, 3600s |
| Connection pool size | C_pool  | Max DB connections              | 10, 50, 100      |
| Query timeout        | T_max   | Maximum query wait time         | 5s, 30s          |

### Workload Parameters

| Parameter          | Symbol  | Description                    | Typical Values           |
| ------------------ | ------- | ------------------------------ | ------------------------ |
| Concurrent clients | C       | Number of parallel connections | 10, 50, 100, 250         |
| Read/Write ratio   | R:W     | Proportion of reads to writes  | 90:10, 99:1              |
| Query pattern      | -       | Point query vs. range query    | Point (80%), Range (20%) |
| Think time         | T_think | Delay between client requests  | 0ms, 100ms               |
| Data distribution  | -       | Uniform, Zipfian (hot spots)   | Zipfian (α=0.99)         |
| Test duration      | T_test  | Total experiment runtime       | 300s                     |

---

## 5. Select Factors to Study

From the parameter list, select factors that significantly impact performance:

### Primary Factors

| Factor                     | Levels                              | Rationale         |
| -------------------------- | ----------------------------------- | ----------------- |
| **Configuration**          | No Index, B-tree Index, Redis Cache | Core comparison   |
| **Table Size (N)**         | 1M, 10M                             | Tests scalability |
| **Concurrent Clients (C)** | 10, 50, 100, 200, 250               | Load scaling      |

### Secondary Factors (for sensitivity analysis)

| Factor                | Levels           | Rationale                         |
| --------------------- | ---------------- | --------------------------------- |
| **Cache TTL**         | 60s, 300s, 3600s | Trade-off: freshness vs. hit rate |
| **Read/Write Ratio**  | 90:10, 99:1      | Write penalty assessment          |
| **Data Distribution** | Uniform, Zipfian | Cache effectiveness               |

### Experimental Matrix (Full Factorial for Primary Factors)

```
3 Configurations × 2 Table Sizes × 5 Concurrency Levels = 30 experiments
```

Each experiment: 3 replications × 300 seconds = 900 seconds per configuration

---

## 6. Select Evaluation Technique

### Technique Selection

| Criterion      | Choice              | Justification                                                            |
| -------------- | ------------------- | ------------------------------------------------------------------------ |
| **Primary**    | Measurement         | Real database behavior is complex; simulation may miss important effects |
| **Secondary**  | Emulation           | Use Docker containers for reproducible environment                       |
| **Validation** | Analytical (simple) | Use Little's Law to validate throughput/response time relationship       |

### Justification (based on course criteria)

| Criterion     | Measurement Score | Rationale                               |
| ------------- | ----------------- | --------------------------------------- |
| Stage         | ✓ Postprototype   | PostgreSQL and Redis are mature systems |
| Accuracy      | Very High         | Real system behavior captured           |
| Realism       | Very High         | Actual database queries                 |
| Cost          | Medium            | Requires test infrastructure            |
| Repeatability | Moderate          | Use containerization to improve         |

### Tool Selection

| Component      | Tool                    | Purpose            |
| -------------- | ----------------------- | ------------------ |
| Database       | PostgreSQL 15           | Primary data store |
| Cache          | Redis 7                 | Caching layer      |
| Load Generator | pgbench / custom Python | Generate workload  |
| Monitoring     | Prometheus + Grafana    | Collect metrics    |
| Environment    | Docker Compose          | Reproducibility    |

---

## 7. Select Workload

### Workload Specification

| Characteristic      | Specification                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| **Data Model**      | Users table: user_id (PK), email, name, created_at, metadata (JSONB)                           |
| **Query Mix**       | 80% point queries (by user_id), 15% point queries (by email), 5% range queries (by created_at) |
| **Distribution**    | Zipfian (α=0.99) - realistic hot spot pattern                                                  |
| **Arrival Pattern** | Closed-loop with configurable think time                                                       |

### Schema Definition

```sql
CREATE TABLE users (
    user_id     BIGSERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    name        VARCHAR(255),
    created_at  TIMESTAMP DEFAULT NOW(),
    metadata    JSONB,
    status      VARCHAR(20) DEFAULT 'active'
);

-- Index configurations (applied selectively)
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created_at ON users(created_at);
```

### Query Templates

```sql
-- Q1: Point query by ID (80%)
SELECT * FROM users WHERE user_id = $1;

-- Q2: Point query by email (15%)
SELECT * FROM users WHERE email = $1;

-- Q3: Range query by date (5%)
SELECT * FROM users WHERE created_at BETWEEN $1 AND $2 LIMIT 100;
```

### Workload Form by Technique

| Technique             | Workload Representation                                    |
| --------------------- | ---------------------------------------------------------- |
| Measurement           | Python script with connection pool, executing actual SQL   |
| Emulation             | Same script against Dockerized PostgreSQL/Redis            |
| Analytical Validation | λ (arrival rate), μ (service rate) for M/M/1 approximation |

---

## 8. Design Experiment

### Experimental Design: Full Factorial

**Phase 1: Screening (Many factors, few levels)**

```
Factors: Configuration(3) × TableSize(2) × Concurrency(3) = 18 experiments
Purpose: Identify which factors have significant effects
```

**Phase 2: Detailed Study (Fewer factors, more levels)**

```
Focus on Configuration and Concurrency with finer granularity
Concurrency levels: 10, 25, 50, 75, 100, 150, 200, 250
Purpose: Find knee points and saturation behavior
```

### Experiment Procedure

```
For each (Configuration, TableSize, Concurrency):
    1. Reset environment (restart containers)
    2. Warm up (60 seconds of traffic, discard data)
    3. Run test (300 seconds)
    4. Collect metrics every 1 second
    5. Cool down (30 seconds)
    6. Repeat 3 times for statistical validity
```

### Experiment Schedule

| Exp ID | Config   | Table Size | Concurrency | Replications |
| ------ | -------- | ---------- | ----------- | ------------ |
| E01    | No Index | 1M         | 10          | 3            |
| E02    | No Index | 1M         | 50          | 3            |
| E03    | No Index | 1M         | 100         | 3            |
| ...    | ...      | ...        | ...         | ...          |
| E18    | Redis    | 10M        | 100         | 3            |

### Randomization

- Randomize experiment order to avoid time-based confounding
- Use different random seeds for workload generation in each replication

---

## 9. Analyze and Interpret Data

### Statistical Analysis Plan

**For each metric:**

1. Calculate mean, standard deviation, and confidence intervals (95%)
2. Report percentiles: p50, p95, p99 for response time
3. Use ANOVA to determine factor significance
4. Perform pairwise comparisons (Tukey HSD) for configuration differences

### Expected Analysis Questions

| Question                                       | Analysis Method                                |
| ---------------------------------------------- | ---------------------------------------------- |
| Which configuration has lowest response time?  | Compare p95 response times with CI             |
| At what load does each configuration saturate? | Find knee in throughput vs. concurrency curve  |
| Is Redis cache effective for this workload?    | Compare cache hit rate with speedup factor     |
| What is the write penalty of indexing?         | Compare write latency: indexed vs. non-indexed |

### Validation Checks

```python
# Little's Law validation
# L = λ * W (average items in system = arrival rate × average wait time)
# If throughput = 1000 qps and avg response time = 50ms
# Then avg concurrent requests ≈ 1000 * 0.050 = 50

def validate_littles_law(throughput, avg_response_time, avg_concurrent):
    expected_concurrent = throughput * avg_response_time
    error = abs(expected_concurrent - avg_concurrent) / avg_concurrent
    return error < 0.1  # Within 10% tolerance
```

### Interpretation Guidelines

- **Don't just report numbers** - explain what they mean for system design
- **Compare to baselines** - "Redis reduces p99 latency by 85% compared to no-index"
- **Identify trade-offs** - "Indexing improves read performance but adds 15% write overhead"

---

## 10. Present Results

### Visualization Plan

| Chart Type      | Purpose                                 | Example                    |
| --------------- | --------------------------------------- | -------------------------- |
| **Line chart**  | Throughput vs. Concurrency (find knee)  | Show saturation point      |
| **Bar chart**   | Response time comparison across configs | p50, p95, p99 side by side |
| **Heatmap**     | Factor interaction effects              | Config × TableSize         |
| **Time series** | Latency distribution over test duration | Identify warm-up effects   |

### Executive Summary Format

```
Key Findings (for decision-makers):
1. Redis caching provides 5× throughput improvement for read-heavy workloads
2. B-tree indexing is sufficient for workloads under 100 concurrent users
3. Redis becomes cost-effective when concurrent users exceed 200
4. Write penalty: 12% slower writes with indexes, 8% with cache invalidation
```

### Technical Report Structure

1. **Abstract** - One paragraph summary
2. **Goals and System Definition** - What we tested and why
3. **Methodology** - Experimental setup (reproducible)
4. **Results** - Charts and tables with confidence intervals
5. **Analysis** - Statistical significance and interpretation
6. **Recommendations** - Actionable conclusions
7. **Limitations** - Assumptions and scope
8. **Appendix** - Raw data, scripts, configuration files
