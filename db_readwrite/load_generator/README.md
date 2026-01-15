# PostgreSQL Benchmark Load Generator

Custom Python-based load generator for evaluating PostgreSQL performance under OLTP workloads with different indexing strategies.

## Features

- Configurable read/write ratios
- Multiple query types (point lookup, range scan, range with ORDER BY)
- Multi-threaded workload execution
- Per-operation latency tracking
- Prometheus metrics export
- JSON/CSV results export

## Directory Structure

```
load_generator/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py          # Entry point
│   ├── config.py        # Configuration management
│   ├── database.py      # Database operations
│   ├── workload.py      # Workload execution
│   ├── metrics.py       # Metrics collection
│   └── queries.py       # Query templates
└── config/
    └── test_config.yaml # Sample configuration
```

## Configuration

See `config/test_config.yaml` for all available options.

## Running

The load generator is designed to run as a Docker container within the benchmark environment.

See the main project README for usage instructions.
