UV ?= uv
PYTHON ?= .venv/bin/python
PYTHONPATH ?= src
export PYTHONPATH

.PHONY: sync format format-check lint type-check compile test simulate check-core check clean-build

sync:
	$(UV) venv --python 3.13.5 --clear
	$(UV) pip install --python $(PYTHON) -r requirements-dev.lock -e .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

format-check:
	$(PYTHON) -m ruff format --check .

lint:
	$(PYTHON) -m ruff check .

type-check:
	$(PYTHON) -m mypy

compile:
	$(PYTHON) -m compileall -q src tests

test:
	$(PYTHON) -m pytest

clean-build:
	rm -rf build

clean: clean-build
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf src/optimatrix/__pycache__ tests/__pycache__
	rm -f .DS_Store docs/.DS_Store src/.DS_Store src/optimatrix/.DS_Store

simulate: clean-build
	$(PYTHON) -m optimatrix simulate \
		--scenario all \
		--output build/business-acceptance.json \
		--ledger-root build/simulation-ledger

check-core: compile test simulate

check: format-check lint type-check check-core
