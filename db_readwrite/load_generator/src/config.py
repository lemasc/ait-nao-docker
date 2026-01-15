"""
Configuration management module.
"""

import argparse
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Configuration dictionary
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    logger.info(f"Loading configuration from {config_path}")

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    # Validate required sections
    required_sections = ['database', 'workload', 'metrics']
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required configuration section: {section}")

    logger.info("Configuration loaded successfully")
    return config


def validate_config(config: dict):
    """
    Validate configuration parameters.

    Args:
        config: Configuration dictionary

    Raises:
        ValueError: If configuration is invalid
    """
    workload = config['workload']

    # Validate read/write ratio
    ratio = workload.get('read_write_ratio', [90, 10])
    if len(ratio) != 2 or sum(ratio) != 100:
        raise ValueError(f"read_write_ratio must sum to 100, got: {ratio}")

    # Validate read operation weights
    read_ops = workload.get('read_operations', {})
    read_weights = [
        read_ops.get('point_lookup_weight', 0),
        read_ops.get('range_scan_weight', 0),
        read_ops.get('range_order_weight', 0)
    ]
    if sum(read_weights) != 100:
        raise ValueError(f"read_operations weights must sum to 100, got: {sum(read_weights)}")

    # Validate write operation weights
    write_ops = workload.get('write_operations', {})
    write_weights = [
        write_ops.get('insert_weight', 0),
        write_ops.get('update_weight', 0)
    ]
    if sum(write_weights) != 100:
        raise ValueError(f"write_operations weights must sum to 100, got: {sum(write_weights)}")

    logger.info("Configuration validation passed")


def setup_logging(level: str = "INFO"):
    """
    Setup logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='PostgreSQL Performance Benchmark Load Generator'
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config/test_config.yaml',
        help='Path to configuration file (default: config/test_config.yaml)'
    )

    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )

    parser.add_argument(
        '--skip-warmup',
        action='store_true',
        help='Skip warmup phase'
    )

    parser.add_argument(
        '--skip-data-load',
        action='store_true',
        help='Skip initial data loading (assumes data already exists)'
    )

    return parser.parse_args()
