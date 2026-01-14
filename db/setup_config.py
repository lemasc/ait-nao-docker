#!/usr/bin/env python3
"""
Setup database configuration for performance testing.

This script manages indexes and cache state for different test configurations:
- no_index: Drop all indexes except primary key
- btree_index: Create B-tree indexes on email and created_at
- redis_cache: Create B-tree indexes + flush Redis cache
"""

import argparse
import os
import sys
import time

import psycopg2
import redis


def connect_to_database():
    """Connect to PostgreSQL database."""
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME', 'perftest'),
        user=os.getenv('DB_USER', 'testuser'),
        password=os.getenv('DB_PASSWORD', 'testpass')
    )
    conn.autocommit = True  # Required for VACUUM ANALYZE
    # Disable statement timeout for long-running maintenance operations
    # (CREATE INDEX, VACUUM ANALYZE can take minutes on large tables)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0;")
    return conn


def connect_to_redis():
    """Connect to Redis cache."""
    r = redis.Redis(
        host=os.getenv('REDIS_HOST', 'redis'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        decode_responses=True
    )
    return r


def drop_indexes(conn):
    """Drop all indexes except primary key."""
    print("Dropping indexes...")
    with conn.cursor() as cur:
        # Drop email index if exists
        cur.execute("DROP INDEX IF EXISTS idx_users_email;")
        print("  ✓ Dropped idx_users_email")

        # Drop created_at index if exists
        cur.execute("DROP INDEX IF EXISTS idx_users_created_at;")
        print("  ✓ Dropped idx_users_created_at")


def create_indexes(conn):
    """Create B-tree indexes on email and created_at columns."""
    print("Creating B-tree indexes...")
    with conn.cursor() as cur:
        # Create email index (use CONCURRENTLY to avoid table locking)
        cur.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON users(email);")
        print("  ✓ Created idx_users_email")

        # Create created_at index
        cur.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_created_at ON users(created_at);")
        print("  ✓ Created idx_users_created_at")


def flush_redis_cache(redis_conn):
    """Flush all keys from Redis cache."""
    print("Flushing Redis cache...")
    redis_conn.flushall()
    print("  ✓ Redis cache flushed")


def vacuum_analyze(conn):
    """Update PostgreSQL statistics."""
    print("Running VACUUM ANALYZE...")
    with conn.cursor() as cur:
        cur.execute("VACUUM ANALYZE users;")
    print("  ✓ Statistics updated")


def verify_configuration(conn, config_type):
    """Verify that configuration is set up correctly."""
    print("\nVerifying configuration...")

    with conn.cursor() as cur:
        # Check existing indexes
        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'users'
            AND indexname != 'users_pkey'
            ORDER BY indexname;
        """)
        indexes = [row[0] for row in cur.fetchall()]

        if config_type == 'no_index':
            if len(indexes) == 0:
                print("  ✓ No indexes present (expected for no_index)")
            else:
                print(f"  ✗ Warning: Found {len(indexes)} indexes: {indexes}")
                return False

        elif config_type in ['btree_index', 'redis_cache']:
            expected = {'idx_users_email', 'idx_users_created_at'}
            actual = set(indexes)

            if actual == expected:
                print(f"  ✓ Indexes present: {', '.join(sorted(indexes))}")
            else:
                missing = expected - actual
                extra = actual - expected
                if missing:
                    print(f"  ✗ Missing indexes: {missing}")
                if extra:
                    print(f"  ✗ Extra indexes: {extra}")
                return False

        # Get table statistics
        cur.execute("""
            SELECT
                n_live_tup,
                n_dead_tup,
                last_vacuum,
                last_analyze
            FROM pg_stat_user_tables
            WHERE relname = 'users';
        """)
        stats = cur.fetchone()
        if stats:
            n_live, n_dead, last_vac, last_analyze = stats
            print(f"  ✓ Live tuples: {n_live:,}")
            print(f"  ✓ Dead tuples: {n_dead:,}")

    return True


def main():
    parser = argparse.ArgumentParser(description='Setup database configuration for performance testing')
    parser.add_argument('--config', type=str, required=True,
                        choices=['no_index', 'btree_index', 'redis_cache'],
                        help='Configuration type')

    args = parser.parse_args()

    print("=" * 60)
    print("Database Performance Evaluation - Configuration Setup")
    print("=" * 60)
    print(f"Configuration: {args.config}")
    print()

    # Connect to PostgreSQL
    print("Connecting to PostgreSQL...")
    try:
        pg_conn = connect_to_database()
        print("✓ Connected to PostgreSQL")
    except Exception as e:
        print(f"✗ Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    # Connect to Redis (if needed)
    redis_conn = None
    if args.config == 'redis_cache':
        print("Connecting to Redis...")
        try:
            redis_conn = connect_to_redis()
            redis_conn.ping()
            print("✓ Connected to Redis")
        except Exception as e:
            print(f"✗ Failed to connect to Redis: {e}")
            pg_conn.close()
            sys.exit(1)

    try:
        print()

        # Apply configuration
        if args.config == 'no_index':
            # Drop all indexes
            drop_indexes(pg_conn)

        elif args.config == 'btree_index':
            # Drop existing indexes first (for clean state)
            drop_indexes(pg_conn)
            time.sleep(1)
            # Create B-tree indexes
            create_indexes(pg_conn)

        elif args.config == 'redis_cache':
            # Drop existing indexes first (for clean state)
            drop_indexes(pg_conn)
            time.sleep(1)
            # Create B-tree indexes
            create_indexes(pg_conn)
            # Flush Redis cache
            flush_redis_cache(redis_conn)

        print()

        # Update PostgreSQL statistics
        vacuum_analyze(pg_conn)

        # Verify configuration
        if verify_configuration(pg_conn, args.config):
            print("\n" + "=" * 60)
            print(f"Configuration '{args.config}' applied successfully!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("Configuration verification failed!")
            print("=" * 60)
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ Error during configuration setup: {e}")
        sys.exit(1)
    finally:
        pg_conn.close()
        if redis_conn:
            redis_conn.close()


if __name__ == '__main__':
    main()
