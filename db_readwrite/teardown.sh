#!/bin/bash
set -e

echo "================================"
echo "PostgreSQL Benchmark Teardown"
echo "================================"
echo ""

# Ask for confirmation
read -p "This will stop all containers and remove volumes. Continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Teardown cancelled."
    exit 0
fi

echo "Stopping containers and removing volumes..."
docker compose down -v

echo ""
echo "Teardown complete!"
echo ""
echo "Note: Results in ./results directory are preserved."
echo "To remove results, run: rm -rf results/"
echo ""
