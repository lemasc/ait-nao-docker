"""
Workload execution module for running multi-threaded benchmark workloads.
"""

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .database import Database
from .metrics import MetricsCollector
from .queries import OperationType, QueryExecutor

logger = logging.getLogger(__name__)


class WorkloadExecutor:
    """Executes multi-threaded benchmark workload."""

    def __init__(self, database: Database, metrics: MetricsCollector, config: dict):
        """
        Initialize workload executor.

        Args:
            database: Database instance
            metrics: MetricsCollector instance
            config: Workload configuration dictionary
        """
        self.database = database
        self.metrics = metrics
        self.config = config

        # Workload parameters
        self.concurrency = config.get('concurrency', 4)
        self.duration_seconds = config.get('duration_seconds', 300)
        self.warmup_seconds = config.get('warmup_seconds', 60)

        # Read/write ratio
        read_pct, write_pct = config.get('read_write_ratio', [90, 10])
        self.read_probability = read_pct / 100.0

        # Per-session timeouts for workload connections (prep stays unbounded).
        self.statement_timeout_ms = config.get('statement_timeout_ms', 2000)
        self.lock_timeout_ms = config.get('lock_timeout_ms', 200)

        # Operation weights
        read_ops = config.get('read_operations', {})
        self.read_operation_weights = [
            ('point_lookup', read_ops.get('point_lookup_weight', 50)),
            ('range_scan', read_ops.get('range_scan_weight', 30)),
            ('range_order', read_ops.get('range_order_weight', 20)),
        ]

        write_ops = config.get('write_operations', {})
        self.write_operation_weights = [
            ('insert', write_ops.get('insert_weight', 50)),
            ('update', write_ops.get('update_weight', 50)),
        ]

        # Normalize weights
        self.read_operations = self._normalize_weights(self.read_operation_weights)
        self.write_operations = self._normalize_weights(self.write_operation_weights)

        # Query executor
        range_scan_size = config.get('range_scan_size', 100)
        payload_size_bytes = config.get('payload_size_bytes', 1024)

        # Get data ranges
        id_range = database.get_min_max_id()
        indexed_col_range = database.get_indexed_col_range()

        self.query_executor = QueryExecutor(
            id_range=id_range,
            indexed_col_range=indexed_col_range,
            range_scan_size=range_scan_size,
            payload_size_bytes=payload_size_bytes
        )

        # Control flags
        self.stop_flag = threading.Event()
        self.warmup_mode = False

    def _normalize_weights(self, weights: list[tuple[str, int]]) -> list[tuple[str, float]]:
        """
        Normalize operation weights to probabilities.

        Args:
            weights: List of (operation_name, weight) tuples

        Returns:
            List of (operation_name, cumulative_probability) tuples
        """
        total = sum(w for _, w in weights)
        cumulative = 0.0
        normalized = []

        for op, weight in weights:
            cumulative += weight / total
            normalized.append((op, cumulative))

        return normalized

    def _select_operation(self) -> OperationType:
        """
        Select an operation type based on configured probabilities.

        Returns:
            Operation type to execute
        """
        # First decide read or write
        if random.random() < self.read_probability:
            # Select read operation
            r = random.random()
            for op, cumulative_prob in self.read_operations:
                if r <= cumulative_prob:
                    return op
            # Fallback to last operation
            return self.read_operations[-1][0]
        else:
            # Select write operation
            r = random.random()
            for op, cumulative_prob in self.write_operations:
                if r <= cumulative_prob:
                    return op
            # Fallback to last operation
            return self.write_operations[-1][0]

    def _worker_thread(self, worker_id: int, collect_metrics: bool = True) -> int:
        """
        Worker thread that continuously executes operations.

        Args:
            worker_id: Worker thread identifier
            collect_metrics: Whether to collect metrics for these operations

        Returns:
            Number of operations executed
        """
        operations_executed = 0

        try:
            # Get a dedicated connection for this worker
            with self.database.get_connection() as conn:
                with conn.cursor() as cur:
                    statement_timeout_ms = int(self.statement_timeout_ms)
                    lock_timeout_ms = int(self.lock_timeout_ms)
                    cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
                    cur.execute(f"SET lock_timeout = {lock_timeout_ms}")
                logger.debug(f"Worker {worker_id} started")

                while not self.stop_flag.is_set():
                    # Select operation type
                    operation_type = self._select_operation()

                    # Execute operation
                    latency, success = self.query_executor.execute_operation(
                        operation_type, conn
                    )

                    # Record metrics if not in warmup mode
                    if collect_metrics and not self.warmup_mode:
                        self.metrics.record_operation(operation_type, latency, success)

                    operations_executed += 1

                    # Small sleep to prevent tight loop (optional, can remove for max throughput)
                    # time.sleep(0.0001)

        except Exception as e:
            logger.error(f"Worker {worker_id} encountered error: {e}", exc_info=True)

        logger.debug(f"Worker {worker_id} stopped after {operations_executed} operations")
        return operations_executed

    def run_warmup(self):
        """Run warmup phase."""
        logger.info(f"Starting warmup phase ({self.warmup_seconds} seconds)")
        self.warmup_mode = True
        self.stop_flag.clear()

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            # Start workers
            futures = [
                executor.submit(self._worker_thread, i, collect_metrics=False)
                for i in range(self.concurrency)
            ]

            # Run for warmup duration
            time.sleep(self.warmup_seconds)

            # Stop workers
            self.stop_flag.set()

            # Wait for completion
            total_ops = sum(f.result() for f in as_completed(futures))

        self.warmup_mode = False
        logger.info(f"Warmup completed ({total_ops:,} operations)")

    def run_measurement(self):
        """Run measurement phase."""
        logger.info(f"Starting measurement phase ({self.duration_seconds} seconds)")
        self.stop_flag.clear()

        # Update active connections metric
        self.metrics.set_active_connections(self.concurrency)

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            # Start workers
            futures = [
                executor.submit(self._worker_thread, i, collect_metrics=True)
                for i in range(self.concurrency)
            ]

            # Run for measurement duration
            time.sleep(self.duration_seconds)

            # Stop workers
            self.stop_flag.set()

            # Wait for completion
            total_ops = sum(f.result() for f in as_completed(futures))

        actual_duration = time.time() - start_time
        throughput = total_ops / actual_duration

        # Update active connections to 0
        self.metrics.set_active_connections(0)

        logger.info(f"Measurement completed: {total_ops:,} operations in {actual_duration:.2f}s "
                   f"({throughput:.2f} ops/sec)")

        return actual_duration

    def run_full_workload(self) -> float:
        """
        Run complete workload: warmup + measurement.

        Returns:
            Actual measurement duration in seconds
        """
        logger.info("Starting full workload execution")

        # Warmup phase
        if self.warmup_seconds > 0:
            self.run_warmup()

        # Small pause between phases
        time.sleep(2)

        # Measurement phase
        duration = self.run_measurement()

        logger.info("Full workload execution completed")
        return duration
