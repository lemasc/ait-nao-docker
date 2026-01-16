#!/usr/bin/env python3
"""
Configuration file generator for test matrix orchestration.

Generates YAML configuration files for all test combinations:
- 2 indexing levels (indexed, no_index)
- 3 read/write ratios ([90,10], [50,50], [10,90])
- 5 concurrency levels (1, 4, 8, 16, 32)
= 30 configurations per phase

Usage:
    python generate_configs.py --phase phase1
    python generate_configs.py --phase phase2
    python generate_configs.py --phase all
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, Any
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Matrix parameters
INDEXING_LEVELS = [True, False]
READ_WRITE_RATIOS = [[90, 10], [50, 50], [10, 90]]
CONCURRENCY_LEVELS = [1, 4, 8, 16, 32]

PHASE_DATASET_SIZES = {
    'phase1': 1_000_000,   # ~250MB, memory-resident
    'phase2': 16_000_000,  # ~4GB, disk-resident
}


def load_template(template_path: Path) -> Dict[str, Any]:
    """Load the base configuration template."""
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    with open(template_path, 'r') as f:
        return yaml.safe_load(f)


def generate_config_name(phase: str, indexed: bool, read_ratio: int,
                        write_ratio: int, concurrency: int) -> str:
    """
    Generate config filename following naming convention.

    Format: phase{N}_{indexed|no_index}_r{read}w{write}_c{concurrency}.yaml
    Example: phase1_indexed_r90w10_c4.yaml
    """
    indexed_str = "indexed" if indexed else "no_index"
    return f"{phase}_{indexed_str}_r{read_ratio}w{write_ratio}_c{concurrency}.yaml"


def create_config(template: Dict[str, Any], phase: str, indexed: bool,
                 read_write_ratio: list, concurrency: int) -> Dict[str, Any]:
    """
    Create a configuration by modifying the template.

    Deep copies template and updates:
    - workload.dataset_size (based on phase)
    - workload.indexed
    - workload.read_write_ratio
    - workload.concurrency

    Keeps constants:
    - workload.duration_seconds: 300
    - workload.warmup_seconds: 60
    - All other settings from template
    """
    import copy
    config = copy.deepcopy(template)

    # Update workload parameters
    config['workload']['dataset_size'] = PHASE_DATASET_SIZES[phase]
    config['workload']['indexed'] = indexed
    config['workload']['read_write_ratio'] = read_write_ratio
    config['workload']['concurrency'] = concurrency

    # Ensure constants are set
    config['workload']['duration_seconds'] = 300
    config['workload']['warmup_seconds'] = 60

    return config


def generate_phase_configs(phase: str, template: Dict[str, Any],
                          output_dir: Path) -> int:
    """
    Generate all configuration files for a phase.

    Returns number of configs generated.
    """
    count = 0

    for indexed in INDEXING_LEVELS:
        for read_write_ratio in READ_WRITE_RATIOS:
            for concurrency in CONCURRENCY_LEVELS:
                # Generate config
                config = create_config(
                    template=template,
                    phase=phase,
                    indexed=indexed,
                    read_write_ratio=read_write_ratio,
                    concurrency=concurrency
                )

                # Generate filename
                filename = generate_config_name(
                    phase=phase,
                    indexed=indexed,
                    read_ratio=read_write_ratio[0],
                    write_ratio=read_write_ratio[1],
                    concurrency=concurrency
                )

                # Write config file
                output_path = output_dir / filename
                with open(output_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

                logger.info(f"Generated: {filename}")
                count += 1

    return count


def main():
    parser = argparse.ArgumentParser(
        description='Generate test matrix configuration files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_configs.py --phase phase1
  python generate_configs.py --phase phase2
  python generate_configs.py --phase all
        """
    )
    parser.add_argument(
        '--phase',
        required=True,
        choices=['phase1', 'phase2', 'all'],
        help='Which phase to generate configs for'
    )
    parser.add_argument(
        '--template',
        type=Path,
        default=Path('load_generator/config/test_config.yaml'),
        help='Path to template configuration file'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('load_generator/config/generated'),
        help='Output directory for generated configs'
    )

    args = parser.parse_args()

    # Load template
    logger.info(f"Loading template from: {args.template}")
    template = load_template(args.template)

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {args.output_dir}")

    # Generate configs
    total_count = 0

    if args.phase in ['phase1', 'all']:
        logger.info("\n=== Generating Phase 1 configs (1M rows, memory-resident) ===")
        count = generate_phase_configs('phase1', template, args.output_dir)
        logger.info(f"Phase 1: Generated {count} configs")
        total_count += count

    if args.phase in ['phase2', 'all']:
        logger.info("\n=== Generating Phase 2 configs (16M rows, disk-resident) ===")
        count = generate_phase_configs('phase2', template, args.output_dir)
        logger.info(f"Phase 2: Generated {count} configs")
        total_count += count

    logger.info(f"\n=== Summary ===")
    logger.info(f"Total configs generated: {total_count}")
    logger.info(f"Output directory: {args.output_dir}")

    # Verify counts
    phase1_files = len(list(args.output_dir.glob('phase1_*.yaml')))
    phase2_files = len(list(args.output_dir.glob('phase2_*.yaml')))

    logger.info(f"\nVerification:")
    logger.info(f"  Phase 1 files: {phase1_files}/30")
    logger.info(f"  Phase 2 files: {phase2_files}/30")

    if args.phase == 'phase1' and phase1_files != 30:
        logger.warning(f"Expected 30 phase1 configs, found {phase1_files}")
    elif args.phase == 'phase2' and phase2_files != 30:
        logger.warning(f"Expected 30 phase2 configs, found {phase2_files}")
    elif args.phase == 'all' and (phase1_files != 30 or phase2_files != 30):
        logger.warning(f"Expected 60 total configs, found {phase1_files + phase2_files}")
    else:
        logger.info("\nAll configs generated successfully!")


if __name__ == '__main__':
    main()
