#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
import sys

import yaml


def default_state_path(run_order_path: Path) -> Path:
    return run_order_path.with_name(run_order_path.stem + ".state.json")


def load_state(state_path: Path):
    if not state_path.exists():
        return None
    with state_path.open("r") as handle:
        return json.load(handle)


def write_state(state_path: Path, state: dict):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")


def resolve_config_path(config_path: str, repo_root: Path) -> Path:
    candidate = Path(config_path)
    if candidate.is_absolute():
        return candidate
    repo_candidate = repo_root / candidate
    if repo_candidate.exists():
        return repo_candidate
    return repo_root / "load_generator" / candidate


def load_config(config_path: str, repo_root: Path) -> dict:
    resolved = resolve_config_path(config_path, repo_root)
    with resolved.open("r") as handle:
        return yaml.safe_load(handle)


def get_workload_config(entry: dict, repo_root: Path) -> dict:
    workload = entry.get("workload") or {}
    if workload.get("dataset_size") is None or workload.get("indexed") is None:
        config_path = entry.get("config_path")
        if config_path:
            config = load_config(config_path, repo_root)
            workload = config.get("workload", {})
    return workload


def run_psql(repo_root: Path, query: str) -> subprocess.CompletedProcess:
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "benchmark_db",
        "-t",
        "-A",
        "-c",
        query,
    ]
    return subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def get_row_count(repo_root: Path):
    table_check = run_psql(repo_root, "SELECT to_regclass('public.test_table');")
    if table_check.returncode != 0:
        return None, table_check.stderr.strip() or table_check.stdout.strip()

    if not table_check.stdout.strip():
        return 0, None

    row_result = run_psql(repo_root, "SELECT COUNT(*) FROM test_table;")
    if row_result.returncode != 0:
        return None, row_result.stderr.strip() or row_result.stdout.strip()

    try:
        return int(row_result.stdout.strip()), None
    except ValueError:
        return None, row_result.stdout.strip()


def should_skip_data_load(workload: dict, repo_root: Path, args) -> tuple:
    if args.skip_data_load:
        return True, "forced by --skip-data-load"

    if args.dry_run:
        return False, "dry run"

    return False, "always reload"


def build_command(config_path: str, args, skip_data_load: bool) -> list:
    cmd = [
        "docker",
        "compose",
        "run",
        "--rm",
        "-e",
        "PYTHONUNBUFFERED=1",
        "--name",
        "load_generator",
        "load_generator",
        "python",
        "-m",
        "src.main",
        "--config",
        f"/app/{config_path}",
    ]

    if args.log_level:
        cmd.extend(["--log-level", args.log_level])
    if args.skip_warmup:
        cmd.append("--skip-warmup")
    if skip_data_load:
        cmd.append("--skip-data-load")

    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run benchmark configs based on a run order file"
    )
    parser.add_argument(
        "--run-order",
        required=True,
        help="Path to run order JSON file",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Path to state file (default: <run_order>.state.json)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=None,
        help="Start at a specific index (0-based)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for load generator",
    )
    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="Skip warmup phase",
    )
    parser.add_argument(
        "--skip-data-load",
        action="store_true",
        help="Skip initial data load",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_order_path = Path(args.run_order)
    if not run_order_path.is_absolute():
        run_order_path = repo_root / run_order_path
    if not run_order_path.exists():
        print(f"Run order file not found: {run_order_path}", file=sys.stderr)
        return 1

    if args.state_file:
        state_path = Path(args.state_file)
        if not state_path.is_absolute():
            state_path = repo_root / state_path
    else:
        state_path = default_state_path(run_order_path)

    with run_order_path.open("r") as handle:
        run_order = json.load(handle)

    configs = run_order.get("configs", [])
    total = len(configs)
    if total == 0:
        print("Run order has no configs", file=sys.stderr)
        return 1

    state = load_state(state_path)
    if args.start_index is not None:
        start_index = args.start_index
    elif state and isinstance(state.get("last_completed_index"), int):
        start_index = state["last_completed_index"] + 1
    else:
        start_index = 0

    if start_index < 0 or start_index >= total:
        print(f"Invalid start index: {start_index}", file=sys.stderr)
        return 1

    session_state = {
        "run_order": run_order_path.as_posix(),
        "state_file": state_path.as_posix(),
        "total": total,
        "started_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_completed_index": start_index - 1,
        "status": "running",
    }
    write_state(state_path, session_state)

    try:
        for index in range(start_index, total):
            entry = configs[index]
            config_path = entry.get("config_path")
            if not config_path:
                print(f"Missing config_path at index {index}", file=sys.stderr)
                return 1

            label = entry.get("id", config_path)
            workload = get_workload_config(entry, repo_root)
            skip_data_load, skip_reason = should_skip_data_load(
                workload, repo_root, args
            )
            cmd = build_command(config_path, args, skip_data_load)
            print(f"[{index + 1}/{total}] {label}")
            print(f"Data load: {'skip' if skip_data_load else 'run'} ({skip_reason})")
            print(" ".join(cmd))

            if args.dry_run:
                result = subprocess.CompletedProcess(cmd, 0)
            else:
                result = subprocess.run(cmd, cwd=repo_root)

            if result.returncode != 0:
                session_state.update(
                    {
                        "status": "failed",
                        "failed_index": index,
                        "failed_id": label,
                        "last_completed_index": index - 1,
                        "finished_at": datetime.utcnow().strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    }
                )
                write_state(state_path, session_state)
                return result.returncode

            session_state.update(
                {
                    "last_completed_index": index,
                    "last_completed_id": label,
                    "finished_at": None,
                }
            )
            write_state(state_path, session_state)

    except KeyboardInterrupt:
        session_state.update(
            {
                "status": "interrupted",
                "finished_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        write_state(state_path, session_state)
        print("Interrupted. State saved.")
        return 130

    session_state.update(
        {
            "status": "completed",
            "finished_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    write_state(state_path, session_state)
    print("All runs completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
