# Contributing to Spore

Thanks for your interest in contributing! Here's everything you need to get started.

## Prerequisites

- **Python 3.11 or later** — Check with `python3 --version`
- **Git** — Check with `git --version`

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/spore-protocol/spore.git
cd spore

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 3. Install Spore in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Verify everything works
pytest
ruff check src/ tests/
```

If all tests pass and ruff reports no errors, you're good to go.

## Project Structure

```
src/spore/
├── __init__.py     # Public API exports
├── models.py       # Protocol data models (Finding, Experiment, Direction)
├── repo.py         # SporeRepo — main interface, Git operations
├── index.py        # SQLite FTS5 index for fast local search
└── cli.py          # Click CLI commands with Rich output

tests/
├── conftest.py     # Shared test fixtures
├── test_models.py  # Unit tests for protocol models
├── test_repo.py    # Unit tests for SporeRepo
├── test_index.py   # Unit tests for SQLite index
├── test_cli.py     # CLI integration tests
└── test_e2e.py     # End-to-end workflow tests
```

## Development Workflow

1. Create a branch for your changes: `git checkout -b my-feature`
2. Make your changes in `src/spore/`
3. Add or update tests in `tests/`
4. Run the checks below before opening a PR

## Testing

Run the full test suite:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=spore --cov-report=term-missing
```

Run a specific test file or test:

```bash
pytest tests/test_models.py
pytest tests/test_repo.py::TestPublishFinding::test_creates_finding
```

All new functionality needs tests. We aim for high coverage across models, repo operations, and CLI commands.

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. Line length is 100 characters.

Check for issues:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

Auto-fix:

```bash
ruff check --fix src/ tests/
ruff format src/ tests/
```

## Pull Request Guidelines

- Write a clear description of what your PR does and why
- All tests must pass (`pytest`)
- Code must pass `ruff check` and `ruff format --check`
- Include tests for new functionality
- Keep changes focused — one feature or fix per PR
