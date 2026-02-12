-- OrionFlow Database Initialization Script
-- This script runs when the PostgreSQL container is first created

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create database if not exists (handled by Docker)
-- Database is created via POSTGRES_DB environment variable

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE orionflow TO orionflow;

-- Optional: Create read-only user for analytics
-- CREATE USER orionflow_readonly WITH PASSWORD 'readonly_password';
-- GRANT CONNECT ON DATABASE orionflow TO orionflow_readonly;
-- GRANT USAGE ON SCHEMA public TO orionflow_readonly;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO orionflow_readonly;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO orionflow_readonly;
