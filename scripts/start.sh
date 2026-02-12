#!/bin/bash
# OrionFlow startup script

set -e

echo "Starting OrionFlow CAD Engine..."

# Wait for database to be ready
echo "Waiting for PostgreSQL..."
while ! pg_isready -h ${DB_HOST:-localhost} -p ${DB_PORT:-5432} -U ${DB_USER:-orionflow}; do
    sleep 1
done
echo "PostgreSQL is ready!"

# Wait for Redis to be ready
echo "Waiting for Redis..."
while ! redis-cli -h ${REDIS_HOST:-localhost} -p ${REDIS_PORT:-6379} ping; do
    sleep 1
done
echo "Redis is ready!"

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting Uvicorn..."
exec uvicorn app.main:app \
    --host ${API_HOST:-0.0.0.0} \
    --port ${API_PORT:-8000} \
    --workers ${WORKERS:-4} \
    --loop uvloop \
    --http httptools \
    --access-log \
    --log-level ${LOG_LEVEL:-info}
