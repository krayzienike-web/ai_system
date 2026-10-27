.PHONY: up down migrate seed demo-data load-demo api-types demo-snapshot test e2e lint check dev-backend dev-frontend

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

api-types:     ## Write the API contract for the frontend (frontend/src/api/openapi.json, schema.ts)
	cd backend && uv run python -m app.openapi

demo-snapshot: ## Record the API's answers on the demo network for the standalone prototype (after seed + load-demo)
	cd backend && uv run python -m app.demo.snapshot

test:          ## Backend tests with the coverage gate (90 %) and frontend unit tests
	cd backend && uv run pytest -q --cov
	cd frontend && npm test

e2e:           ## End-to-end scenarios on the demo build (docs/13-testing.md)
	cd frontend && npm run e2e

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	cd frontend && npm run lint && npm run typecheck

check: lint test
	cd frontend && npm run build

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev
