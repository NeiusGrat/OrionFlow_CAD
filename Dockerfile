# OrionFlow CAD Engine - Production Dockerfile
# Multi-stage build for optimized image size

# ==============================================================================
# Stage 1: Build stage
# ==============================================================================
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==============================================================================
# Stage 2: Production image
# ==============================================================================
FROM python:3.11-slim-bookworm AS production

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r orionflow && useradd -r -g orionflow orionflow

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Create necessary directories
RUN mkdir -p /app/outputs /app/data && \
    chown -R orionflow:orionflow /app

# Switch to non-root user
USER orionflow

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    OUTPUT_DIR=/app/outputs \
    DATASET_DIR=/app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ==============================================================================
# Stage 3: Development image (optional)
# ==============================================================================
FROM production AS development

USER root

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Install development dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir pytest pytest-cov black ruff mypy

USER orionflow

# Development command with hot reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ==============================================================================
# Stage 4: Celery worker image
# ==============================================================================
FROM production AS worker

# Worker command
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]

# ==============================================================================
# Stage 5: Celery beat scheduler image
# ==============================================================================
FROM production AS beat

# Beat command
CMD ["celery", "-A", "app.workers.celery_app", "beat", "--loglevel=info"]
