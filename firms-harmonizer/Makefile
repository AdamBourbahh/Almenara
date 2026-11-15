PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest

.PHONY: install check-deps bootstrap etl test api frontend sync-rules check-all
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
	$(PYTHON) -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

sync-rules:
	$(PYTHON) -c "from pathlib import Path; source=Path('../AGENTS.md').read_bytes(); [Path(target).write_bytes(source) for target in ('.cursorrules','.windsurfrules','.clinerules','.github/copilot-instructions.md')]"

check-all: sync-rules test
	cd frontend && npx tsc --noEmit
