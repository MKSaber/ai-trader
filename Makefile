.PHONY: up down test demo pipeline lint

up:
	cp -n .env.example .env || true
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm api pytest -q

demo:
	docker compose run --rm api python scripts/e2e_demo.py

pipeline:
	docker compose run --rm api python -m app.cli daily-run --offline

lint:
	docker compose run --rm api ruff check app tests
