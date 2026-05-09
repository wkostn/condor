# Ensure tools are in PATH
SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

.PHONY: help setup install run test lint build-frontend setup-chrome run-shadow start-shadow stop-shadow logs-shadow

# Helper function to find node/npm via nvm or system
define find_node
	@(export NVM_DIR="$HOME/.nvm"; \
	if [ -s "$NVM_DIR/nvm.sh" ]; then \
		. "$NVM_DIR/nvm.sh" >/dev/null 2>&1; \
		nvm use default >/dev/null 2>&1 || nvm use node >/dev/null 2>&1 || true; \
	fi; \
	$(1))
endef

help:
	@echo "Condor - Available Commands"
	@echo ""
	@echo "  make setup       - Interactive setup wizard"
	@echo "  make install     - Setup + install all dependencies"
	@echo "  make run         - Run locally (dev)"
	@echo "  make run-shadow  - Run shadow monitor locally"
	@echo "  make start-shadow - Start shadow monitor in Docker"
	@echo "  make stop-shadow - Stop shadow monitor in Docker"
	@echo "  make logs-shadow - Tail shadow monitor logs"
	@echo "  make test        - Run tests"
	@echo "  make lint        - Run black + isort"

setup:
	@chmod +x setup-environment.sh && ./setup-environment.sh

install: setup
	uv sync --dev
	@bash -c ' \
		export NVM_DIR="$$HOME/.nvm"; \
		[ -s "$$NVM_DIR/nvm.sh" ] && . "$$NVM_DIR/nvm.sh"; \
		cd frontend && npm install \
	'
	@$(MAKE) setup-chrome

setup-chrome:
	@echo "Setting up Chrome for chart rendering..."
	@uv run python -c "import kaleido; kaleido.get_chrome_sync()" 2>/dev/null || \
		echo "Chrome setup skipped (not required for basic usage)"

build-frontend:
	@bash -c ' \
		export NVM_DIR="$$HOME/.nvm"; \
		[ -s "$$NVM_DIR/nvm.sh" ] && . "$$NVM_DIR/nvm.sh"; \
		cd frontend && npm run build \
	'

run: build-frontend
	uv run python main.py

run-shadow:
	uv run python scripts/shadow_monitor.py

start-shadow:
	docker compose up -d shadow-monitor

stop-shadow:
	docker compose stop shadow-monitor

logs-shadow:
	docker compose logs -f shadow-monitor

test:
	uv run pytest

lint:
	uv run black .
	uv run isort .
