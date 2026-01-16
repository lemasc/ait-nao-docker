#!/usr/bin/env python3
"""
Shared utilities for test matrix orchestration.
Provides data structures, progress tracking, and validation functions.
"""

import json
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class TestRun:
    """Represents a single test execution."""
    phase: str
    config_path: str
    config_name: str
    repetition: int
    indexed: bool
    read_write_ratio: List[int]
    concurrency: int
    dataset_size: int
    status: str = 'pending'  # pending, running, completed, failed
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    result_files: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestRun':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class Progress:
    """Tracks progress for a test matrix phase."""
    phase: str
    start_time: str
    total_tests: int
    completed_tests: int = 0
    failed_tests: int = 0
    last_updated: Optional[str] = None
    runs: List[TestRun] = None

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'phase': self.phase,
            'start_time': self.start_time,
            'total_tests': self.total_tests,
            'completed_tests': self.completed_tests,
            'failed_tests': self.failed_tests,
            'last_updated': self.last_updated,
            'runs': [run.to_dict() for run in self.runs]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Progress':
        """Create from dictionary."""
        runs = [TestRun.from_dict(r) for r in data.get('runs', [])]
        return cls(
            phase=data['phase'],
            start_time=data['start_time'],
            total_tests=data['total_tests'],
            completed_tests=data.get('completed_tests', 0),
            failed_tests=data.get('failed_tests', 0),
            last_updated=data.get('last_updated'),
            runs=runs
        )


def load_progress(progress_file: Path) -> Optional[Progress]:
    """Load progress from JSON file."""
    if not progress_file.exists():
        return None

    try:
        with open(progress_file, 'r') as f:
            data = json.load(f)
        return Progress.from_dict(data)
    except Exception as e:
        logger.error(f"Failed to load progress from {progress_file}: {e}")
        return None


def save_progress(progress: Progress, progress_file: Path) -> None:
    """Save progress to JSON file."""
    try:
        progress.last_updated = datetime.utcnow().isoformat() + 'Z'
        with open(progress_file, 'w') as f:
            json.dump(progress.to_dict(), f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save progress to {progress_file}: {e}")


def discover_result_files(results_dir: Path, config_name: str, indexed: bool,
                         read_ratio: int, write_ratio: int, concurrency: int) -> Dict[str, str]:
    """
    Discover result files for a test configuration.

    Result files follow the pattern from metrics.py:104:
    {indexed}_r{read}w{write}_c{concurrency}_{timestamp}.{json|csv}
    """
    # Build search pattern
    indexed_str = "indexed" if indexed else "no_index"
    pattern = f"{indexed_str}_r{read_ratio}w{write_ratio}_c{concurrency}_*.json"

    # Find matching files (get the most recent)
    json_files = sorted(results_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    if not json_files:
        return {}

    # Get the most recent file
    latest_json = json_files[0]
    base_name = latest_json.stem  # Remove .json extension

    # Find corresponding CSV files
    summary_csv = results_dir / f"{base_name}_summary.csv"
    detailed_csv = results_dir / f"{base_name}_detailed.csv"

    result = {'json': latest_json.name}
    if summary_csv.exists():
        result['summary_csv'] = summary_csv.name
    if detailed_csv.exists():
        result['detailed_csv'] = detailed_csv.name

    return result


def check_disk_space(path: Path, required_gb: float) -> bool:
    """Check if sufficient disk space is available."""
    stat = shutil.disk_usage(path)
    available_gb = stat.free / (1024 ** 3)
    return available_gb >= required_gb


def validate_matrix_setup(phase: str, config_dir: Path, results_dir: Path) -> List[str]:
    """
    Validate that the system is ready to run the test matrix.
    Returns list of error messages (empty if valid).
    """
    errors = []

    # Check config directory exists
    if not config_dir.exists():
        errors.append(f"Config directory not found: {config_dir}")
        return errors

    # Count config files
    config_files = list(config_dir.glob(f"{phase}_*.yaml"))
    if len(config_files) != 30:
        errors.append(f"Expected 30 config files for {phase}, found {len(config_files)}")

    # Check results directory
    if not results_dir.exists():
        try:
            results_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create results directory {results_dir}: {e}")

    # Check disk space (estimate 10GB per phase with detailed CSV)
    if not check_disk_space(results_dir, 10):
        errors.append("Insufficient disk space. Need at least 10GB available.")

    return errors


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_progress_bar(completed: int, total: int, width: int = 40) -> str:
    """Generate a text progress bar."""
    if total == 0:
        return "[" + " " * width + "]"

    filled = int(width * completed / total)
    bar = "=" * filled + " " * (width - filled)
    percentage = 100.0 * completed / total
    return f"[{bar}] {completed}/{total} ({percentage:.1f}%)"


def get_config_params(config_name: str) -> Dict[str, Any]:
    """
    Parse configuration parameters from config file name.

    Format: phase{N}_{indexed|no_index}_r{read}w{write}_c{concurrency}.yaml
    Example: phase1_indexed_r90w10_c4.yaml
    """
    name = config_name.replace('.yaml', '')

    # Determine indexed status
    indexed = 'no_index' not in name

    # Find ratio and concurrency parts using regex-like approach
    # Find the r{read}w{write} part
    import re
    ratio_match = re.search(r'r(\d+)w(\d+)', name)
    concurrency_match = re.search(r'c(\d+)', name)

    if not ratio_match or not concurrency_match:
        raise ValueError(f"Cannot parse config name: {config_name}")

    read_ratio = int(ratio_match.group(1))
    write_ratio = int(ratio_match.group(2))
    concurrency = int(concurrency_match.group(1))

    return {
        'indexed': indexed,
        'read_ratio': read_ratio,
        'write_ratio': write_ratio,
        'concurrency': concurrency
    }


def create_manifest(phase: str, dataset_size: int, progress: Progress,
                   output_path: Path) -> None:
    """Create manifest file summarizing all test runs in a phase."""
    manifest = {
        'phase': phase,
        'dataset_size': dataset_size,
        'total_runs': progress.total_tests,
        'start_time': progress.start_time,
        'end_time': progress.last_updated,
        'completed': progress.completed_tests,
        'failed': progress.failed_tests,
        'runs': []
    }

    # Calculate duration if we have end time
    if progress.start_time and progress.last_updated:
        try:
            start = datetime.fromisoformat(progress.start_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(progress.last_updated.replace('Z', '+00:00'))
            duration_hours = (end - start).total_seconds() / 3600
            manifest['duration_hours'] = round(duration_hours, 2)
        except:
            pass

    # Add run details
    for run in progress.runs:
        run_info = {
            'config': run.config_name.replace('.yaml', ''),
            'repetition': run.repetition,
            'indexed': run.indexed,
            'read_write_ratio': run.read_write_ratio,
            'concurrency': run.concurrency,
            'status': run.status
        }

        if run.result_files:
            run_info['files'] = run.result_files

        if run.error_message:
            run_info['error'] = run.error_message

        manifest['runs'].append(run_info)

    # Write manifest
    with open(output_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Created manifest: {output_path}")
