#!/usr/bin/env python3
"""
Generate test data for database performance evaluation.

This script generates realistic user data with Faker library and computes
a Zipfian distribution (α=0.99) for hot data access patterns.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
import random

import psycopg2
from psycopg2.extras import execute_values
from faker import Faker
import numpy as np


# Pre-generated data pools (populated at startup)
NAME_POOL = []
METADATA_POOL = []


def connect_to_database():
    """Connect to PostgreSQL database."""
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME', 'perftest'),
        user=os.getenv('DB_USER', 'testuser'),
        password=os.getenv('DB_PASSWORD', 'testpass')
    )
    return conn


def initialize_data_pools(fake, name_pool_size=100_000):
    """Pre-generate data pools to eliminate Faker overhead from hot path."""
    global NAME_POOL, METADATA_POOL

    print("Pre-generating data pools...")

    # Generate name pool (most expensive Faker operation)
    NAME_POOL = [fake.name() for _ in range(name_pool_size)]
    print(f"  ✓ Generated {len(NAME_POOL):,} names")

    # Pre-serialize all metadata combinations
    # 3 sources × 2 newsletter × 3 notifications × 101 scores = 1,818 combinations
    METADATA_POOL = []
    for source in ['web', 'mobile', 'api']:
        for newsletter in [True, False]:
            for notif in ['all', 'important', 'none']:
                for score in range(0, 1001, 10):  # 101 score values
                    METADATA_POOL.append(json.dumps({
                        'signup_source': source,
                        'preferences': {
                            'newsletter': newsletter,
                            'notifications': notif
                        },
                        'score': score
                    }))
    print(f"  ✓ Generated {len(METADATA_POOL):,} metadata variations")


def truncate_users_table(conn):
    """Truncate users table to start fresh."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE;")
    conn.commit()
    print("✓ Users table truncated")


def generate_users_batch(batch_size, start_id):
    """Generate a batch of user records using pre-generated pools."""
    users = []
    base_date = datetime(2020, 1, 1)
    statuses = ['active', 'inactive', 'suspended']
    name_pool_size = len(NAME_POOL)
    metadata_pool_size = len(METADATA_POOL)

    for i in range(batch_size):
        user_id = start_id + i
        email = f"user{user_id}@example.com"
        # Fast array lookup instead of Faker call
        name = NAME_POOL[user_id % name_pool_size]
        created_at = base_date + timedelta(days=random.randint(0, 1460))
        # Pre-serialized JSON lookup instead of json.dumps
        metadata = METADATA_POOL[random.randint(0, metadata_pool_size - 1)]
        status = statuses[random.randint(0, 2)]

        users.append((email, name, created_at, metadata, status))

    return users


def insert_users_batch(conn, users, commit=True):
    """Insert batch of users into database using execute_values (5-10x faster than executemany)."""
    with conn.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO users (email, name, created_at, metadata, status) VALUES %s""",
            users,
            page_size=10000
        )
    if commit:
        conn.commit()


def generate_zipfian_distribution(table_size, alpha=0.99):
    """
    Generate Zipfian distribution for hot data access patterns.

    Args:
        table_size: Total number of users
        alpha: Zipfian exponent (0.99 for very skewed distribution)

    Returns:
        dict: Hot users configuration with user IDs and probabilities
    """
    # Calculate top 1% of users (hot data)
    hot_count = max(int(table_size * 0.01), 100)

    # Generate Zipfian probabilities
    # Using power law: probability proportional to 1 / (rank ^ alpha)
    ranks = np.arange(1, hot_count + 1)
    probabilities = 1.0 / np.power(ranks, alpha)
    probabilities = probabilities / probabilities.sum()  # Normalize

    # User IDs start from 1
    hot_user_ids = list(range(1, hot_count + 1))

    return {
        'user_ids': hot_user_ids,
        'probabilities': probabilities.tolist(),
        'alpha': alpha,
        'total_users': table_size,
        'hot_count': hot_count,
        'generated_at': datetime.now().isoformat()
    }


def save_hot_users_config(hot_users_config, output_path):
    """Save hot users configuration to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(hot_users_config, f, indent=2)
    print(f"✓ Hot users configuration saved to {output_path}")
    print(f"  - Top {hot_users_config['hot_count']} users (1% of dataset)")
    print(f"  - Zipfian α={hot_users_config['alpha']}")
    print(f"  - Top user probability: {hot_users_config['probabilities'][0]:.4%}")


def main():
    parser = argparse.ArgumentParser(description='Generate test data for database performance evaluation')
    parser.add_argument('--table-size', type=int, default=1000000,
                        choices=[1000000, 10000000],
                        help='Number of users to generate (1M or 10M)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for reproducibility')
    parser.add_argument('--batch-size', type=int, default=50000,
                        help='Insert batch size (default: 50000)')
    parser.add_argument('--commit-interval', type=int, default=200000,
                        help='Commit every N rows (default: 200000)')

    args = parser.parse_args()

    # Set random seeds for reproducibility
    random.seed(args.seed)
    np.random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker()

    print("=" * 60)
    print("Database Performance Evaluation - Data Generation")
    print("=" * 60)
    print(f"Table size: {args.table_size:,} rows")
    print(f"Batch size: {args.batch_size:,} rows")
    print(f"Commit interval: {args.commit_interval:,} rows")
    print(f"Random seed: {args.seed}")
    print()

    # Pre-generate data pools (eliminates Faker overhead from hot path)
    initialize_data_pools(fake)

    # Connect to database
    print("Connecting to database...")
    try:
        conn = connect_to_database()
        print("✓ Connected to PostgreSQL")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        sys.exit(1)

    try:
        # Truncate existing data
        truncate_users_table(conn)

        # Generate and insert data
        total_inserted = 0
        start_time = datetime.now()

        print(f"\nGenerating and inserting {args.table_size:,} users...")
        print("Progress: ", end='', flush=True)

        last_commit = 0
        while total_inserted < args.table_size:
            # Generate batch
            batch_size = min(args.batch_size, args.table_size - total_inserted)
            users = generate_users_batch(batch_size, total_inserted + 1)

            # Insert batch (commit only at intervals)
            should_commit = (total_inserted + batch_size - last_commit) >= args.commit_interval
            insert_users_batch(conn, users, commit=should_commit)
            total_inserted += batch_size

            if should_commit:
                last_commit = total_inserted

            # Progress indicator
            if total_inserted % 100000 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = total_inserted / elapsed
                print(f"{total_inserted:,} ({rate:.0f} rows/sec)", end=' ', flush=True)

        # Final commit for any remaining uncommitted data
        conn.commit()
        print()

        # Final statistics
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n✓ Inserted {total_inserted:,} users in {elapsed:.1f} seconds")
        print(f"  Average rate: {total_inserted / elapsed:.0f} rows/second")

        # Verify count
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users;")
            count = cur.fetchone()[0]
            print(f"  Database count: {count:,} rows")

        # Generate Zipfian distribution for hot data
        print("\nGenerating Zipfian distribution for query workload...")
        hot_users_config = generate_zipfian_distribution(args.table_size, alpha=0.99)

        # Save configuration
        output_path = '/app/results/hot_users.json'
        save_hot_users_config(hot_users_config, output_path)

        print("\n" + "=" * 60)
        print("Data generation completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error during data generation: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
