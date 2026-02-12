.PHONY: install
install:
	uv sync

.PHONY: test
test:
	uv run pytest tests.py

.PHONY: lint
lint:
	uv run ruff check migrate.py --fix
