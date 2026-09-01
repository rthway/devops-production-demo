# Developer entry points. Every target here is something CI also runs, so
# "works on my machine" and "passes CI" cannot quietly drift apart.

.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTHON  ?= python
COMPOSE ?= docker compose
IMAGE   ?= devops-production-demo:local

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- development ------------------------------------------------------------

.PHONY: install
install: ## Create a venv and install with dev extras
	$(PYTHON) -m venv .venv
	.venv/Scripts/python.exe -m pip install -e ".[dev]" || .venv/bin/python -m pip install -e ".[dev]"

.PHONY: run
run: ## Run the API locally with reload
	uvicorn app.main:app --reload

# --- quality ----------------------------------------------------------------

.PHONY: lint
lint: ## ruff check + format check
	ruff check .
	ruff format --check .

.PHONY: format
format: ## Apply ruff autofixes and formatting
	ruff check --fix .
	ruff format .

.PHONY: typecheck
typecheck: ## mypy strict
	mypy

.PHONY: test
test: ## Run the unit suite
	pytest -m "not integration"

.PHONY: coverage
coverage: ## Run tests with coverage
	pytest -m "not integration" --cov --cov-report=term-missing --cov-report=html

.PHONY: security
security: ## Bandit + pip-audit
	bandit -c pyproject.toml -r app --severity-level medium
	pip-audit --strict

.PHONY: check
check: lint typecheck test security ## Everything CI runs on a PR

# --- database ---------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply migrations
	alembic upgrade head

.PHONY: migration
migration: ## Generate a migration: make migration m="add widgets"
	alembic revision --autogenerate -m "$(m)"

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	alembic downgrade -1

# --- docker -----------------------------------------------------------------

.PHONY: build
build: ## Build the image
	docker build -t $(IMAGE) .

.PHONY: up
up: ## Start the full stack
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

.PHONY: dev
dev: ## Start the stack with hot reload
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up

.PHONY: logs
logs: ## Tail application logs
	$(COMPOSE) logs -f api

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop the stack and DELETE volumes
	$(COMPOSE) down -v

.PHONY: smoke
smoke: ## Hit the running stack
	curl -fsS localhost:8080/health && echo
	curl -fsS localhost:8080/health/ready && echo
	curl -fsS localhost:8080/api/v1/users && echo

# --- manifests --------------------------------------------------------------

.PHONY: validate
validate: ## Validate compose, k8s, helm and terraform
	$(COMPOSE) config -q
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml config -q
	kubectl apply --dry-run=client -f k8s/ > /dev/null
	helm lint helm/devops-demo
	helm template devops-demo helm/devops-demo -f helm/devops-demo/values-prod.yaml > /dev/null
	terraform fmt -check -recursive terraform/
	terraform -chdir=terraform/environments/dev validate
	terraform -chdir=terraform/environments/prod validate

.PHONY: k8s-delete
k8s-delete: ## Delete the namespace and everything in it
	kubectl delete namespace devops-demo --ignore-not-found
