"""
Main entry point for the PostgreSQL benchmark load generator.
"""

import logging
import sys
import time

from .config import load_config, parse_args, setup_logging, validate_config
from .database import Database
from .metrics import MetricsCollector
from .workload import WorkloadExecutor

logger = logging.getLogger(__name__)


def main():
    """Main execution function."""
    # Parse arguments and setup logging
    args = parse_args()
    setup_logging(args.log_level)

    logger.info("=" * 80)
    logger.info("PostgreSQL Performance Benchmark Load Generator")
    logger.info("=" * 80)

    try:
        # Load and validate configuration
        config = load_config(args.config)
        validate_config(config)

        # Extract configuration sections
        db_config = config['database']
        workload_config = config['workload']
        metrics_config = config['metrics']

        # Log test configuration
        logger.info(f"\nTest Configuration:")
        logger.info(f"  Dataset size: {workload_config['dataset_size']:,} rows")
        logger.info(f"  Indexed: {workload_config['indexed']}")
        logger.info(f"  Read/Write ratio: {workload_config['read_write_ratio']}")
        logger.info(f"  Concurrency: {workload_config['concurrency']} clients")
        logger.info(f"  Duration: {workload_config['duration_seconds']}s (warmup: {workload_config['warmup_seconds']}s)")

        # Initialize components
        logger.info("\nInitializing components...")

        # Database
        database = Database(db_config)
        database.connect(min_pool_size=workload_config.get('concurrency'))
        logger.info("  Database connection established")

        # Metrics
        metrics = MetricsCollector(metrics_config)
        metrics.start_http_server()
        metrics.start_run(workload_config)
        logger.info("  Metrics collector initialized")

        # Setup database schema and load data
        if not args.skip_data_load:
            logger.info("\nSetting up database schema...")
            database.setup_schema(drop_if_exists=True)

            logger.info("\nLoading initial dataset...")
            dataset_size = workload_config['dataset_size']
            payload_size = workload_config.get('payload_size_bytes', 1024)
            database.load_data(dataset_size, payload_size)

            # Create or skip index
            if workload_config['indexed']:
                logger.info("\nCreating index...")
                database.create_index()
            else:
                logger.info("\nSkipping index creation (no-index test)")

            # Run VACUUM ANALYZE
            logger.info("\nRunning VACUUM ANALYZE...")
            database.vacuum_analyze()

            # Display table stats
            stats = database.get_table_stats()
            logger.info(f"\nTable Statistics:")
            logger.info(f"  Rows: {stats['row_count']:,}")
            logger.info(f"  Table size: {stats['table_size']}")
            logger.info(f"  Index size: {stats['indexes_size']}")
            logger.info(f"  Total size: {stats['total_size']}")
            logger.info(f"  Index exists: {stats['index_exists']}")
        else:
            logger.info("\nSkipping data load (using existing data)")
            if workload_config['indexed']:
                logger.info("\nEnsuring index exists...")
                database.create_index()
            else:
                logger.info("\nEnsuring index is dropped for no-index test...")
                database.drop_index()

        # Pause before starting workload
        logger.info("\nStarting workload in 5 seconds...")
        time.sleep(5)

        # Execute workload
        workload = WorkloadExecutor(database, metrics, workload_config)

        if args.skip_warmup:
            logger.info("\nSkipping warmup phase")
            workload.warmup_seconds = 0

        duration = workload.run_full_workload()

        # Export results
        logger.info("\nExporting results...")
        summary = metrics.export_results(workload_config, duration)

        # Print summary
        metrics.print_summary(summary, duration)

        # Cleanup
        logger.info("Cleaning up...")
        metrics.close()
        database.close()

        logger.info("\n" + "=" * 80)
        logger.info("Benchmark completed successfully")
        logger.info("=" * 80)

        return 0

    except KeyboardInterrupt:
        logger.warning("\nBenchmark interrupted by user")
        return 1

    except Exception as e:
        logger.error(f"\nBenchmark failed with error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
