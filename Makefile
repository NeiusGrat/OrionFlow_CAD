# OrionFlow CAD Engine - Makefile
# Common commands for development and deployment

.PHONY: help install dev test lint format build deploy clean

# Default target
help:
	@echo "OrionFlow CAD Engine - Available Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install     - Install all dependencies"
	@echo "  make dev         - Start development server"
	@echo "  make test        - Run test suite"
	@echo "  make lint        - Run linting"
	@echo "  make format      - Format code"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-dev  - Start development environment"
	@echo "  make docker-up   - Start production environment"
	@echo "  make docker-down - Stop all containers"
	@echo "  make docker-logs - View container logs"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate  - Run database migrations"
	@echo "  make db-upgrade  - Upgrade to latest migration"
	@echo "  make db-downgrade- Downgrade one migration"
	@echo ""
	@echo "Deployment:"
	@echo "  make build       - Build Docker images"
	@echo "  make deploy      - Deploy to production"
	@echo "  make clean       - Clean up generated files"

# =============================================================================
# Development
# =============================================================================

install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	cd orionflow-ui && npm install --legacy-peer-deps

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd orionflow-ui && npm run dev

dev-worker:
	celery -A app.workers.celery_app worker --loglevel=debug

dev-beat:
	celery -A app.workers.celery_app beat --loglevel=debug

dev-flower:
	celery -A app.workers.celery_app flower --port=5555

# =============================================================================
# Testing
# =============================================================================

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

test-unit:
	pytest tests/ -v -m "not integration" --cov=app

test-integration:
	pytest tests/ -v -m integration

test-watch:
	ptw tests/ -- -v

coverage:
	pytest tests/ --cov=app --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

# =============================================================================
# Code Quality
# =============================================================================

lint:
	ruff check app/ tests/
	mypy app/ --ignore-missing-imports

format:
	black app/ tests/
	ruff check app/ tests/ --fix

type-check:
	mypy app/ --ignore-missing-imports

# =============================================================================
# Docker
# =============================================================================

docker-dev:
	docker-compose -f docker-compose.dev.yml up --build

docker-dev-down:
	docker-compose -f docker-compose.dev.yml down

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-logs-api:
	docker-compose logs -f api

docker-logs-worker:
	docker-compose logs -f worker

docker-shell:
	docker-compose exec api /bin/bash

docker-clean:
	docker-compose down -v --rmi local

# =============================================================================
# Database
# =============================================================================

db-migrate:
	alembic revision --autogenerate -m "$(message)"

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

db-history:
	alembic history --verbose

db-reset:
	alembic downgrade base
	alembic upgrade head

# =============================================================================
# Build & Deploy
# =============================================================================

build:
	docker build -t orionflow-api:latest --target production .
	docker build -t orionflow-worker:latest --target worker .
	docker build -t orionflow-frontend:latest -f docker/Dockerfile.frontend .

build-api:
	docker build -t orionflow-api:latest --target production .

build-frontend:
	cd orionflow-ui && npm run build
	docker build -t orionflow-frontend:latest -f docker/Dockerfile.frontend .

push:
	docker push orionflow-api:latest
	docker push orionflow-worker:latest
	docker push orionflow-frontend:latest

deploy-staging:
	@echo "Deploying to staging..."
	# Add deployment commands here

deploy-production:
	@echo "Deploying to production..."
	# Add deployment commands here

# =============================================================================
# Utilities
# =============================================================================

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml 2>/dev/null || true
	rm -rf outputs/*.glb outputs/*.step outputs/*.stl 2>/dev/null || true

clean-docker:
	docker system prune -f
	docker volume prune -f

logs:
	tail -f data/logs/*.log 2>/dev/null || echo "No log files found"

config:
	python -c "from app.config import settings; settings.print_config_summary()"

shell:
	python -c "from app.config import settings; import IPython; IPython.embed()"

# Generate secret key
secret:
	python -c "import secrets; print(secrets.token_urlsafe(32))"
