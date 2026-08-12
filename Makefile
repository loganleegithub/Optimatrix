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
	rm -rf build/simulation-cases build/business-acceptance.json build/workbench

simulate: clean-build
	$(PYTHON) -m optimatrix simulate \
		--scenario all \
		--output build/business-acceptance.json \
		--case-root build/simulation-cases

check-core: compile test simulate

check: format-check lint type-check check-core
