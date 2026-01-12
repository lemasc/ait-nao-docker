# Project Summary: Web Server Performance Evaluation Lab

## Overview

This is a comprehensive performance testing laboratory project (NSPNAO2025 Lab Week 05) designed to systematically evaluate and compare the performance of Apache and Nginx web servers running in resource-constrained Docker containers under various concurrent user loads.

## Technical Architecture

### Physical Topology

The system uses a two-machine architecture:
- PC-1 (Load Generator Node): Runs k6 load testing tool to simulate concurrent user traffic
- PC-2 (Server Node): Hosts Docker environment with all services including web servers and monitoring stack

### System Components

**System Under Test (SUT):**
- Apache HTTP Server (httpd:latest) - Port 8080
- Nginx Web Server (nginx:latest) - Port 8081

**Monitoring Stack:**
- cAdvisor: Collects container resource usage metrics
- Prometheus: Time-series database for storing metrics (5-second scrape
interval)
- Grafana: Visualization dashboard (Dashboard ID: 14282 for Docker Container
Monitoring)

## Experimental Design

### Methodology

The lab follows a rigorous 10-step performance evaluation methodology:

1. State Goals and Define System: Comparative analysis between Apache/Nginx to
find scalability limits, knee points, and breaking points
2. List Services and Outcomes: HTTP GET requests to static index pages with
success/failure criteria
3. Select Metrics: Response time (http_req_duration), throughput (http_reqs), 
resource utilization (CPU/memory), error rates
4. List Parameters: Fixed (OS, hardware, network) and variable factors (web
server type, VU count)
5. Select Factors to Study: Virtual Users (VUs) as primary factor across 5
levels: 100, 500, 1000, 2500, 5000
6-10. Design, Execute, Analyze, Interpret, and Present Results

### Test Scenarios

**Scenario A: Low Resources**
- CPU Limit: 0.5 cores
- Memory Limit: 512MB
- 10 test runs (5 per web server)

**Scenario B: High Resources**
- CPU Limit: 1.0 core
- Memory Limit: 512MB
- 10 test runs (5 per web server)

Total Experimental Runs: 20 tests (4 blocks of 5 runs each)

## Load Testing Configuration

### Workload Profile

- Protocol: HTTP/1.1 GET
- Load Model: VUs-based (Closed Model)
- Test Stages:
- Warm-up: 30 seconds (ramp to target VUs)
- Steady State: 60 seconds (constant load for measurement)
- Cooldown: 30 seconds (ramp down to 0)
- Total Duration: 120 seconds per test
- Think Time: Random 0.5-2.0 seconds (simulates user behavior)
- Success Criteria: HTTP 200 OK
- Failure Observation: HTTP 429, 500+, timeouts

### k6 Script Features

- Configurable via environment variables (TARGET_URL, VUS, THINK_TIME_MIN/MAX)
- Stage-based load progression
- Built-in response validation checks
- CSV output for data analysis

## Metrics and Analysis

### Performance Metrics

**Response Time (Time):**
- http_req_duration with aggregations: avg, p95, max

**Throughput (Rate):**
- http_reqs (requests per second)

**Resource Utilization:**
- container_cpu_usage_seconds_total (% CPU)
- container_memory_usage_bytes (MB)

**Error Metrics:**
- http_req_failed (% of total requests)
- Connection errors

### Statistical Analysis

- Confidence Intervals: 95% CI using Z-distribution (n > 30)
- Formula: CI = x̄ ± z₁₋α/₂ (s/√n) where z = 1.96
- Visual Hypothesis Testing: CI overlap analysis to determine statistical
significance
- Capacity Curve Analysis: Identifies knee points and usable capacity

### Capacity Planning

**Capacity Curve Components:**
1. Throughput vs Load graph
2. Response Time (p95, p99) vs Load graph
3. Response Time Limit: p95 ≤ 500ms (configurable threshold)
4. Knee Point identification (where throughput plateaus and response time
spikes)
5. Usable Capacity determination (maximum load within acceptable response
time)

## Deployment Instructions

### File Structure

```
load-test/
├── docker-compose.yml# Orchestrates all services
├── prometheus.yml# Prometheus configuration
└── script.js# k6 load test script
```

### Execution Commands

**Scenario A (0.5 CPU):**
```
# Apache tests
k6 run -e VUS=100/500/1000/2500/5000 -e TARGET_URL=http://localhost:8080 --out
csv=apache_0.5_{VUS}.csv script.js

# Nginx tests
k6 run -e VUS=100/500/1000/2500/5000 -e TARGET_URL=http://localhost:8081 --out
csv=nginx_0.5_{VUS}.csv script.js
```

**Scenario B (1.0 CPU):**
```
# Update docker-compose.yml CPU limit to 1.0, then repeat tests
# Output files: apache_1.0_{VUS}.csv and nginx_1.0_{VUS}.csv
```

## Expected Outcomes

The lab enables students to:
- Compare Apache vs Nginx performance under resource constraints
- Understand scalability behavior as load increases
- Identify system capacity limits (knee points, breaking points)
- Perform statistical significance testing using confidence intervals
- Create capacity planning models with usable capacity recommendations
- Analyze the relationship between throughput, response time, and resource
utilization

## Technical Considerations

- Uses Docker Bridge networking
- Tests static content delivery (minimal application logic)
- Accounts for warm-up phase to avoid cold start effects
- Separates load generation from server node to prevent resource contention
- Provides standardized data collection format for reproducible analysis
