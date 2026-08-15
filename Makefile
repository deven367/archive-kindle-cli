# archive-kindle-cli development targets (uv-based)
.PHONY: env sync test

## env — create the virtualenv and install the package with dev extras
env:
	uv venv
	uv pip install -e '.[dev]'

## sync — refresh uv.lock and sync the environment to it (dev extras included)
sync:
	uv lock
	uv sync --extra dev

## test — run the test suite (requires coverage >= 75%)
test:
	uv run pytest
