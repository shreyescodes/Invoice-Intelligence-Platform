.DEFAULT_GOAL := help
.PHONY: help up up-all down reset logs test lint typecheck check e2e screenshots openapi

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

up: ## Build and start the stack on http://localhost:8080
	docker compose up --build --detach --wait

up-all: ## Stack plus Prometheus and Grafana
	docker compose --profile observability up --build --detach --wait

down: ## Stop the stack
	docker compose --profile observability --profile llm down

reset: ## Stop the stack and delete its data (database, documents, metrics)
	docker compose --profile observability --profile llm down --volumes

logs: ## Follow API and worker logs
	docker compose logs --follow api worker

test: ## Run backend, ERP mock and frontend unit tests
	cd backend && uv run pytest
	cd erp-mock && uv run pytest -q
	cd frontend && npm test

lint: ## Lint everything
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd erp-mock && uv run ruff check .
	cd frontend && npm run lint

typecheck: ## Type-check backend and frontend
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

check: lint typecheck test ## Everything CI runs except end-to-end

e2e: ## Playwright smoke tests against the running stack
	cd frontend && E2E_BASE_URL=http://localhost:8080 npx playwright test --project=e2e

screenshots: ## Regenerate docs/screenshots (needs a freshly seeded stack)
	cd frontend && E2E_BASE_URL=http://localhost:8080 npx playwright test --project=screenshots

openapi: ## Regenerate the OpenAPI contract and frontend client types
	cd backend && uv run iip export-openapi --out ../frontend/openapi.json
	cd frontend && npm run gen:api
