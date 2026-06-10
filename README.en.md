# PPT Library

PPT Library is a local-first CLI for indexing, searching, reviewing, and reusing PPTX slide assets with AI agents. It groups deck versions, exports review packs, tracks reuse signals, and keeps private presentation data on the user's machine.

It is useful when:

- Solution teams need to find reusable slides from years of historical decks.
- Sales engineering or consulting teams want to reduce repeated slide work.
- AI agents need a reliable CLI instead of guessing from folders and filenames.
- A project has many PPT versions, but search should show the best representative version by default.

## Key Features

- **Slide-level search**: extracts slide text, screenshots, embeddings, and metadata.
- **Version governance**: groups related PPT versions and prioritizes representative versions in search.
- **Deck insights**: stores deck-level project, client, industry, scenario, structure, and summary fields.
- **Important slide candidates**: identifies high-value slides for reuse, review, or later vision enrichment.
- **Usage tracking**: records slide reuse, deal outcomes, and ranking feedback.
- **Compose workflow**: selects relevant slides from a brief and builds reviewable PPTX drafts.
- **Agent-friendly CLI**: JSON output for Codex, Claude Code, Hermes, OpenCode, and other agent runtimes.
- **Local-first storage**: SQLite, rendered screenshots, HTML previews, and derived assets stay on the local machine.
- **Recommended recognition stack**: local embeddings plus PaddleOCR MCP for slide OCR, layout, and chart parsing with low local memory pressure.

## What's Included

| Path | Purpose |
|---|---|
| `ppt_lib/` | CLI and core runtime |
| `skills/ppt-library/` | Agent Skill for safely operating `ppt-lib` |
| `docs/quick-start-guide.md` | Full setup, indexing, and search guide |
| `docs/guides/asset-intelligence-demo.md` | Synthetic demo for key pages, review packs, usage tracking, and business ranking |
| `docs/guides/library-build-guideline.md` | Safe local library build process |
| `docs/guides/open-source-release-checklist.md` | Release hygiene checklist for public snapshots |
| `docs/guides/model-compatibility.md` | LM Studio, PaddleOCR MCP, Ollama, and OpenAI-compatible model guidance |
| `docs/guides/recommended-implementation.md` | Recommended local embedding + PaddleOCR MCP implementation |
| `docs/specs/` | Module specs for CLI, database, search, screenshots, and vision |

## Requirements

- Python 3.12+
- LibreOffice, optional, used for PPTX slide screenshots
- LM Studio, Ollama, or an OpenAI-compatible API, optional, used for embeddings
- PaddleOCR MCP, optional and recommended for PPT slide OCR, layout, and chart parsing

Without a model service, PPT Library can still extract text and run lexical search. Search quality improves significantly after configuring embeddings.

## Installation

The public source release is intended to be installed from the repository until a PyPI package is published.

```bash
git clone https://github.com/MainQuestAI/PPT-Library.git
cd PPT-Library

# Install development and test dependencies.
uv sync --extra test --extra lint

# Recommended when using PaddleOCR MCP.
uv sync --extra test --extra lint --extra paddleocr

# Run the CLI from the source tree.
uv run ppt-lib --help

# Or install it as a local CLI tool.
uv tool install .
```

Editable install is also supported:

```bash
pip install -e .
```

`ppt-library` is the Python package name. `ppt-lib` is the command name.

## Quick Start for Humans

Use this path for your first manual library build and search.

```bash
# 1. Initialize configuration.
uv run ppt-lib setup --quick

# Recommended recognition stack: local embeddings + PaddleOCR MCP.
uv run ppt-lib setup --mode lmstudio
uv run ppt-lib setup --mode paddleocr-mcp

# 2. Create a source manifest.
uv run ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output ./ppt-sources.json

# 3. Load the source manifest.
uv run ppt-lib init --manifest ./ppt-sources.json --non-interactive

# 4. Preview the scan scope.
uv run ppt-lib sources scan --dry-run

# 5. Confirm the scan scope.
uv run ppt-lib sources scan --apply

# 6. Build the index.
uv run ppt-lib index --from-sources --file-workers 2

# 7. Search and generate an HTML review page.
uv run ppt-lib search "technical architecture" --html

# 8. Fill deck insights and inspect key pages.
uv run ppt-lib enrich-decks --pending --limit 20
uv run ppt-lib insights key-pages --output json
```

Search HTML is written to `~/.ppt-library/html/search-review-*.html`.

Minimal source manifest:

```json
{
  "sources": {
    "library": [
      "/path/to/your/ppt-folder"
    ],
    "exclude": []
  }
}
```

For the first run, start with a small PPTX folder before expanding to the full library.

## Quick Start for Agents

Agents should treat `ppt-lib` as the stable tool boundary and prefer JSON output.

```bash
# 1. Use a temporary home-dir for smoke tests.
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test

# 2. Build only after the user confirms the source scope.
uv run ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output ~/.ppt-library/sources/sources-manifest.json --output json
uv run ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
uv run ppt-lib sources scan --dry-run --output json
uv run ppt-lib sources scan --apply --output json
uv run ppt-lib index --from-sources

# 3. Search with JSON and inspect _errors.
uv run ppt-lib search "customer success case study" --top-k 8 --output json

# 4. Inspect reusable key pages and export a review pack.
uv run ppt-lib enrich-decks --pending --limit 20 --output json
uv run ppt-lib insights key-pages --output json
uv run ppt-lib insights review-pack --output /tmp/ppt-lib-review-pack.jsonl

# 5. Compose with dry-run first, then execute a confirmed plan.
uv run ppt-lib compose --brief "Create a customer success proposal deck" --dry-run
uv run ppt-lib compose --confirm /path/to/narrative-plan.json
```

