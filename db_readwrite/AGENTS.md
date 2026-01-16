# Repository Guidelines

## Project Structure & Module Organization
- `load_generator/src/`: Python workload runner (entry point in `main.py`, config in `config.py`).
- `load_generator/config/`: Base and generated YAML configs for benchmarks.
- `scripts/`: Matrix generation and run-order tooling.
- `postgres/`, `prometheus/`, `grafana/`: Service configs used by Docker Compose.
- `results/`: Benchmark output (ignored by git per `.gitignore`).
- `run_orders/`: Saved run-order JSON files for matrix runs.

## Build, Test, and Development Commands
- `./setup.sh`: Start the full stack (PostgreSQL, Prometheus, Grafana, exporter).
- `./run_test.sh [config/path.yaml]`: Run a benchmark using the default or specified config.
- `./teardown.sh`: Stop containers and remove volumes (keeps `results/`).
- `docker compose run --rm load_generator python -m src.main --config /app/config/test_config.yaml`: Run the load generator directly; add `--skip-data-load` or `--skip-warmup` for iteration.
- `python scripts/generate_configs.py`: Produce the 2x3x5 config matrix under `load_generator/config/generated/`.

## Coding Style & Naming Conventions
- Python uses 4-space indentation, snake_case functions/variables, and module-level constants in UPPER_SNAKE_CASE.
- YAML keys follow snake_case (see `load_generator/config/test_config.yaml`).
- Generated config filenames follow: `indexed|no_index_rw<read>_<write>_c<concurrency>.yaml`.
- No formatter/linter is enforced; match the existing style in the touched file.

## Testing Guidelines
- No unit test framework is configured; validation is via benchmark runs.
- Use `./run_test.sh` for a standard check and inspect outputs in `results/` (JSON and CSV).

## Commit & Pull Request Guidelines
- No explicit commit convention is documented; use short, imperative messages (e.g., "Add run order filter support").
- PRs should describe the benchmark parameters or config changes, and include relevant script/command examples.
- Avoid committing generated artifacts under `results/` (ignored by `.gitignore`).

## Security & Configuration Tips
- Default services run on localhost; Grafana uses `admin/admin` by default.
- Keep benchmark configs in version control; avoid embedding secrets in YAML.

## Agent Notes
- Review `CLAUDE.md` for workflow specifics and common commands.
