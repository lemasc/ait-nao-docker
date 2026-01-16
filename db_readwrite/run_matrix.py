#!/usr/bin/env python3
"""
Test matrix orchestration script.

Executes the full test matrix with:
- Sequential test execution (avoid resource contention)
- 3 repetitions per configuration
- Progress tracking with JSON persistence
- Resume capability for interrupted runs
- Error handling (continue on failure, log errors)
- Real-time progress display with ETA

Usage:
    python run_matrix.py --phase phase1
    python run_matrix.py --phase phase1 --resume
    python run_matrix.py --phase phase1 --dry-run
    python run_matrix.py --phase phase1 --organize-results
"""

import argparse
import subprocess
import sys
import time
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import logging
import signal

from matrix_utils import (
    TestRun, Progress,
    load_progress, save_progress,
    discover_result_files, check_disk_space,
    validate_matrix_setup, format_duration,
    format_progress_bar, get_config_params,
    create_manifest
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Phase configuration
PHASE_CONFIG = {
    'phase1': {'dataset_size': 1_000_000, 'name': 'Memory-resident (1M rows)'},
    'phase2': {'dataset_size': 16_000_000, 'name': 'Disk-resident (16M rows)'}
}

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    logger.info("\n\nShutdown requested. Finishing current test and saving progress...")
    shutdown_requested = True


def check_docker_running() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ['docker', 'ps'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to check Docker: {e}")
        return False


def check_services_running() -> List[str]:
    """
    Check if required services are running.
    Returns list of missing services.
    """
    required_services = ['postgres', 'prometheus', 'grafana']
    missing = []

    try:
        result = subprocess.run(
            ['docker', 'compose', 'ps', '--services', '--filter', 'status=running'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            running = set(result.stdout.strip().split('\n'))
            missing = [svc for svc in required_services if svc not in running]
    except Exception as e:
        logger.error(f"Failed to check services: {e}")
        return required_services

    return missing


def discover_config_files(phase: str, config_dir: Path) -> List[Path]:
    """
    Discover all configuration files for a phase.
    Returns sorted list of config paths.
    """
    pattern = f"{phase}_*.yaml"
    configs = sorted(config_dir.glob(pattern))
    return configs


def build_test_matrix(phase: str, config_dir: Path, repetitions: int = 3) -> List[TestRun]:
    """
    Build test matrix for a phase.

    Creates TestRun objects for all configs × repetitions.
    Returns sorted list for reproducibility.
    """
    dataset_size = PHASE_CONFIG[phase]['dataset_size']
    configs = discover_config_files(phase, config_dir)

    if not configs:
        raise ValueError(f"No config files found for {phase} in {config_dir}")

    test_runs = []

    for config_path in configs:
        # Parse config parameters from filename
        params = get_config_params(config_path.name)

        # Create repetitions
        for rep in range(1, repetitions + 1):
            test_run = TestRun(
                phase=phase,
                config_path=str(config_path),
                config_name=config_path.name,
                repetition=rep,
                indexed=params['indexed'],
                read_write_ratio=[params['read_ratio'], params['write_ratio']],
                concurrency=params['concurrency'],
                dataset_size=dataset_size
            )
            test_runs.append(test_run)

    return test_runs


def execute_test(test_run: TestRun, skip_data_load: bool = False,
                base_dir: Path = Path('.')) -> None:
    """
    Execute a single test via Docker Compose.

    Raises exception on failure.
    """
    # Build command
    cmd = [
        'docker', 'compose', 'run', '--rm',
        'load_generator',
        'python', '-m', 'src.main',
        '--config', f'/app/{test_run.config_path}'
    ]

    if skip_data_load:
        cmd.append('--skip-data-load')

    # Log command
    logger.info(f"Executing: {' '.join(cmd)}")

    # Execute with timeout (10 minutes max per test)
    result = subprocess.run(
        cmd,
        cwd=base_dir,
        capture_output=True,
        text=True,
        timeout=600  # 10 minutes
    )

    if result.returncode != 0:
        error_msg = f"Test failed with exit code {result.returncode}\n"
        error_msg += f"STDOUT:\n{result.stdout}\n"
        error_msg += f"STDERR:\n{result.stderr}"
        raise RuntimeError(error_msg)

    logger.info("Test completed successfully")


def display_progress(progress: Progress, current_run: Optional[TestRun] = None,
                    current_start: Optional[float] = None) -> None:
    """Display real-time progress information."""
    phase_name = PHASE_CONFIG[progress.phase]['name']

    print("\n" + "=" * 70)
    print(f"Phase: {progress.phase} ({phase_name})")
    print(format_progress_bar(progress.completed_tests, progress.total_tests, width=40))
    print(f"Completed: {progress.completed_tests} | Failed: {progress.failed_tests} | "
          f"Remaining: {progress.total_tests - progress.completed_tests - progress.failed_tests}")

    # Calculate elapsed and estimate remaining
    if progress.start_time:
        try:
            start = datetime.fromisoformat(progress.start_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            elapsed = (now - start).total_seconds()

            if progress.completed_tests > 0:
                avg_per_test = elapsed / progress.completed_tests
                remaining_tests = progress.total_tests - progress.completed_tests - progress.failed_tests
                estimated_remaining = avg_per_test * remaining_tests

                print(f"Elapsed: {format_duration(elapsed)} | "
                      f"Est. remaining: {format_duration(estimated_remaining)}")
        except:
            pass

    # Show current test
    if current_run:
        current_elapsed = time.time() - current_start if current_start else 0
        print(f"\nCurrent: {current_run.config_name} (rep {current_run.repetition}) - "
              f"Running {format_duration(current_elapsed)}")

    print("=" * 70)


def run_matrix(phase: str, config_dir: Path, results_dir: Path,
              repetitions: int = 3, resume: bool = False,
              dry_run: bool = False) -> Progress:
    """
    Run the full test matrix for a phase.

    Args:
        phase: Phase identifier (phase1 or phase2)
        config_dir: Directory containing config files
        results_dir: Directory for results output
        repetitions: Number of repetitions per config
        resume: Resume from previous run
        dry_run: Preview execution without running tests

    Returns:
        Progress object with final state
    """
    progress_file = Path(f"matrix_progress_{phase}.json")

    # Load or create progress
    if resume:
        progress = load_progress(progress_file)
        if not progress:
            logger.error("No progress file found to resume from")
            sys.exit(1)
        logger.info(f"Resuming from previous run: {progress.completed_tests}/{progress.total_tests} completed")
    else:
        # Build fresh test matrix
        test_runs = build_test_matrix(phase, config_dir, repetitions)
        progress = Progress(
            phase=phase,
            start_time=datetime.now(timezone.utc).isoformat(),
            total_tests=len(test_runs),
            runs=test_runs
        )
        save_progress(progress, progress_file)
        logger.info(f"Created test matrix: {len(test_runs)} tests")

    # Filter to pending/failed tests
    pending_runs = [r for r in progress.runs if r.status in ['pending', 'failed']]

    if dry_run:
        print(f"\nDry run: Would execute {len(pending_runs)} tests")
        for i, run in enumerate(pending_runs[:10], 1):
            print(f"{i:3d}. {run.config_name} (rep {run.repetition})")
        if len(pending_runs) > 10:
            print(f"     ... and {len(pending_runs) - 10} more")
        return progress

    if not pending_runs:
        logger.info("No pending tests to run. All tests completed.")
        return progress

    logger.info(f"Executing {len(pending_runs)} tests...")

    # Track if first test (need data load)
    first_test = not any(r.status == 'completed' for r in progress.runs)

    # Execute tests sequentially
    for test_run in pending_runs:
        if shutdown_requested:
            logger.info("Shutdown requested. Stopping execution.")
            break

        # Update status to running
        test_run.status = 'running'
        test_run.start_time = datetime.now(timezone.utc).isoformat()
        save_progress(progress, progress_file)

        # Display progress
        display_progress(progress, test_run, time.time())

        try:
            # Execute test
            skip_data_load = not first_test
            execute_test(test_run, skip_data_load=skip_data_load)

            # Mark completed
            test_run.status = 'completed'
            test_run.end_time = datetime.now(timezone.utc).isoformat()

            # Calculate duration
            if test_run.start_time and test_run.end_time:
                start = datetime.fromisoformat(test_run.start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(test_run.end_time.replace('Z', '+00:00'))
                test_run.duration_seconds = (end - start).total_seconds()

            # Discover result files
            test_run.result_files = discover_result_files(
                results_dir=results_dir,
                config_name=test_run.config_name,
                indexed=test_run.indexed,
                read_ratio=test_run.read_write_ratio[0],
                write_ratio=test_run.read_write_ratio[1],
                concurrency=test_run.concurrency
            )

            # Update counters
            progress.completed_tests += 1
            first_test = False

        except subprocess.TimeoutExpired:
            # Test timeout
            test_run.status = 'failed'
            test_run.error_message = "Test exceeded 10 minute timeout"
            progress.failed_tests += 1
            logger.error(f"Test timed out: {test_run.config_name} (rep {test_run.repetition})")

        except Exception as e:
            # Test failed
            test_run.status = 'failed'
            test_run.error_message = str(e)
            progress.failed_tests += 1
            logger.error(f"Test failed: {test_run.config_name} (rep {test_run.repetition}): {e}")

        finally:
            # Always save progress
            save_progress(progress, progress_file)

    # Final progress display
    display_progress(progress)

    return progress


def organize_results(phase: str, results_dir: Path, progress_file: Path) -> None:
    """
    Organize results and create manifest file.

    Moves results to phase-specific subdirectory and creates manifest.
    """
    # Load progress
    progress = load_progress(progress_file)
    if not progress:
        logger.error(f"No progress file found: {progress_file}")
        return

    # Create phase subdirectory
    phase_dir = results_dir / phase
    phase_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Organizing results into: {phase_dir}")

    # Move result files
    moved_count = 0
    for run in progress.runs:
        if run.result_files:
            for file_type, filename in run.result_files.items():
                src = results_dir / filename
                dst = phase_dir / filename

                if src.exists() and src != dst:
                    src.rename(dst)
                    moved_count += 1

    logger.info(f"Moved {moved_count} result files")

    # Create manifest
    dataset_size = PHASE_CONFIG[phase]['dataset_size']
    manifest_path = phase_dir / 'manifest.json'
    create_manifest(phase, dataset_size, progress, manifest_path)

    logger.info(f"Results organized in: {phase_dir}")


def validate_setup(phase: str, config_dir: Path, results_dir: Path) -> bool:
    """
    Run pre-flight checks before starting matrix execution.

    Returns True if valid, False otherwise.
    """
    logger.info("Running pre-flight checks...")

    # Check Docker
    if not check_docker_running():
        logger.error("Docker is not running")
        return False

    # Check services
    missing_services = check_services_running()
    if missing_services:
        logger.error(f"Required services not running: {', '.join(missing_services)}")
        logger.info("Run './setup.sh' to start services")
        return False

    # Check matrix setup
    errors = validate_matrix_setup(phase, config_dir, results_dir)
    if errors:
        logger.error("Matrix setup validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return False

    logger.info("Pre-flight checks passed")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Test matrix orchestration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_matrix.py --phase phase1
  python run_matrix.py --phase phase1 --resume
  python run_matrix.py --phase phase1 --dry-run
  python run_matrix.py --phase phase1 --organize-results
        """
    )
    parser.add_argument(
        '--phase',
        required=True,
        choices=['phase1', 'phase2'],
        help='Which phase to run'
    )
    parser.add_argument(
        '--config-dir',
        type=Path,
        default=Path('load_generator/config/generated'),
        help='Directory containing config files'
    )
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=Path('results'),
        help='Results output directory'
    )
    parser.add_argument(
        '--repetitions',
        type=int,
        default=3,
        help='Number of repetitions per config'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from previous run'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview execution without running tests'
    )
    parser.add_argument(
        '--organize-results',
        action='store_true',
        help='Organize results and create manifest (post-execution)'
    )

    args = parser.parse_args()

    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    # Handle organize-results mode
    if args.organize_results:
        progress_file = Path(f"matrix_progress_{args.phase}.json")
        organize_results(args.phase, args.results_dir, progress_file)
        return

    # Validate setup (skip for resume and dry-run)
    if not args.resume and not args.dry_run:
        if not validate_setup(args.phase, args.config_dir, args.results_dir):
            sys.exit(1)

    # Run matrix
    try:
        progress = run_matrix(
            phase=args.phase,
            config_dir=args.config_dir,
            results_dir=args.results_dir,
            repetitions=args.repetitions,
            resume=args.resume,
            dry_run=args.dry_run
        )

        # Summary
        if not args.dry_run:
            print("\n" + "=" * 70)
            print("EXECUTION SUMMARY")
            print("=" * 70)
            print(f"Phase: {args.phase}")
            print(f"Total tests: {progress.total_tests}")
            print(f"Completed: {progress.completed_tests}")
            print(f"Failed: {progress.failed_tests}")

            if progress.failed_tests > 0:
                print("\nFailed tests:")
                for run in progress.runs:
                    if run.status == 'failed':
                        print(f"  - {run.config_name} (rep {run.repetition}): {run.error_message}")

            print("\nNext steps:")
            if progress.completed_tests + progress.failed_tests < progress.total_tests:
                print("  - Resume: python run_matrix.py --phase {args.phase} --resume")
            else:
                print(f"  - Organize: python run_matrix.py --phase {args.phase} --organize-results")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Matrix execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
