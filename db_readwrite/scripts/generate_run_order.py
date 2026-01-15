#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from datetime import datetime
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


def normalize_ratio(value):
    if isinstance(value, list) and len(value) == 2:
        return [int(value[0]), int(value[1])]
    return None


def build_id(indexed: bool, ratio: list, concurrency: int) -> str:
    idx_label = "indexed" if indexed else "no_index"
    ratio_label = f"{ratio[0]}_{ratio[1]}"
    return f"{idx_label}_rw{ratio_label}_c{concurrency}"


def resolve_config_path(config_path: Path, repo_root: Path):
    try:
        return config_path.relative_to(repo_root / "load_generator").as_posix()
    except ValueError:
        return config_path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a run order file from YAML configs"
    )
    parser.add_argument(
        "--configs-dir",
        default="load_generator/config/generated",
        help="Directory of YAML configs",
    )
    parser.add_argument(
        "--output",
        default="run_orders/run_order.json",
        help="Output run order JSON file",
    )
    parser.add_argument(
        "--indexed",
        default=None,
        help="Comma-separated list of indexed values to include",
    )
    parser.add_argument(
        "--read-write-ratios",
        default=None,
        help="Comma-separated list of ratios like 90:10 to include",
    )
    parser.add_argument(
        "--concurrency",
        default=None,
        help="Comma-separated list of concurrency values to include",
    )
    parser.add_argument(
        "--block-by",
        default="indexed,read_write_ratio,concurrency",
        help="Comma-separated list of fields for block ordering",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    configs_dir = Path(args.configs_dir)
    if not configs_dir.is_absolute():
        configs_dir = repo_root / configs_dir
    if not configs_dir.exists():
        print(f"Configs dir not found: {configs_dir}", file=sys.stderr)
        return 1

    indexed_filter = parse_bool_list(args.indexed) if args.indexed else None
    ratios_filter = parse_ratio_list(args.read_write_ratios) if args.read_write_ratios else None
    concurrency_filter = parse_int_list(args.concurrency) if args.concurrency else None

    block_by = [item.strip() for item in args.block_by.split(',') if item.strip()]

    order_maps = {}
    if indexed_filter is not None:
        order_maps["indexed"] = {value: idx for idx, value in enumerate(indexed_filter)}
    if ratios_filter is not None:
        ratio_keys = [tuple(ratio) for ratio in ratios_filter]
        order_maps["read_write_ratio"] = {
            value: idx for idx, value in enumerate(ratio_keys)
        }
    if concurrency_filter is not None:
        order_maps["concurrency"] = {
            value: idx for idx, value in enumerate(concurrency_filter)
        }

    entries = []
    candidates = [
        path
        for path in configs_dir.rglob("*")
        if path.suffix in {".yaml", ".yml"}
    ]
    for path in sorted(candidates):
        with path.open("r") as handle:
            config = yaml.safe_load(handle)
        workload = config.get("workload", {})
        indexed = bool(workload.get("indexed", False))
        ratio = normalize_ratio(workload.get("read_write_ratio"))
        concurrency = workload.get("concurrency")

        if ratio is None or concurrency is None:
            continue

        if indexed_filter is not None and indexed not in indexed_filter:
            continue
        if ratios_filter is not None and ratio not in ratios_filter:
            continue
        if concurrency_filter is not None and concurrency not in concurrency_filter:
            continue

        entry = {
            "id": build_id(indexed, ratio, concurrency),
            "config_path": resolve_config_path(path, repo_root),
            "workload": {
                "indexed": indexed,
                "read_write_ratio": ratio,
                "concurrency": concurrency,
                "dataset_size": workload.get("dataset_size"),
                "duration_seconds": workload.get("duration_seconds"),
                "warmup_seconds": workload.get("warmup_seconds"),
            },
        }
        entries.append(entry)

    def sort_key(item):
        key = []
        for field in block_by:
            value = item["workload"].get(field)
            if field == "read_write_ratio" and value is not None:
                value = tuple(value)
            order_map = order_maps.get(field)
            if order_map is not None:
                key.append(order_map.get(value, len(order_map)))
            else:
                key.append(value)
        key.append(item["config_path"])
        return tuple(key)

    entries.sort(key=sort_key)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": 1,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "configs_dir": configs_dir.as_posix(),
        "filters": {
            "indexed": indexed_filter,
            "read_write_ratio": ratios_filter,
            "concurrency": concurrency_filter,
        },
        "block_by": block_by,
        "configs": entries,
    }

    with output_path.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    print(f"Wrote {len(entries)} entries to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
