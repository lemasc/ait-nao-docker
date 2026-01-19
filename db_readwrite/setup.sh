#!/bin/bash
set -e

echo "================================"
echo "PostgreSQL Benchmark Setup"
echo "================================"
echo ""

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo "Error: docker compose not found. Please install Docker Compose V2."
    exit 1
fi

# Pull images
echo "Pulling Docker images..."
docker compose pull

# Create results directory
echo "Creating results directory..."
mkdir -p results

# Start PostgreSQL and wait for it to be ready
echo ""
echo "Starting PostgreSQL..."
docker compose up -d postgres

echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U postgres &> /dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

# Start monitoring services
echo ""
echo "Starting monitoring services..."
docker compose up -d prometheus grafana postgres_exporter

# Wait a moment for services to initialize
sleep 5

# Display service URLs
echo ""
echo "================================"
echo "Setup Complete!"
echo "================================"
echo ""
echo "Services are running:"
echo "  - PostgreSQL:  localhost:5432"
echo "  - Prometheus:  http://localhost:9090"
echo "  - Grafana:     http://localhost:3000 (admin/admin)"
echo ""
echo "Next steps:"
echo "  1. Visit Grafana at http://localhost:3000"
echo "  2. Run a test with: ./run_test.sh"
echo ""
