#!/usr/bin/env python3
"""
Load testing script for database performance evaluation.

This script generates database workload with configurable concurrency,
collects performance metrics, and outputs results to CSV.
"""

import argparse
import csv
import json
import os
import sys
import time
import random
import signal
from datetime import datetime, timedelta
from collections import deque, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import psycopg2.pool
import redis
import numpy as np


# Global configuration
class Config:
    def __init__(self):
        # Database connection
        self.DB_HOST = os.getenv('DB_HOST', 'postgres')
        self.DB_PORT = int(os.getenv('DB_PORT', 5432))
        self.DB_NAME = os.getenv('DB_NAME', 'perftest')
        self.DB_USER = os.getenv('DB_USER', 'testuser')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD', 'testpass')

        # Redis connection
        self.REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

        # Test configuration
        self.TEST_CONFIG = os.getenv('TEST_CONFIG', 'no_index')
        self.TABLE_SIZE = int(os.getenv('TABLE_SIZE', 1000000))
        self.CONCURRENCY = int(os.getenv('CONCURRENCY', 10))
        self.TEST_DURATION = int(os.getenv('TEST_DURATION', 300))
        self.WARMUP_DURATION = int(os.getenv('WARMUP_DURATION', 60))
        self.WORKLOAD_SEED = int(os.getenv('WORKLOAD_SEED', 42))

        # Query configuration
        self.QUERY_TIMEOUT = int(os.getenv('QUERY_TIMEOUT_MS', 15000))  # milliseconds
        self.CACHE_TTL = 300  # seconds
        self.HOT_READ_FRACTION = float(os.getenv('HOT_READ_FRACTION', 0.80))
        self.PRECOMPUTE_SAMPLE_SIZE = int(os.getenv('PRECOMPUTE_SAMPLE_SIZE', 1_000_000))

        # Results
        self.RESULTS_DIR = '/app/results'

        # Enable caching only for redis_cache config
        self.USE_CACHE = (self.TEST_CONFIG == 'redis_cache')


# Global state
config = Config()
pg_pool = None
redis_pool = None
hot_users = None
precomputed_hot_samples = None  # Pre-computed Zipfian samples for hot set
precomputed_cold_samples = None  # Pre-computed uniform samples for cold set
hot_fraction = 0.0
shutdown_flag = False

# Metrics storage
metrics_lock = Lock()
request_metrics = deque()  # Store per-request metrics


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global shutdown_flag
    print("\n\nReceived shutdown signal. Finishing current requests...")
    shutdown_flag = True


def initialize_connection_pools():
    """Initialize PostgreSQL and Redis connection pools."""
    global pg_pool, redis_pool

    print("Initializing connection pools...")

    # PostgreSQL connection pool
    try:
        pool_size = max(config.CONCURRENCY, 1)
        pg_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=pool_size,
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            connect_timeout=10,
            options=f'-c statement_timeout={config.QUERY_TIMEOUT}'
        )
        print(f"  ✓ PostgreSQL pool created (size: 5-{pool_size})")
    except Exception as e:
        print(f"  ✗ Failed to create PostgreSQL pool: {e}")
        sys.exit(1)

    # Redis connection pool (if caching enabled)
    if config.USE_CACHE:
        try:
            redis_pool = redis.ConnectionPool(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                max_connections=max(config.CONCURRENCY, 50),
                socket_timeout=5,
                socket_connect_timeout=5,
                decode_responses=True
            )
            # Test connection
            r = redis.Redis(connection_pool=redis_pool)
            r.ping()
            print(f"  ✓ Redis pool created (caching enabled)")
        except Exception as e:
            print(f"  ✗ Failed to create Redis pool: {e}")
            sys.exit(1)


