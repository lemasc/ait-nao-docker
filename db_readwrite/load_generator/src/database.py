"""
Database module for PostgreSQL connection management, schema setup, and data loading.
"""

import logging
import random
import string
import time
from io import StringIO
from typing import Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


class Database:
    """Manages PostgreSQL connections and schema operations."""

    def __init__(self, config: dict):
        """
        Initialize database manager.

        Args:
            config: Database configuration dictionary with keys:
                   - host, port, name, user, password, pool_size
        """
        self.config = config
        self.pool: Optional[ConnectionPool] = None
        self.conninfo = (
            f"host={config['host']} "
            f"port={config['port']} "
            f"dbname={config['name']} "
            f"user={config['user']} "
            f"password={config['password']}"
        )

    def connect(self, min_pool_size: Optional[int] = None):
        """Create connection pool."""
        pool_size = self.config.get('pool_size', 10)
        if min_pool_size is not None and pool_size < min_pool_size:
            logger.warning(
                "Configured pool_size %s is below requested minimum %s; increasing.",
                pool_size,
                min_pool_size
            )
            pool_size = min_pool_size
        logger.info(f"Creating connection pool with size {pool_size}")
        self.pool = ConnectionPool(
            self.conninfo,
            min_size=pool_size,
            max_size=pool_size * 2,
            open=True,
            check=ConnectionPool.check_connection
        )
        logger.info("Connection pool created successfully")

    def close(self):
        """Close connection pool."""
        if self.pool:
            logger.info("Closing connection pool")
            self.pool.close()
            self.pool = None

    def get_connection(self):
        """Get a connection from the pool."""
        if not self.pool:
            raise RuntimeError("Connection pool not initialized. Call connect() first.")
        return self.pool.connection()

    def setup_schema(self, drop_if_exists: bool = True):
        """
        Create the benchmark table schema.

        Args:
            drop_if_exists: If True, drop existing table before creating
        """
        logger.info("Setting up database schema")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if drop_if_exists:
                    logger.info("Dropping existing table if exists")
                    cur.execute("DROP TABLE IF EXISTS test_table CASCADE")

                logger.info("Creating test_table")
                if drop_if_exists:
                    cur.execute("""
                        CREATE TABLE test_table (
                            id BIGSERIAL PRIMARY KEY,
                            indexed_col INTEGER NOT NULL,
                            payload TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                else:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS test_table (
                            id BIGSERIAL PRIMARY KEY,
                            indexed_col INTEGER NOT NULL,
                            payload TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                conn.commit()

        logger.info("Schema setup completed")

    def create_index(self):
        """Create B-tree index on indexed_col."""
        logger.info("Creating B-tree index on indexed_col")
        start_time = time.time()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_test_table_indexed_col
                    ON test_table (indexed_col)
                """)
                conn.commit()

        duration = time.time() - start_time
        logger.info(f"Index created in {duration:.2f} seconds")

    def drop_index(self):
        """Drop B-tree index on indexed_col."""
        logger.info("Dropping index on indexed_col")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DROP INDEX IF EXISTS idx_test_table_indexed_col")
                conn.commit()

        logger.info("Index dropped")

    def load_data(
        self,
        num_rows: int,
        payload_size_bytes: int = 1024,
        batch_size: int = 10000,
        truncate_first: bool = True
    ):
        """
        Load initial dataset into test_table.

        Args:
            num_rows: Number of rows to insert
            payload_size_bytes: Size of payload field in bytes
            batch_size: Number of rows per batch insert
        """
        logger.info(f"Loading {num_rows} rows of data (payload size: {payload_size_bytes} bytes)")
        start_time = time.time()

        # Generate a sample payload string
        payload_template = ''.join(random.choices(string.ascii_letters + string.digits, k=payload_size_bytes))

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if truncate_first:
                    cur.execute("TRUNCATE test_table")

                rows_inserted = 0

                with cur.copy("COPY test_table (indexed_col, payload) FROM STDIN") as copy:
                    while rows_inserted < num_rows:
                        current_batch = min(batch_size, num_rows - rows_inserted)

                        # Prepare batch data for COPY
                        # indexed_col: distributed across a range for realistic queries
                        buffer = StringIO()
                        for _ in range(current_batch):
                            indexed_value = random.randint(0, num_rows * 2)
                            buffer.write(f"{indexed_value}\t{payload_template}\n")
                        copy.write(buffer.getvalue())

                        rows_inserted += current_batch

                        if rows_inserted % 100000 == 0:
                            logger.info(f"  Loaded {rows_inserted}/{num_rows} rows")

                conn.commit()

        duration = time.time() - start_time
        rows_per_sec = num_rows / duration
        logger.info(f"Data loading completed: {num_rows} rows in {duration:.2f}s ({rows_per_sec:.0f} rows/sec)")

    def vacuum_analyze(self):
        """Run VACUUM ANALYZE on test_table."""
        logger.info("Running VACUUM ANALYZE")
        start_time = time.time()

        # VACUUM cannot run inside a transaction block
        with self.get_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("VACUUM ANALYZE test_table")

        duration = time.time() - start_time
        logger.info(f"VACUUM ANALYZE completed in {duration:.2f} seconds")

    def get_table_stats(self) -> dict:
        """
        Get statistics about test_table.

        Returns:
            Dictionary with table statistics
        """
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Get row count
                cur.execute("SELECT COUNT(*) as row_count FROM test_table")
                row_count = cur.fetchone()['row_count']

                # Get table size
                cur.execute("""
                    SELECT
                        pg_size_pretty(pg_total_relation_size('test_table')) as total_size,
                        pg_size_pretty(pg_relation_size('test_table')) as table_size,
                        pg_size_pretty(pg_indexes_size('test_table')) as indexes_size
                """)
                sizes = cur.fetchone()

                # Check if index exists
                cur.execute("""
                    SELECT COUNT(*) as index_exists
                    FROM pg_indexes
                    WHERE tablename = 'test_table' AND indexname = 'idx_test_table_indexed_col'
                """)
                index_exists = cur.fetchone()['index_exists'] > 0

                return {
                    'row_count': row_count,
                    'total_size': sizes['total_size'],
                    'table_size': sizes['table_size'],
                    'indexes_size': sizes['indexes_size'],
                    'index_exists': index_exists
                }

    def get_min_max_id(self) -> tuple[int, int]:
        """Get minimum and maximum id values from test_table."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(id), MAX(id) FROM test_table")
                result = cur.fetchone()
                return result[0], result[1]

    def get_indexed_col_range(self) -> tuple[int, int]:
        """Get minimum and maximum indexed_col values from test_table."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(indexed_col), MAX(indexed_col) FROM test_table")
                result = cur.fetchone()
                return result[0], result[1]
