-- Database Initialization Script
-- This script runs when the PostgreSQL container starts for the first time

-- Enable pg_stat_statements extension for query performance monitoring
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON DATABASE benchmark_db TO postgres;

-- Create schema for the benchmark (using public schema by default)
-- Additional initialization can be added here if needed

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'Benchmark database initialized successfully';
END $$;
