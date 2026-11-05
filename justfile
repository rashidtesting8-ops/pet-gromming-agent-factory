# Justfile for Pet Grooming Website Builder Engine

default: lint typecheck test

lint:
    uv run ruff check .

typecheck:
    uv run pyright

test:
    uv run pytest

