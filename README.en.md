# PPT Library

> A local CLI for indexing, searching, versioning, and reusing PPTX slide assets.

PPT Library (`ppt-lib`) indexes PPTX files at the slide level. It extracts text, can render screenshots, stores local metadata in SQLite, and supports hybrid semantic + lexical search. It is designed for solution teams and AI agents that need to find and reuse slides from a local presentation library.

## Key Features

- **Slide-level indexing**: text extraction, screenshots, embeddings, and metadata.
- **Hybrid search**: semantic and lexical ranking with score breakdowns.
- **Deck versioning**: groups related PPT versions and hides older versions by default.
- **Usage tracking**: records slide usage, deal outcomes, and reuse metrics.
- **Compose workflow**: selects relevant slides from a brief and builds PPTX outputs.
- **CLI-first JSON output**: suitable for both humans and agent workflows.
- **Local-first storage**: SQLite database and local filesystem assets.

## Requirements

| Dependency | Required | Notes |
|---|---|---|
| Python | >= 3.12 | Required |
| LibreOffice | Optional | Used for slide screenshots |
| LM Studio / Ollama / cloud LLM | Optional | Used for embeddings, vision summaries, and annotation |

Runtime Python dependencies: `defusedxml`, `numpy`, `pydantic`, `PyYAML`, `watchdog`.

## Installation

The public source release is intended to be installed from the repository until a PyPI package is published.

```bash
# Install development dependencies.
uv sync --extra test --extra lint

# Run the CLI from the source tree.
uv run ppt-lib --help

# Or install it as a local CLI tool.
uv tool install .
```

`ppt-library` is the Python package name. `ppt-lib` is the command name.

## Quick Start

```bash
# 1. Initialize configuration.
uv run ppt-lib setup --quick

# 2. Index a PPTX file or directory.
uv run ppt-lib index path/to/deck.pptx

# 3. Search for slides.
uv run ppt-lib search "cloud migration architecture"

# 4. Include all historical deck versions when needed.
uv run ppt-lib search "cloud migration architecture" --include-versions
```

## CLI Reference

| Command | Description |
|---|---|
| `ppt-lib setup` | Initialize local config and database |
| `ppt-lib index <path>` | Index PPTX files |
| `ppt-lib search <query>` | Search slides |
| `ppt-lib versions status` | Inspect deck family/version coverage |
| `ppt-lib versions recompute` | Recompute deck families and representative versions |
| `ppt-lib enrich-decks --pending` | Fill deck-level insights and important slide candidates |
| `ppt-lib compose <brief>` | Select and assemble slides from a brief |
| `ppt-lib config show` | Display configuration |
| `ppt-lib schema --output json` | Print the CLI schema |

Use `--output json` where supported for machine-readable output.

## Testing

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv build
```

Current baseline: 506 automated tests.

## License

MIT. See [LICENSE](LICENSE).
