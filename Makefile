.PHONY: install test lint run docker generate-samples eval

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

lint:
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

run:
	python -m src.main

docker:
	docker compose up --build

generate-samples:
	python scripts/generate_samples.py

eval:
	python -m evaluation.run_eval
