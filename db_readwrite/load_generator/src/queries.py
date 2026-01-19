"""
Query templates and execution functions for the benchmark workload.
"""

import logging
import random
import string
import time
from collections import Counter
from typing import Literal, Optional

import psycopg

OperationType = Literal["point_lookup", "range_scan", "range_order", "insert", "update"]


class QueryExecutor:
    """Executes query templates against the database."""

    def __init__(self, id_range: tuple[int, int], indexed_col_range: tuple[int, int],
                 range_scan_size: int = 100, payload_size_bytes: int = 1024):
        """
        Initialize query executor.

        Args:
            id_range: Tuple of (min_id, max_id) for update operations
            indexed_col_range: Tuple of (min_val, max_val) for indexed_col queries
            range_scan_size: LIMIT for range queries
            payload_size_bytes: Size of payload for inserts/updates
        """
        self.min_id, self.max_id = id_range
        self.min_indexed_col, self.max_indexed_col = indexed_col_range
        self.range_scan_size = range_scan_size
        self.payload_size_bytes = payload_size_bytes
        self._error_counts = Counter()
        self._error_last_log = {}
        self._error_log_interval_s = 5.0

        # Pre-generate payload template for better performance
        self.payload_template = ''.join(
            random.choices(string.ascii_letters + string.digits, k=payload_size_bytes)
        )

    def _log_error(self, operation_type: str, exc: Exception) -> None:
        key = (operation_type, exc.__class__.__name__, str(exc))
        self._error_counts[key] += 1

        now = time.monotonic()
        last = self._error_last_log.get(operation_type, 0.0)
        if now - last < self._error_log_interval_s:
            return

        self._error_last_log[operation_type] = now
        logger = logging.getLogger(__name__)
        logger.warning(
            "Operation %s error sample: %s: %s (count=%d)",
            operation_type,
            exc.__class__.__name__,
            exc,
            self._error_counts[key],
        )

    def _classify_error(self, exc: Exception) -> str:
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == "57014":
            return "timeout_statement"
        if sqlstate == "55P03":
            return "timeout_lock"
        if sqlstate == "40P01":
            return "deadlock"
        if isinstance(exc, psycopg.errors.QueryCanceled):
            return "timeout_statement"
        if isinstance(exc, psycopg.errors.DeadlockDetected):
            return "deadlock"
        return "other"

    def execute_point_lookup(self, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute point lookup query.

        Returns:
            Tuple of (latency_seconds, success)
        """
        value = random.randint(self.min_indexed_col, self.max_indexed_col)

        start = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM test_table WHERE indexed_col = %s",
                    (value,)
                )
                result = cur.fetchall()
            latency = time.perf_counter() - start
            return latency, True, None
        except Exception as e:
            self._log_error("point_lookup", e)
            try:
                conn.rollback()
            except Exception:
                pass
            latency = time.perf_counter() - start
            return latency, False, self._classify_error(e)

    def execute_range_scan(self, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute range scan query.

        Returns:
            Tuple of (latency_seconds, success)
        """
        # Generate a range
        range_width = (self.max_indexed_col - self.min_indexed_col) // 10
        start_val = random.randint(self.min_indexed_col, self.max_indexed_col - range_width)
        end_val = start_val + range_width

        start = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM test_table WHERE indexed_col BETWEEN %s AND %s LIMIT %s",
                    (start_val, end_val, self.range_scan_size)
                )
                result = cur.fetchall()
            latency = time.perf_counter() - start
            return latency, True, None
        except Exception as e:
            self._log_error("range_scan", e)
            try:
                conn.rollback()
            except Exception:
                pass
            latency = time.perf_counter() - start
            return latency, False, self._classify_error(e)

    def execute_range_order(self, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute range scan with ORDER BY query.

        Returns:
            Tuple of (latency_seconds, success)
        """
        # Generate a range
        range_width = (self.max_indexed_col - self.min_indexed_col) // 10
        start_val = random.randint(self.min_indexed_col, self.max_indexed_col - range_width)
        end_val = start_val + range_width

        start = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM test_table WHERE indexed_col BETWEEN %s AND %s ORDER BY indexed_col LIMIT %s",
                    (start_val, end_val, self.range_scan_size)
                )
                result = cur.fetchall()
            latency = time.perf_counter() - start
            return latency, True, None
        except Exception as e:
            self._log_error("range_order", e)
            try:
                conn.rollback()
            except Exception:
                pass
            latency = time.perf_counter() - start
            return latency, False, self._classify_error(e)

    def execute_insert(self, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute INSERT operation.

        Returns:
            Tuple of (latency_seconds, success)
        """
        indexed_col_value = random.randint(self.min_indexed_col, self.max_indexed_col * 2)

        start = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO test_table (indexed_col, payload) VALUES (%s, %s)",
                    (indexed_col_value, self.payload_template)
                )
            conn.commit()
            latency = time.perf_counter() - start
            return latency, True, None
        except Exception as e:
            self._log_error("insert", e)
            conn.rollback()
            latency = time.perf_counter() - start
            return latency, False, self._classify_error(e)

    def execute_update(self, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute UPDATE operation (payload only).

        Returns:
            Tuple of (latency_seconds, success)
        """
        target_id = random.randint(self.min_id, self.max_id)
        new_payload = self.payload_template[::-1]  # Simple variation

        start = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE test_table SET payload = %s WHERE id = %s",
                    (new_payload, target_id)
                )
            conn.commit()
            latency = time.perf_counter() - start
            return latency, True, None
        except Exception as e:
            self._log_error("update", e)
            conn.rollback()
            latency = time.perf_counter() - start
            return latency, False, self._classify_error(e)

    def execute_operation(self, operation_type: OperationType, conn) -> tuple[float, bool, Optional[str]]:
        """
        Execute the specified operation type.

        Args:
            operation_type: Type of operation to execute
            conn: Database connection

        Returns:
            Tuple of (latency_seconds, success, error_type)
        """
        if operation_type == "point_lookup":
            return self.execute_point_lookup(conn)
        elif operation_type == "range_scan":
            return self.execute_range_scan(conn)
        elif operation_type == "range_order":
            return self.execute_range_order(conn)
        elif operation_type == "insert":
            return self.execute_insert(conn)
        elif operation_type == "update":
            return self.execute_update(conn)
        else:
            raise ValueError(f"Unknown operation type: {operation_type}")
