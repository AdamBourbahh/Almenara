PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,$(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,python3))
PYTEST ?= $(PYTHON) -m pytest
API_HOST ?= 127.0.0.1
API_PORT ?= 8000

.PHONY: install check-deps bootstrap etl test api dev frontend sync-rules check-all

install:
	$(PYTHON) -m pip install -r requirements.lock
	cd frontend && npm ci

check-deps:
	$(PYTHON) -m pip check
	cd frontend && npm ls --all && npm audit

bootstrap:
	$(PYTHON) scripts/00_bootstrap_synthetic_cube.py

etl:
	$(PYTHON) scripts/run_pipeline.py etl

test:
	$(PYTHON) scripts/run_pipeline.py test

api:
	@$(PYTHON) -c "import uvicorn, fastapi, duckdb" 2>/dev/null || { \
		echo "Backend dependencies are missing for '$(PYTHON)'."; \
		echo "Create the environment and install the locked dependencies:"; \
		echo "  python3 -m venv .venv"; \
		echo "  .venv/bin/pip install -r requirements.lock"; \
		echo "Then retry 'make api' (it picks .venv automatically)."; \
		exit 1; }
	$(PYTHON) -m uvicorn backend.api.main:app --host $(API_HOST) --port $(API_PORT) --reload

dev:
	$(PYTHON) scripts/run_dev.py $(DEV_ARGS)

frontend:
	cd frontend && npm run dev

sync-rules:
	$(PYTHON) -c "from pathlib import Path; source=Path('../AGENTS.md').read_bytes(); [Path(target).write_bytes(source) for target in ('.cursorrules','.windsurfrules','.clinerules','.github/copilot-instructions.md')]"

check-all: sync-rules test
	cd frontend && npx tsc --noEmit
