.PHONY: install
install:
	uv sync

.PHONY: test
test:
	uv run pytest tests

.PHONY: lint
lint:
	uv run ruff check migrate.py tests --fix
