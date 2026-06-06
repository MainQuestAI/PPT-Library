# Contributing to PPT Library

Thanks for contributing to PPT Library. This project is a local-first CLI, so contributions should keep private files and generated local assets out of the repository.

## Development Setup

```bash
uv sync --extra test --extra lint
uv run ppt-lib --help
```

For demo deck generation:

```bash
uv sync --extra demo
uv run --extra demo python scripts/create_demo_decks.py --output /tmp/ppt-lib-demo-decks
```

## Validation

Run these checks before opening a pull request:

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv build
```

For release-related changes, also run:

```bash
uv run python scripts/release_check.py --output json
```

## Pull Request Rules

- Keep changes scoped to one clear goal.
- Add focused tests for CLI behavior, database behavior, or generated HTML behavior when relevant.
- Do not commit real PPT files, screenshots, local databases, `.env` files, model outputs, or customer material.
- Use synthetic fixtures and generated demo files under `/tmp` for local smoke tests.
- Treat `ppt-lib --output json` as a stable contract for agents.

## Public Snapshot Rule

The development repository and public repository have separate histories. Public releases must be prepared as clean snapshots, not by pushing private development history.
