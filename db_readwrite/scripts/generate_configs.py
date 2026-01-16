#!/usr/bin/env python3
import argparse
import copy
from pathlib import Path
import sys

import yaml


def parse_bool_list(value: str):
    items = [item.strip().lower() for item in value.split(',') if item.strip()]
    result = []
    for item in items:
        if item in {"true", "1", "yes", "y"}:
            result.append(True)
        elif item in {"false", "0", "no", "n"}:
            result.append(False)
        else:
            raise argparse.ArgumentTypeError(
                f"Invalid boolean value: {item}. Use true/false."
            )
    return result


def parse_int_list(value: str):
    items = [item.strip() for item in value.split(',') if item.strip()]
    try:
        return [int(item) for item in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a comma-separated list of ints") from exc


def parse_ratio_list(value: str):
    items = [item.strip() for item in value.split(',') if item.strip()]
    ratios = []
    for item in items:
        parts = item.split(':')
        if len(parts) != 2:
            raise argparse.ArgumentTypeError(
                f"Invalid ratio format: {item}. Use 90:10"
            )
        try:
            ratio = [int(parts[0]), int(parts[1])]
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid ratio numbers: {item}. Use 90:10"
            ) from exc
        if sum(ratio) != 100:
            raise argparse.ArgumentTypeError(
                f"Ratio must sum to 100, got {ratio}"
            )
        ratios.append(ratio)
    return ratios


def build_filename(indexed: bool, ratio: list, concurrency: int) -> str:
    idx_label = "indexed" if indexed else "no_index"
    ratio_label = f"{ratio[0]}_{ratio[1]}"
    return f"{idx_label}_rw{ratio_label}_c{concurrency}.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate YAML configs for the benchmark matrix"
    )
    parser.add_argument(
        "--base-config",
        default="load_generator/config/test_config.yaml",
        help="Base config to copy and modify",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write generated YAML configs",
    )
    parser.add_argument(
        "--phase",
        choices=["memory", "disk"],
        help="Experiment phase (memory or disk)",
    )
    parser.add_argument(
        "--dataset-size",
        type=int,
        default=None,
        help="Override workload.dataset_size",
    )
    parser.add_argument(
        "--indexed",
        default="true,false",
        help="Comma-separated list of indexed values",
    )
    parser.add_argument(
        "--read-write-ratios",
        default="90:10,50:50,10:90",
        help="Comma-separated list of ratios like 90:10",
    )
    parser.add_argument(
        "--concurrency",
        default="1,4,8,16,32",
        help="Comma-separated list of concurrency values",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    base_path = Path(args.base_config)
    if not base_path.is_absolute():
        base_path = repo_root / base_path
    if not base_path.exists():
        print(f"Base config not found: {base_path}", file=sys.stderr)
        return 1

    with base_path.open("r") as handle:
        base_config = yaml.safe_load(handle)

    indexed_values = parse_bool_list(args.indexed)
    ratios = parse_ratio_list(args.read_write_ratios)
    concurrency_values = parse_int_list(args.concurrency)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(
            "load_generator/config/generated_disk"
            if args.phase == "disk"
            else "load_generator/config/generated"
        )
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_size = args.dataset_size
    # Overide dataset size for disk phase
    if dataset_size is None and args.phase == "disk":
        dataset_size = 16_000_000

    count = 0
    for indexed in indexed_values:
        for ratio in ratios:
            for concurrency in concurrency_values:
                config = copy.deepcopy(base_config)
                workload = config.setdefault("workload", {})
                workload["indexed"] = indexed
                workload["read_write_ratio"] = ratio
                workload["concurrency"] = concurrency
                if dataset_size is not None:
                    workload["dataset_size"] = dataset_size

                filename = build_filename(indexed, ratio, concurrency)
                output_path = output_dir / filename
                with output_path.open("w") as handle:
                    yaml.safe_dump(
                        config,
                        handle,
                        sort_keys=False,
                        indent=2,
                    )
                count += 1

    print(f"Generated {count} configs in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
