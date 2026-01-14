# Repository Guidelines

## Project Structure & Module Organization
- Root scripts orchestrate the experiment flow: `run_experiments.sh`, `run_single_test.sh`, and `validate_results.sh`.
- Python workload and setup live at the repo root: `load_test.py`, `generate_data.py`, `setup_config.py`.
- Docker assets live in `docker-compose.yml`, `Dockerfile`, `init.sql`, `prometheus.yml`, and `grafana-dashboard.json`.
- Experiment outputs are written to `results/` as CSV files, plus `results/experiment_state.txt` for resumable runs.

## Build, Test, and Development Commands
- `docker compose up -d postgres redis` starts the database and cache services.
- `./run_single_test.sh no_index 1000000 50` runs one configuration (config, table size, concurrency).
- `./run_experiments.sh` executes the full experiment matrix with state tracking.
- `./validate_results.sh` rebuilds `results/experiment_state.txt` from existing CSVs.
- `docker compose down` stops all services and removes containers.

## Coding Style & Naming Conventions
- Python uses 4-space indentation and `snake_case` for functions and variables.
- Shell scripts are Bash with `set -e` and clear option parsing.
- SQL schema in `init.sql` uses lowercase, underscore-separated identifiers.
- Result files follow `{config}_{table_size}_{concurrency}_{timestamp}.csv` in `results/`.

## Testing Guidelines
- There is no unit test framework; validation is performance-driven.
- Use `./run_single_test.sh` for quick checks and `./run_experiments.sh` for the full matrix.
- CSV validation expects at least ~340 rows per run (see `validate_results.sh`).

## Commit & Pull Request Guidelines
- Git history mixes short imperative messages and optional prefixes (`feat:`, `fix:`). Use concise summaries; add a prefix if it clarifies scope.
- PRs should describe configuration changes, include the exact command(s) run, and attach key metrics or charts when results change.

## Configuration & Security Tips
- Default service ports are `5433` (PostgreSQL), `6380` (Redis), `3000` (Grafana), `9090` (Prometheus).
- Grafana defaults to `admin/admin` unless overridden; update credentials for shared environments.
- Runtime parameters are controlled via environment variables in `docker-compose.yml` (e.g., `TEST_DURATION`, `CONCURRENCY`).