def load_hot_users_distribution():
    """Load Zipfian distribution for hot data access and pre-compute samples."""
    global hot_users, precomputed_hot_samples, precomputed_cold_samples, hot_fraction

    hot_users_file = os.path.join(config.RESULTS_DIR, 'hot_users.json')
    if not os.path.exists(hot_users_file):
        print(f"✗ Hot users file not found: {hot_users_file}")
        print("  Run generate_data.py first to create this file.")
        sys.exit(1)

    with open(hot_users_file, 'r') as f:
        hot_users = json.load(f)

    total_users = int(hot_users.get('total_users', config.TABLE_SIZE))
    hot_count = int(hot_users['hot_count'])
    cold_start = hot_count + 1
    cold_end = total_users

    hot_fraction = max(0.0, min(1.0, config.HOT_READ_FRACTION))

    print(f"✓ Loaded hot users distribution:")
    print(f"  - {hot_users['hot_count']} hot users (top 1%)")
    print(f"  - Zipfian α={hot_users['alpha']}")
    print(f"  - Hot read fraction: {hot_fraction:.0%}")

    # Pre-compute samples for performance (avoids expensive RNG in hot path)
    print("  Pre-computing Zipfian samples...")
    sample_size = config.PRECOMPUTE_SAMPLE_SIZE
    precomputed_hot_samples = np.random.choice(
        hot_users['user_ids'],
        size=sample_size,
        p=hot_users['probabilities'],
        replace=True
    )
    print(f"  ✓ Pre-computed {sample_size:,} hot samples (~{precomputed_hot_samples.nbytes / 1024 / 1024:.1f} MB)")

    if cold_start <= cold_end:
        precomputed_cold_samples = np.random.randint(
            cold_start,
            cold_end + 1,
            size=sample_size
        )
        print(f"  ✓ Pre-computed {sample_size:,} cold samples")
    else:
        precomputed_cold_samples = None
        print("  ⚠ No cold range available; all reads will target hot users")

    # Verify distribution is preserved
    unique_samples = len(set(precomputed_hot_samples))
    print(f"  ✓ Hot distribution: {unique_samples:,} unique users in sample")


def select_user_id():
    """Select user ID from hot/cold pre-computed samples (fast array lookup)."""
    use_hot = random.random() < hot_fraction or precomputed_cold_samples is None
    if use_hot:
        idx = random.randint(0, len(precomputed_hot_samples) - 1)
        return int(precomputed_hot_samples[idx])
    idx = random.randint(0, len(precomputed_cold_samples) - 1)
    return int(precomputed_cold_samples[idx])


def select_query_type():
    """Select query type based on workload distribution."""
    rand = random.random()
    if rand < 0.80:
        return 'Q1'  # 80% - Point query by user_id
    elif rand < 0.95:
        return 'Q2'  # 15% - Point query by email
    else:
        return 'Q3'  # 5% - Range query by created_at


def execute_query_q1(conn, user_id):
    """Execute Q1: Point query by user_id."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
        result = cur.fetchall()
    return result


def execute_query_q2(conn, email):
    """Execute Q2: Point query by email."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s;", (email,))
        result = cur.fetchall()
    return result


