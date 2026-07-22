UV ?= uv
PYTHON ?= .venv/bin/python

.PHONY: sync format format-check lint type-check test check

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

test:
	$(PYTHON) -m pytest

check: format-check lint type-check test
