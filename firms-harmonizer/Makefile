PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

.PHONY: bootstrap test api frontend sync-rules check-all
bootstrap:
	$(PYTHON) scripts/00_bootstrap_synthetic_cube.py

test: bootstrap
	$(PYTEST) backend/tests/test_cube_schema.py
	$(PYTEST) backend/tests/test_math_core.py -v
	$(PYTEST) backend/tests/test_db_layer.py -v
	$(PYTEST) backend/tests/test_api_contract.py -v

api:
	$(PYTHON) -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

sync-rules:
	@for target in .cursorrules .windsurfrules .clinerules .github/copilot-instructions.md; do \
		if [ ! ../AGENTS.md -ef "$$target" ]; then cp ../AGENTS.md "$$target" || exit 1; fi; \
	done

check-all: sync-rules test
	cd frontend && npx tsc --noEmit
