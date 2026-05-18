.PHONY: install-dev lint test verify

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.venv:
	python3 -m venv .venv

install-dev: .venv
	$(PIP) install -e ".[dev]"

lint: .venv
	$(PYTHON) -m ruff check .

test: .venv
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q

verify: lint test
