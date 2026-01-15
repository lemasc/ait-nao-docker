# Project Proposal (Systematic 10-Step Approach)

## Topic

**Comparing PostgreSQL tradeoffs between no indexing vs single-column B-tree indexing across variants of OLTP read/write workloads**

This project applies the systematic workflow to avoid common evaluation mistakes (unclear goals, wrong metrics, unrepresentative workload, etc.). 

---

## 1) State Goals and Define the System 

### Goal (decision question)

**Determine whether adding one canonical B-tree index is beneficial under different OLTP read/write workload ratios and concurrency levels**, and quantify the tradeoff (read latency improvements vs write overhead).

### Scope boundaries

* PostgreSQL **15**
* **Single-node** only (no replication)
* Linux host + **SSD storage**, likely run via Docker
* Resource constraint for v1:

  * **CPU: 4 cores**
  * **RAM: 8GB**
* Outside scope (v1):

  * replication, failover
  * cross-node networking effects
  * multi-index / composite index tuning

---

## 2) List Services and Outcomes 

### Services (requests)

**Read services**

1. **Point lookup**
2. **Range scan**
3. **Range scan + ORDER BY**

**Write services**

1. **INSERT**
2. **UPDATE (payload-only)**

### Outcomes to record

* Success (correct result)
* Failure: timeouts, deadlocks/lock-waits beyond threshold, errors 

---

## 3) Select Metrics 

### Primary metric (decision-driving)

* **p95 latency** per operation type (read vs write), measured at the client

### Secondary performance metric

* **Throughput** (ops/sec or transactions/sec), per workload mix

### Supporting “explain why” metrics (collected but not necessarily decision criteria)

* CPU utilization, load average
* Disk IO: IOPS, throughput, IO wait
* PostgreSQL stats:

  * buffer hit ratio
  * index vs sequential scan counts
  * WAL volume / checkpoint behavior
  * table size vs index size growth

These follow the “time / rate / resource” guidance for successful service. 

---

## 4) List Parameters (that can affect performance) 

### System parameters (fixed in v1)

* PostgreSQL version: 15
* CPU: 4 cores
* RAM: 8GB
* Storage: SSD
* Docker container runtime
* PostgreSQL configuration: defaults, with a recorded subset (see below)
* Observability: Prometheus + Grafana

### Workload parameters (defined inputs)

* Read/write ratio (operations mix)
* Concurrency (client count)
* Dataset size regime (cache-resident vs disk-resident) *(see Step 5 plan)*
* Query templates (point/range/order-by)
* Update type: payload-only

---

## 5) Select Factors to Study 

We deliberately vary a **small, impactful set of factors** to keep v1 efficient.

### Factor A — Indexing (2 levels)

* **No indexing**: no explicit index except PK (and any unavoidable internal constraints)
* **B-tree indexing**: **single canonical column**, full index

### Factor B — Read/write ratio (3 levels)

Using **ratio of operations** (not time-based), as you decided:

* **90/10** (read-heavy)
* **50/50** (balanced)
* **10/90** (write-heavy)

### Factor C — Concurrency (5 levels)

* **1, 4, 8, 16, 32 clients**

### Factor D — Dataset size regime (2 levels, planned as staged)

You asked if we can test both cache scenarios — yes.

* **Memory-resident**: dataset ≈ **0.25× RAM**
* **Disk-resident**: dataset ≈ **2× RAM**

To keep v1 manageable, we’ll stage this in experiment design (Step 8).

---

## 6) Select Evaluation Technique 

**Technique: Measurement**

* We will execute workloads against real PostgreSQL on the defined testbed and measure end-to-end performance. 

Instrumentation plan:

* Query latency/throughput from workload driver
* PostgreSQL statistics views + optional `pg_stat_statements`
* Prometheus exporters (node + postgres exporter) feeding Grafana dashboards

---

## 7) Select Workload 

Workload must be representative of the “database queries + updates” we want to study. 

### Workload model (OLTP, single-table)

Single table is enough for v1, to isolate index effects.

Example table sketch (final schema can be minimal):

* `id` (PK)
* `indexed_col` (the canonical index column)
* `payload` (updated frequently)
* `created_at` or similar (optional)

### Query templates

* **Point lookup**: `WHERE indexed_col = ?`
* **Range scan**: `WHERE indexed_col BETWEEN ? AND ? LIMIT N`
* **Range + ORDER BY**: `... ORDER BY indexed_col LIMIT N`
* **Insert**
* **Update payload-only**: `SET payload = ? WHERE id = ?`

### Test phases (per run)

* Load data
* Warm-up
* Steady state measurement window
* Cooldown
* Vacuum/analyze (as planned)

---

## 8) Design Experiment 

We will follow an efficient two-phase design approach. 

### Phase 1 (v1 baseline): memory-resident dataset

Purpose: isolate algorithmic tradeoffs with minimal IO noise.

Runs:

* 2 indexing levels × 3 ratios × 5 concurrencies
  = **30 configurations**

Repetitions:

* Repeat each configuration **3 times**, report mean + variability (Step 9)

### Phase 2 (v1 extension): disk-resident dataset

Same matrix as Phase 1, run on dataset ≈ 2× RAM:

* another **30 configurations**

This gives you “both cache regimes” without inflating the initial setup complexity.

---

## 9) Analyze and Interpret Data 

### What we will compute

For each configuration:

* p95 latency for each operation class
* throughput (ops/sec)
* resource profile (CPU/IO)
* index overhead indicators (index size, WAL rate, checkpoints)

### Variability and statistical treatment

Because measurements vary run-to-run, we will:

* report confidence intervals or error bars (at least across repeats)
* avoid conclusions based only on averages 

### Expected interpretation outcomes (examples)

* Identify the “knee point” where concurrency causes latency explosion
* Identify which ratios benefit from indexing vs which ratios suffer write penalty

---

## 10) Present Results 

The goal is decision clarity: “When should we add the index?” 

### Deliverables

1. **Executive summary** (1 page)

* Recommendation: “Index helps when read ratio ≥ X% AND concurrency ≤/≥ Y”
* Explicit assumptions & limitations

2. **Technical report**

* Full configuration matrix + raw results
* Dashboard snapshots
* Detailed explanation of *why* (CPU/IO/index scan evidence)

### Visualization plan

* p95 latency vs concurrency (separate plots per ratio)
* throughput vs concurrency
* index overhead: write TPS drop, WAL rate, index size growth
* (optional) heatmap of “index wins / loses” across (ratio × concurrency)

---

# V1 Final Configuration (what we will implement)

* PG 15, Docker, SSD
* CPU/RAM: **4 cores / 8GB**
* Index: none vs single-column B-tree
* Workload: OLTP single-table
* Read types: point + range + range/ORDER BY
* Writes: insert + update payload-only
* Ratios: **90/10, 50/50, 10/90**
* Concurrency: **1, 4, 8, 16, 32**
* Cache regime: Phase 1 in-cache, Phase 2 out-of-cache