def execute_query_q3(conn, start_date, end_date):
    """Execute Q3: Range query by created_at."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM users WHERE created_at BETWEEN %s AND %s LIMIT 100;",
            (start_date, end_date)
        )
        result = cur.fetchall()
    return result


def execute_with_cache(query_type, params, pg_conn, redis_client):
    """Execute query with Redis cache (if enabled).

    Optimized version that reuses connections to eliminate object creation overhead.

    Args:
        query_type: Type of query (Q1, Q2, Q3)
        params: Query parameters
        pg_conn: Pre-created PostgreSQL connection (reused per worker)
        redis_client: Pre-created Redis client (reused per worker, or None)
    """
    # Generate cache key
    if query_type == 'Q1':
        cache_key = f"user:id:{params[0]}"
    elif query_type == 'Q2':
        cache_key = f"user:email:{params[0]}"
    else:  # Q3
        cache_key = f"users:range:{params[0]}:{params[1]}"

    # Try cache first (if enabled)
    cache_hit = False
    if config.USE_CACHE and redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                cache_hit = True
                result = json.loads(cached)
                return result, cache_hit
        except Exception as e:
            # Cache error - fallback to database
            pass

    # Cache miss or caching disabled - query PostgreSQL
    if query_type == 'Q1':
        result = execute_query_q1(pg_conn, params[0])
    elif query_type == 'Q2':
        result = execute_query_q2(pg_conn, params[0])
    else:  # Q3
        result = execute_query_q3(pg_conn, params[0], params[1])

    # Store in cache if enabled
    if config.USE_CACHE and redis_client:
        try:
            # Convert result to JSON-serializable format
            result_json = json.dumps([[str(v) for v in row] for row in result])
            redis_client.setex(cache_key, config.CACHE_TTL, result_json)
        except Exception as e:
            # Cache write error - ignore
            pass

    return result, cache_hit


def worker_task(worker_id, test_start_time, warmup_duration, test_duration):
    """Worker task that executes queries in a loop.

    Optimized version: Creates connections once per worker and reuses them
    throughout the worker's lifetime to eliminate pool contention and
    object creation overhead.
    """
    global shutdown_flag, request_metrics, pg_pool, redis_pool

    # Set random seed for this worker
    np.random.seed(config.WORKLOAD_SEED + worker_id)
    random.seed(config.WORKLOAD_SEED + worker_id)

    # Acquire connections ONCE per worker (not per request)
    pg_conn = pg_pool.getconn()
    redis_client = redis.Redis(connection_pool=redis_pool) if config.USE_CACHE else None

    try:
        total_duration = warmup_duration + test_duration

        while not shutdown_flag:
            elapsed = time.time() - test_start_time
            if elapsed >= total_duration:
                break

            is_warmup = (elapsed < warmup_duration)

            # Select query type
            query_type = select_query_type()

            # Generate query parameters
            if query_type == 'Q1':
                user_id = select_user_id()
                params = (user_id,)
            elif query_type == 'Q2':
                user_id = select_user_id()
                email = f"user{user_id}@example.com"
                params = (email,)
            else:  # Q3
                # Random date range within data range
                base_date = datetime(2020, 1, 1)
                start_offset = random.randint(0, 1430)
                range_days = random.randint(1, 30)
                start_date = base_date + timedelta(days=start_offset)
                end_date = start_date + timedelta(days=range_days)
                params = (start_date, end_date)

            # Execute query and measure time (using reused connections)
            start_time = time.time()
            success = True
            cache_hit = False
            error_type = None

            try:
                result, cache_hit = execute_with_cache(query_type, params, pg_conn, redis_client)
            except Exception as e:
                success = False
                error_type = type(e).__name__

            end_time = time.time()
            response_time = (end_time - start_time) * 1000  # milliseconds

            # Record metrics
            with metrics_lock:
                request_metrics.append({
                    'timestamp': end_time,
                    'query_type': query_type,
                    'response_time': response_time,
                    'success': success,
                    'cache_hit': cache_hit,
                    'is_warmup': is_warmup,
                    'error_type': error_type
                })
    finally:
        # Release connection when worker exits
        pg_pool.putconn(pg_conn)


def aggregate_metrics_per_second(test_start_time, warmup_duration):
    """Aggregate metrics into per-second buckets."""
    global request_metrics

    # Group metrics by second
    second_buckets = defaultdict(lambda: {
        'latencies': [],
        'successes': 0,
        'errors': 0,
        'error_types': defaultdict(int),
        'cache_hits': 0,
        'cache_misses': 0,
        'q1_count': 0,
        'q2_count': 0,
        'q3_count': 0
    })

    with metrics_lock:
        for metric in request_metrics:
            elapsed_seconds = int(metric['timestamp'] - test_start_time)
            bucket = second_buckets[elapsed_seconds]

            bucket['latencies'].append(metric['response_time'])

            if metric['success']:
                bucket['successes'] += 1
            else:
                bucket['errors'] += 1
                if metric['error_type']:
                    bucket['error_types'][metric['error_type']] += 1

            if config.USE_CACHE:
                if metric['cache_hit']:
                    bucket['cache_hits'] += 1
                else:
                    bucket['cache_misses'] += 1

            # Count query types
            if metric['query_type'] == 'Q1':
                bucket['q1_count'] += 1
            elif metric['query_type'] == 'Q2':
                bucket['q2_count'] += 1
            else:
                bucket['q3_count'] += 1

    # Convert to time series
    time_series = []
    for second in sorted(second_buckets.keys()):
        bucket = second_buckets[second]
        latencies = bucket['latencies']

        if len(latencies) > 0:
            time_series.append({
                'timestamp': datetime.fromtimestamp(test_start_time + second).isoformat(),
                'elapsed_seconds': second,
                'is_warmup': (second < warmup_duration),
                'throughput_qps': len(latencies),
                'response_time_p50_ms': np.percentile(latencies, 50),
                'response_time_p95_ms': np.percentile(latencies, 95),
                'response_time_p99_ms': np.percentile(latencies, 99),
                'response_time_mean_ms': np.mean(latencies),
                'response_time_max_ms': np.max(latencies),
                'error_rate_pct': (bucket['errors'] / len(latencies)) * 100,
                'error_types_json': json.dumps(bucket['error_types']),
                'cache_hit_rate_pct': (bucket['cache_hits'] / (bucket['cache_hits'] + bucket['cache_misses']) * 100)
                                      if (bucket['cache_hits'] + bucket['cache_misses']) > 0 else 0,
                'q1_count': bucket['q1_count'],
                'q2_count': bucket['q2_count'],
                'q3_count': bucket['q3_count']
            })

    return time_series


def write_results_to_csv(time_series, output_file):
    """Write time series metrics to CSV file."""
    if len(time_series) == 0:
        print("  ✗ No metrics to write")
        return

    fieldnames = [
        'timestamp', 'elapsed_seconds', 'is_warmup', 'throughput_qps',
        'response_time_p50_ms', 'response_time_p95_ms', 'response_time_p99_ms',
        'response_time_mean_ms', 'response_time_max_ms',
        'error_rate_pct', 'error_types_json', 'cache_hit_rate_pct',
        'q1_count', 'q2_count', 'q3_count'
    ]

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(time_series)

    print(f"✓ Results written to {output_file}")
    print(f"  - {len(time_series)} seconds of data")


def main():
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 70)
    print("Database Performance Evaluation - Load Test")
    print("=" * 70)
    print(f"Configuration:  {config.TEST_CONFIG}")
    print(f"Table size:     {config.TABLE_SIZE:,} rows")
    print(f"Concurrency:    {config.CONCURRENCY} threads")
    print(f"Warmup:         {config.WARMUP_DURATION} seconds")
    print(f"Test duration:  {config.TEST_DURATION} seconds")
    print(f"Total duration: {config.WARMUP_DURATION + config.TEST_DURATION} seconds")
    print(f"Caching:        {'Enabled' if config.USE_CACHE else 'Disabled'}")
    print()

    # Initialize
    initialize_connection_pools()
    load_hot_users_distribution()

    # Run test
    print("\nStarting load test...")
    test_start_time = time.time()

    # Create thread pool
    with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as executor:
        # Submit worker tasks
        futures = []
        for worker_id in range(config.CONCURRENCY):
            future = executor.submit(
                worker_task,
                worker_id,
                test_start_time,
                config.WARMUP_DURATION,
                config.TEST_DURATION
            )
            futures.append(future)

        # Monitor progress
        last_report = time.time()
        while True:
            elapsed = time.time() - test_start_time
            total_duration = config.WARMUP_DURATION + config.TEST_DURATION

            if elapsed >= total_duration or shutdown_flag:
                break

            # Report progress every 30 seconds
            if time.time() - last_report >= 30:
                if elapsed < config.WARMUP_DURATION:
                    print(f"  Warmup phase: {elapsed:.0f}s / {config.WARMUP_DURATION}s")
                else:
                    test_elapsed = elapsed - config.WARMUP_DURATION
                    print(f"  Test progress: {test_elapsed:.0f}s / {config.TEST_DURATION}s")
                last_report = time.time()

            time.sleep(1)

        # Wait for all workers to complete (with timeout)
        for future in as_completed(futures, timeout=10):
            pass

    print("\n✓ Load test completed")

    # Aggregate metrics
    print("\nAggregating metrics...")
    time_series = aggregate_metrics_per_second(test_start_time, config.WARMUP_DURATION)

    # Calculate summary statistics
    measurement_data = [row for row in time_series if not row['is_warmup']]
    if measurement_data:
        avg_throughput = np.mean([row['throughput_qps'] for row in measurement_data])
        avg_p95 = np.mean([row['response_time_p95_ms'] for row in measurement_data])
        avg_error_rate = np.mean([row['error_rate_pct'] for row in measurement_data])
        avg_cache_hit = np.mean([row['cache_hit_rate_pct'] for row in measurement_data])

        print(f"  ✓ Average throughput: {avg_throughput:.1f} qps")
        print(f"  ✓ Average p95 latency: {avg_p95:.2f} ms")
        print(f"  ✓ Average error rate: {avg_error_rate:.2f}%")
        if config.USE_CACHE:
            print(f"  ✓ Average cache hit rate: {avg_cache_hit:.2f}%")

    # Write results to CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(
        config.RESULTS_DIR,
        f"{config.TEST_CONFIG}_{config.TABLE_SIZE}_{config.CONCURRENCY}_{timestamp}.csv"
    )

    print("\nWriting results...")
    write_results_to_csv(time_series, output_file)

    # Cleanup
    if pg_pool:
        pg_pool.closeall()
    if redis_pool:
        redis_pool.disconnect()

    print("\n" + "=" * 70)
    print("Load test completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    main()
