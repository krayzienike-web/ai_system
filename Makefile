# Local development runs in the dev environment (the settings default to production).
export FAI_ENV ?= dev

.PHONY: up down migrate seed demo-data load-demo api-types eval-chat eval-hypotheses eval-digest demo-snapshot test e2e lint check dev-backend dev-frontend

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

eval-chat:     ## The chat's eval on the demo network with the real model (FAI_AI_PROVIDER=claude, ANTHROPIC_API_KEY)
	cd backend && uv run python -m app.ai.evals --out ../eval-chat.json

eval-hypotheses: ## «Почему так» eval: planted causes in the top three (the real model; the demo's answer key)
	cd backend && uv run python -m app.cli generate-demo --out demo-data && \
	uv run python -m app.ai.evals --suite hypotheses --anomalies demo-data/anomalies.json --out ../eval-hypotheses.json

eval-digest:   ## Digest texts eval: every latest digest of the demo, numbers checked, no leaks (the real model)
	cd backend && uv run python -m app.ai.evals --suite digest --out ../eval-digest.json

api-types:     ## Write the API contract for the frontend (frontend/src/api/openapi.json, schema.ts)
	cd backend && uv run python -m app.openapi

demo-snapshot: ## Record the API's answers on the demo network for the standalone prototype (after seed + load-demo)
	cd backend && uv run python -m app.demo.snapshot

test:          ## Backend tests with the coverage gate (90 %) and frontend unit tests
	cd backend && uv run pytest -q --cov
	cd frontend && npm test

e2e:           ## End-to-end scenarios on the demo build (docs/13-testing.md)
	cd frontend && npm run e2e

e2e-live:      ## The session on the real API: production build + uvicorn on the FAI_DATABASE_URL database (migrated)
	cd frontend && npx playwright test -c playwright.live.config.ts --trace off

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run lint-imports
	cd frontend && npm run lint && npm run typecheck

check: lint test
	cd frontend && npm run build

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev
