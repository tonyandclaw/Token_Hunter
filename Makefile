PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install run test test-one lint format audit clean

help:
	@echo "make install  - create venv and install editable package + dev deps"
	@echo "make run      - launch Telegram webhook (src/main.py)"
	@echo "make test     - run pytest"
	@echo "make test-one T=tests/test_x.py::test_y - run a single test"
	@echo "make lint     - ruff check + format check"
	@echo "make format   - ruff format in place"
	@echo "make audit    - pip-audit (run weekly per docs/04 §B)"

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: $(BIN)/python
	$(BIN)/pip install -e ".[dev]"

run:
	$(BIN)/python -m src.main

test:
	$(BIN)/pytest -q

test-one:
	$(BIN)/pytest -q $(T)

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

audit:
	$(BIN)/pip-audit

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache **/__pycache__ *.egg-info build dist