Agent integration rules:

- Prefer `--output json` and treat stdout JSON as the source of truth.
- Check `_errors`, failed jobs, and fallback warnings before reporting success.
- Run `sources scan --dry-run` before indexing, then ask the user to confirm before `sources scan --apply`.
- Avoid scanning downloads, caches, chat app file caches, or other high-risk directories unless the user explicitly confirms the scope.
- Start `watch` only when the user explicitly asks for continuous folder watching.
- Keep customer paths, real PPT files, screenshots, HTML previews, and local databases on the user's machine.

See [skills/ppt-library/SKILL.md](skills/ppt-library/SKILL.md) for the full agent operating contract.

## Installing the Agent Skill

This repository includes a `ppt-library` Skill that can be copied into local agent runtimes.

```bash
# Codex
mkdir -p ~/.codex/skills/ppt-library
rsync -a skills/ppt-library/ ~/.codex/skills/ppt-library/

# Claude Code
mkdir -p ~/.claude/skills/ppt-library
rsync -a skills/ppt-library/ ~/.claude/skills/ppt-library/
```

For other agents, copy the full `skills/ppt-library/` directory to the local skills directory, or attach `skills/ppt-library/SKILL.md` as task context.

Smoke prompt after installation:

```text
Use the ppt-library skill. Check whether PPT Library is usable on this machine without indexing any private files. Report CLI availability, JSON schema health, index status, and model diagnostics.
```

See [Agent Adapters](skills/ppt-library/references/agent-adapters.md) for host-specific notes.

## Common Workflows

| Goal | Command |
|---|---|
| Check CLI version | `ppt-lib --version` |
| Initialize config | `ppt-lib setup --quick --non-interactive` |
| Inspect health | `ppt-lib doctor --output json` |
| Inspect index status | `ppt-lib status --output json` |
| Index one deck | `ppt-lib index /path/to/deck.pptx` |
| Index from sources | `ppt-lib index --from-sources` |
| Search slides | `ppt-lib search "query" --top-k 8` |
| Generate HTML review | `ppt-lib search "query" --html` |
| Include historical versions | `ppt-lib search "query" --include-versions` |
| Inspect version coverage | `ppt-lib versions status` |
| Inspect a deck family | `ppt-lib versions inspect <family-id>` |
| Recompute version families | `ppt-lib versions recompute --dry-run` |
| Fill deck insights | `ppt-lib enrich-decks --pending --limit 20` |
| Inspect key page candidates | `ppt-lib insights key-pages --output json` |
| Export review pack | `ppt-lib insights review-pack --output /path/to/review-pack.jsonl` |
| Record deal context | `ppt-lib record-deal --name "..." --outcome won --description "..." --industry retail --scenario proposal --tags demo,key-page` |
| Search with business ranking | `ppt-lib search "query" --ranking business --output json` |
| Preview compose | `ppt-lib compose --brief "..." --dry-run` |
| Assemble from confirmed plan | `ppt-lib compose --confirm /path/to/narrative-plan.json` |

## Version-Aware Search

Long-running projects often produce many PPT versions. PPT Library groups similar decks into a deck family and marks a representative version.

Default search shows representative versions first to reduce duplicate results:

```bash
ppt-lib search "project retrospective"
```

When you need historical versions:

```bash
ppt-lib search "project retrospective" --include-versions
ppt-lib versions inspect <family-id>
```

Representative versions are the default search view. Historical versions remain in the local library.

## Configuration

PPT Library uses local capabilities first. After configuring an embedding model, search improves from lexical matching to semantic retrieval.

- OpenAI-compatible API: set `PPT_LIB_OPENAI_API_KEY` or configure `embedding_api_url`.
- LM Studio: start the local OpenAI-compatible server, then run `ppt-lib setup --quick`.
- Ollama: configure the OpenAI-compatible endpoint and embedding model.

More details:

- [Quick Start Guide](docs/quick-start-guide.md)
- [Model Compatibility](docs/guides/model-compatibility.md)

## Data and Privacy

PPT Library stores local data under `~/.ppt-library/` by default:

- SQLite index database
- Slide screenshots
- Search HTML previews
- Compose manifests and local outputs

The public repository does not contain real PPT files, customer materials, sample screenshots, or local databases. Keep `.pptx`, `.db`, `.env`, screenshots, and exported outputs out of public commits.

## Documentation

- [Quick Start Guide](docs/quick-start-guide.md)
- [Library Build Guideline](docs/guides/library-build-guideline.md)
- [Asset Intelligence Demo](docs/guides/asset-intelligence-demo.md)
- [Open Source Release Checklist](docs/guides/open-source-release-checklist.md)
- [Model Compatibility](docs/guides/model-compatibility.md)
- [Agent Adapters](skills/ppt-library/references/agent-adapters.md)
- [Specs](docs/specs/README.md)

## Development

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run python scripts/release_check.py --output json
uv build
```

Current baseline: 534 automated tests.

## License

Apache License 2.0. See [LICENSE](LICENSE).
