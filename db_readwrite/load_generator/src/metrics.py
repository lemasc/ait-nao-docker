"""
Metrics collection and export module using Prometheus client.
"""

import csv
import json
import logging
import threading
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server

logger = logging.getLogger(__name__)


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
        self.latency_buckets = config.get('latency_buckets',
                                         [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])

        # Thread-safe storage for detailed metrics
        self.lock = threading.Lock()
        self.latencies = defaultdict(list)  # operation_type -> list of latencies
        self.operation_counts = defaultdict(lambda: {'success': 0, 'error': 0})

        # Prometheus metrics
        self._setup_prometheus_metrics()

        # HTTP server for Prometheus
        self.http_server_started = False

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

    def record_operation(self, operation_type: str, latency: float, success: bool):
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

        # Store detailed data for offline analysis
        with self.lock:
            self.latencies[operation_type].append(latency)
            self.operation_counts[operation_type][status] += 1

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

            for op_type, latencies in self.latencies.items():
                if not latencies:
                    continue

                sorted_latencies = sorted(latencies)
                n = len(sorted_latencies)

                def percentile(p):
                    k = (n - 1) * p / 100
                    f = int(k)
                    c = f + 1 if (f + 1) < n else f
                    if f == c:
                        return sorted_latencies[f]
                    return sorted_latencies[f] * (c - k) + sorted_latencies[c] * (k - f)

                counts = self.operation_counts[op_type]

                summary[op_type] = {
                    'count': n,
                    'success': counts['success'],
                    'error': counts['error'],
                    'min_latency_ms': min(latencies) * 1000,
                    'max_latency_ms': max(latencies) * 1000,
                    'mean_latency_ms': (sum(latencies) / n) * 1000,
                    'p50_latency_ms': percentile(50) * 1000,
                    'p95_latency_ms': percentile(95) * 1000,
                    'p99_latency_ms': percentile(99) * 1000,
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
        indexed = "indexed" if test_config.get('indexed', False) else "no_index"
        ratio = test_config.get('read_write_ratio', [90, 10])
        concurrency = test_config.get('concurrency', 4)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")

        base_filename = f"{indexed}_r{ratio[0]}w{ratio[1]}_c{concurrency}_{timestamp}"

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
        if self.export_csv:
            csv_file = self.output_dir / f"{base_filename}_detailed.csv"

            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['operation_type', 'latency_seconds', 'latency_ms'])

                with self.lock:
                    for op_type, latencies in self.latencies.items():
                        for latency in latencies:
                            writer.writerow([op_type, latency, latency * 1000])

            logger.info(f"Detailed latencies exported to {csv_file}")

        # Export summary CSV
        summary_csv = self.output_dir / f"{base_filename}_summary.csv"
        with open(summary_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'operation_type', 'count', 'success', 'error',
                'min_ms', 'max_ms', 'mean_ms', 'p50_ms', 'p95_ms', 'p99_ms'
            ])

            for op_type, stats in summary.items():
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
                ])

        logger.info(f"Summary exported to {summary_csv}")

        return summary

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
