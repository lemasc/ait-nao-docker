-- Database Performance Evaluation Project
-- Initialize schema and performance parameters

-- Create users table
CREATE TABLE users (
    user_id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,
    status VARCHAR(20) DEFAULT 'active'
);

-- Indexes will be created conditionally by setup_config.py
-- These are commented out and managed programmatically:
-- CREATE INDEX idx_users_email ON users(email);
-- CREATE INDEX idx_users_created_at ON users(created_at);

-- Performance tuning parameters
-- These settings optimize for our testing workload (up to 250 concurrent users)
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '4GB';
ALTER SYSTEM SET random_page_cost = 1.1;  -- Optimized for SSD storage
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET max_connections = 300; -- Headroom when running 250‑concurrency tests alongside exporters.
ALTER SYSTEM SET statement_timeout = '15000';  -- 15 second query timeout

-- Create helper view for monitoring query statistics
CREATE VIEW query_stats AS
SELECT
    schemaname,
    relname as tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_live_tup,
    n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'users';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO testuser;
GRANT SELECT ON query_stats TO testuser;
GRANT USAGE, SELECT ON SEQUENCE users_user_id_seq TO testuser;
