# List available recipes.
help:
    @just --list --unsorted

# Run unit tests.
[group('Testing')]
test:
    uv run pytest --spec

# Run unit tests with coverage report.
[group('Testing')]
test-cov:
    uv run pytest --cov --spec

# Run unit tests with coverage on every supported Python version.
[group('Testing')]
test-all:
    uv run tox run-parallel

# Run linting and formatting checks.
[group('Checks')]
lint:
    uv run deptry .
    uv run ruff format --check .
    uv run ruff check .

# Run static typing analysis.
[group('Checks')]
type:
    uv run pyrefly check

# Run dead-code and maintainability analysis.
[group('Checks')]
analyze:
    uvx vulture --min-confidence 100 birling/
    uvx radon mi --show --multi --min B birling/

# Run all checks.
[group('Checks')]
check: lint type analyze

# Serve the documentation site locally, rebuilding it on changes.
[group('Documentation')]
docs:
    uv run --group docs mkdocs serve

# Build the documentation site into `site/`.
[group('Documentation')]
docs-build:
    uv run --group docs mkdocs build --strict

# Reformat the code and sort imports using ruff.
[group('Development')]
[confirm]
reformat:
    uv run ruff format .
    uv run ruff check --select I --fix .

# Extract current production requirements. Save to a file by appending `> requirements.txt`.
[group('Development')]
reqs:
    uv export --no-default-groups
