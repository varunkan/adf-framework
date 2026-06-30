# ANDS platform — common tasks. Run from apps/ands-platform/.
VENV := .venv
PY := $(VENV)/bin/python

.PHONY: help venv test up down logs clean

help:
	@echo "venv  - create the dev venv and install the toolchain"
	@echo "test  - run every service + gateway + integration suite (verify.sh)"
	@echo "up    - docker compose up --build (full mesh: per-service PG + Redis + gateway)"
	@echo "down  - docker compose down -v"
	@echo "clean - remove the venv and caches"

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements-dev.txt

test:
	./verify.sh

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f gateway

clean:
	rm -rf $(VENV) .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
