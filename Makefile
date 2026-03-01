.PHONY: help install test test-integration test-coverage lint format run run-docker build clean

help:
	@echo "ChatBotura Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  install          - Install dependencies"
	@echo "  test             - Run unit tests"
	@echo "  test-integration - Run integration tests"
	@echo "  test-coverage    - Run tests with coverage"
	@echo "  lint             - Run linters"
	@echo "  format           - Format code"
	@echo "  run              - Run the API server"
	@echo "  run-docker       - Run with Docker Compose"
	@echo "  build            - Build Docker containers"
	@echo "  clean            - Clean up generated files"

install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio httpx

test:
	pytest tests/ -v --tb=short

test-integration:
	pytest tests/ -v --tb=short -m integration

test-coverage:
	pytest tests/ --cov=app --cov=main --cov-report=html --cov-report=term

lint:
	@echo "Running ruff..."
	ruff check app/ main/
	@echo "Running mypy..."
	mypy app/ main/ --ignore-missing-imports || true

format:
	ruff format app/ main/
	ruff check --fix app/ main/

run:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

run-docker:
	docker-compose up --build

build:
	docker-compose build

clean:
	rm -rf __pycache__ app/__pycache__ tests/__pycache__
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
