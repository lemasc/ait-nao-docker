# Repository Guidelines

## Project Structure & Module Organization
- Top-level orchestration lives in `docker-compose.yml` with helper scripts `setup.sh`, `run_test.sh`, and `teardown.sh`.
- Load generator code is in `load_generator/src/` (Python modules like `main.py`, `workload.py`, `database.py`).
- Configuration lives in `load_generator/config/test_config.yaml` and Grafana/Prometheus files under `grafana/` and `prometheus/`.
- PostgreSQL tuning and initialization are in `postgres/` (`postgresql.conf`, `init.sql`).
- Generated artifacts (results, CSV/JSON) go to `results/` and are gitignored.

## Build, Test, and Development Commands
- `./setup.sh`: pull images and start PostgreSQL, Prometheus, Grafana, and exporters.
- `./run_test.sh [config/path.yaml]`: run a benchmark with the default or specified config.
- `./teardown.sh`: stop containers and remove volumes (keeps `results/`).
- `docker compose run --rm load_generator python -m src.main --config /app/config/test_config.yaml --skip-data-load`: rerun against existing data.

## Coding Style & Naming Conventions
- Python follows 4-space indentation and PEP 8 naming: `snake_case` for functions/vars and `PascalCase` for classes.
- Config files use 2-space YAML indentation and lower_snake_case keys (e.g., `read_write_ratio`).
- Keep new modules in `load_generator/src/` and mirror existing file naming patterns.

## Testing Guidelines
- There are no unit tests; validation is via benchmark runs.
- Use `./run_test.sh` for end-to-end checks and inspect `results/` CSV/JSON outputs.
- When changing workload logic, run at least a short config (e.g., reduced `duration_seconds`).

## Commit & Pull Request Guidelines
- Recent commits use short, lowercase, imperative messages (e.g., "fix db timeout").
- PRs should include: a brief problem/solution summary, the exact config used, and any result highlights.
- Do not commit generated data under `results/` or CSV/JSON outputs (see `.gitignore`).

## Security & Configuration Tips
- Default credentials are for local benchmarking only; avoid exposing ports outside localhost.
- If you modify `postgres/postgresql.conf`, restart with `docker compose restart postgres`.
