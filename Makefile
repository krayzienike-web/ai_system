.PHONY: up down migrate seed demo-data load-demo test lint check dev-backend dev-frontend

up:            ## Start everything in Docker (db, redis, backend, frontend) and seed demo data
	docker compose up --build -d
	docker compose exec backend python -m app.cli seed-demo
	docker compose exec backend python -m app.cli load-demo

down:
	docker compose down

migrate:       ## Apply migrations to the local database
	cd backend && uv run alembic upgrade head

seed:          ## Create the demo tenant: 3 restaurants, HQ and director users
	cd backend && uv run python -m app.cli seed-demo

demo-data:     ## Write the files of the synthetic 12-restaurant network to demo-data/ (with anomalies.json)
	cd backend && uv run python -m app.cli generate-demo --out ../demo-data

load-demo:     ## Load the synthetic network into the demo tenant through the import pipeline
	cd backend && uv run python -m app.cli load-demo

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	cd frontend && npm run lint && npm run typecheck

check: lint test
	cd frontend && npm run build

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev
