"""
Metrics collection and export module using Prometheus client.
"""

import csv
import json
import logging
import random
import threading
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server

logger = logging.getLogger(__name__)
ERROR_TYPES = ("timeout_statement", "timeout_lock", "deadlock", "other")


class MetricsCollector:
    """Collects and exports performance metrics."""

    def __init__(self, config: dict):
        """
        Initialize metrics collector.

        Args:
            config: Metrics configuration dictionary
        """
        self.config = config
        self.prometheus_port = config.get('prometheus_port', 8000)
        self.output_dir = Path(config.get('output_dir', '/results'))
        self.export_json = config.get('export_json', True)
        self.export_csv = config.get('export_csv', True)
        self.stream_detailed_csv = config.get('stream_detailed_csv', False)
        self.max_latency_samples = config.get('max_latency_samples', 0)
        self.latency_buckets = config.get('latency_buckets',
                                         [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])

        # Thread-safe storage for metrics
        self.lock = threading.Lock()
        self.latency_samples = defaultdict(list)  # operation_type -> sample list of latencies
        self.latency_total_counts = defaultdict(int)
        self.latency_sums = defaultdict(float)
        self.latency_mins = {}
        self.latency_maxs = {}
        self.operation_counts = defaultdict(lambda: {'success': 0, 'error': 0})
        self.error_type_counts = defaultdict(lambda: defaultdict(int))

        # Prometheus metrics
        self._setup_prometheus_metrics()

        # HTTP server for Prometheus
        self.http_server_started = False
        self.base_filename: Optional[str] = None
        self._detailed_file = None
        self._detailed_writer = None

    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics."""
        # Histogram for operation latencies
        self.latency_histogram = Histogram(
            'operation_latency_seconds',
            'Operation latency in seconds',
            ['operation_type'],
            buckets=self.latency_buckets
        )

        # Counter for operations
        self.operations_counter = Counter(
            'operations_total',
            'Total number of operations',
            ['operation_type', 'status']
        )

        # Gauge for active connections
        self.active_connections_gauge = Gauge(
            'active_connections',
            'Number of active database connections'
        )

        # Summary for throughput tracking
        self.throughput_summary = Summary(
            'throughput_ops_per_second',
            'Operations per second'
        )

    def start_http_server(self):
        """Start HTTP server for Prometheus metrics endpoint."""
        if not self.http_server_started:
            try:
                start_http_server(self.prometheus_port)
                self.http_server_started = True
                logger.info(f"Prometheus metrics server started on port {self.prometheus_port}")
            except Exception as e:
                logger.error(f"Failed to start metrics HTTP server: {e}")

    def start_run(self, test_config: dict):
        """Initialize run metadata and optional streaming outputs."""
        indexed = "indexed" if test_config.get('indexed', False) else "no_index"
        ratio = test_config.get('read_write_ratio', [90, 10])
        concurrency = test_config.get('concurrency', 4)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")

        self.base_filename = f"{indexed}_r{ratio[0]}w{ratio[1]}_c{concurrency}_{timestamp}"

        if self.export_csv and self.stream_detailed_csv:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            csv_file = self.output_dir / f"{self.base_filename}_detailed.csv"
            self._detailed_file = open(csv_file, 'w', newline='')
            self._detailed_writer = csv.writer(self._detailed_file)
            self._detailed_writer.writerow(['operation_type', 'latency_seconds', 'latency_ms'])
            logger.info(f"Streaming detailed latencies to {csv_file}")

    def record_operation(self, operation_type: str, latency: float, success: bool,
                         error_type: Optional[str] = None):
        """
        Record a single operation result.

        Args:
            operation_type: Type of operation (point_lookup, range_scan, etc.)
            latency: Operation latency in seconds
            success: Whether the operation succeeded
        """
        # Update Prometheus metrics
        self.latency_histogram.labels(operation_type=operation_type).observe(latency)
        status = 'success' if success else 'error'
        self.operations_counter.labels(operation_type=operation_type, status=status).inc()

        # Store metrics data for offline analysis
        with self.lock:
            self.operation_counts[operation_type][status] += 1
            self.latency_total_counts[operation_type] += 1
            self.latency_sums[operation_type] += latency
            current_min = self.latency_mins.get(operation_type)
            current_max = self.latency_maxs.get(operation_type)
            self.latency_mins[operation_type] = latency if current_min is None else min(current_min, latency)
            self.latency_maxs[operation_type] = latency if current_max is None else max(current_max, latency)

            if self.max_latency_samples and self.max_latency_samples > 0:
                samples = self.latency_samples[operation_type]
                total_seen = self.latency_total_counts[operation_type]
                if len(samples) < self.max_latency_samples:
                    samples.append(latency)
                else:
                    j = random.randint(1, total_seen)
                    if j <= self.max_latency_samples:
                        samples[random.randint(0, self.max_latency_samples - 1)] = latency
            else:
                self.latency_samples[operation_type].append(latency)

            if not success:
                normalized_error = error_type if error_type in ERROR_TYPES else "other"
                self.error_type_counts[operation_type][normalized_error] += 1

            if self._detailed_writer is not None:
                self._detailed_writer.writerow([operation_type, latency, latency * 1000])

    def set_active_connections(self, count: int):
        """Update active connections gauge."""
        self.active_connections_gauge.set(count)

    def get_summary_statistics(self) -> dict:
        """
        Calculate summary statistics from collected data.

        Returns:
            Dictionary with summary statistics per operation type
        """
        with self.lock:
            summary = {}

            for op_type, total_count in self.latency_total_counts.items():
                if total_count == 0:
                    continue

                samples = self.latency_samples.get(op_type, [])
                if not samples:
                    continue

                sorted_latencies = sorted(samples)
                n = len(sorted_latencies)

                def percentile(p):
                    k = (n - 1) * p / 100
                    f = int(k)
                    c = f + 1 if (f + 1) < n else f
                    if f == c:
                        return sorted_latencies[f]
                    return sorted_latencies[f] * (c - k) + sorted_latencies[c] * (k - f)

                counts = self.operation_counts[op_type]
                error_types = self.error_type_counts.get(op_type, {})
                error_type_summary = {
                    error_type: error_types.get(error_type, 0)
                    for error_type in ERROR_TYPES
                }

                summary[op_type] = {
                    'count': total_count,
                    'success': counts['success'],
                    'error': counts['error'],
                    'min_latency_ms': self.latency_mins[op_type] * 1000,
                    'max_latency_ms': self.latency_maxs[op_type] * 1000,
                    'mean_latency_ms': (self.latency_sums[op_type] / total_count) * 1000,
                    'p50_latency_ms': percentile(50) * 1000,
                    'p95_latency_ms': percentile(95) * 1000,
                    'p99_latency_ms': percentile(99) * 1000,
                    'errors_by_type': error_type_summary,
                }

            return summary

    def export_results(self, test_config: dict, duration: float) -> dict:
        """
        Export results to JSON and CSV files.

        Args:
            test_config: Test configuration dictionary
            duration: Test duration in seconds

        Returns:
            Summary statistics dictionary
        """
        summary = self.get_summary_statistics()

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename base from config
        if self.base_filename is None:
            indexed = "indexed" if test_config.get('indexed', False) else "no_index"
            ratio = test_config.get('read_write_ratio', [90, 10])
            concurrency = test_config.get('concurrency', 4)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
            self.base_filename = f"{indexed}_r{ratio[0]}w{ratio[1]}_c{concurrency}_{timestamp}"

        base_filename = self.base_filename

        for stats in summary.values():
            stats['ops_per_sec'] = stats['count'] / duration if duration > 0 else 0.0

        # Export JSON
        if self.export_json:
            json_file = self.output_dir / f"{base_filename}.json"
            result_data = {
                'config': test_config,
                'duration_seconds': duration,
                'summary': summary,
                'total_operations': sum(s['count'] for s in summary.values()),
                'operations_per_second': sum(s['count'] for s in summary.values()) / duration
            }

            with open(json_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            logger.info(f"Results exported to {json_file}")

        # Export CSV (detailed latencies)
        if self.export_csv and not self.stream_detailed_csv:
            csv_file = self.output_dir / f"{base_filename}_detailed.csv"

            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['operation_type', 'latency_seconds', 'latency_ms'])

                with self.lock:
                    for op_type, latencies in self.latency_samples.items():
                        for latency in latencies:
                            writer.writerow([op_type, latency, latency * 1000])

            logger.info(f"Detailed latencies exported to {csv_file}")

        # Export summary CSV
        summary_csv = self.output_dir / f"{base_filename}_summary.csv"
        with open(summary_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'operation_type', 'count', 'success', 'error',
                'min_ms', 'max_ms', 'mean_ms', 'p50_ms', 'p95_ms', 'p99_ms',
                'ops_per_sec', 'timeout_statement', 'timeout_lock', 'deadlock', 'other'
            ])

            for op_type, stats in summary.items():
                error_types = stats.get('errors_by_type', {})
                writer.writerow([
                    op_type,
                    stats['count'],
                    stats['success'],
                    stats['error'],
                    f"{stats['min_latency_ms']:.3f}",
                    f"{stats['max_latency_ms']:.3f}",
                    f"{stats['mean_latency_ms']:.3f}",
                    f"{stats['p50_latency_ms']:.3f}",
                    f"{stats['p95_latency_ms']:.3f}",
                    f"{stats['p99_latency_ms']:.3f}",
                    f"{stats['ops_per_sec']:.3f}",
                    error_types.get('timeout_statement', 0),
                    error_types.get('timeout_lock', 0),
                    error_types.get('deadlock', 0),
                    error_types.get('other', 0),
                ])

        logger.info(f"Summary exported to {summary_csv}")

        return summary

    def close(self):
        """Close any open resources."""
        if self._detailed_file is not None:
            try:
                self._detailed_file.close()
            finally:
                self._detailed_file = None
                self._detailed_writer = None

    def print_summary(self, summary: dict, duration: float):
        """Print summary statistics to console."""
        print("\n" + "=" * 80)
        print("BENCHMARK RESULTS SUMMARY")
        print("=" * 80)

        total_ops = sum(s['count'] for s in summary.values())
        total_errors = sum(s['error'] for s in summary.values())
        throughput = total_ops / duration

        print(f"\nOverall:")
        print(f"  Duration: {duration:.2f} seconds")
        print(f"  Total Operations: {total_ops:,}")
        print(f"  Successful: {total_ops - total_errors:,}")
        print(f"  Errors: {total_errors:,}")
        print(f"  Throughput: {throughput:.2f} ops/sec")

        print("\nPer-Operation Latency (milliseconds):")
        print(f"{'Operation':<20} {'Count':>10} {'Min':>8} {'Mean':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8}")
        print("-" * 100)

        for op_type, stats in sorted(summary.items()):
            print(f"{op_type:<20} {stats['count']:>10,} "
                  f"{stats['min_latency_ms']:>8.2f} "
                  f"{stats['mean_latency_ms']:>8.2f} "
                  f"{stats['p50_latency_ms']:>8.2f} "
                  f"{stats['p95_latency_ms']:>8.2f} "
                  f"{stats['p99_latency_ms']:>8.2f} "
                  f"{stats['max_latency_ms']:>8.2f}")

        print("=" * 80 + "\n")
