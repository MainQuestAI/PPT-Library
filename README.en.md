# PPT Library

> Local-first PPT asset intelligence for humans and AI agents.

English | [中文](README.md)

PPT Library is a local-first PPTX asset library. It indexes historical decks at slide level so teams and AI agents can search, review, reuse, compose, and govern presentation assets.

Current public release: **v2.0.0**
Database schema: **v5**
License: **Apache-2.0**

## Who It Is For

- Solution, sales engineering, and consulting teams that need to find reusable slides from years of historical decks.
- Individual developers and AI Coding users who want a stable PPT tool boundary for Codex, Claude Code, OpenCode, and similar agents.
- Teams with many versions of the same project deck that want representative search results by default.
- Teams that want to turn PPT folders into searchable, reusable, governed assets.

## v2.0.0 Capability Overview

| Capability | Status | Notes |
|---|---:|---|
| Slide-level search | Implemented | Keyword search, FTS5, local embeddings, and HTML review pages |
| Version governance | Implemented | Similar decks are grouped into deck families; representative versions are prioritized |
| Asset identity | Implemented | Schema v5 introduces asset/revision/lineage identity |
| Near-duplicate detection | Implemented | Combines text, visual fingerprint, and structure signals |
| Key pages and reuse tracking | Implemented | Key page candidates, deal outcomes, usage records, and business ranking |
| Compose workflow | Implemented | Selects slides from a brief and produces reviewable plans and PPTX drafts |
| Job Engine | Implemented | Background job model, status lifecycle, and tests |
| Local Workbench | Implemented | FastAPI service, Workbench shell, SSE progress, and health events |
| RBAC / Workspace | Implemented | Roles, permissions, workspace isolation, and audit logging |
| Policy and approvals | Implemented | Policy engine, approval workflows, governance metrics |
| Server deployment | Not deployed | The public release focuses on local operation; production deployment tooling is deferred |
| ANN search | Not deployed | The default retrieval path uses SQLite, FTS5, and embeddings |

## Principles

- **Local first**: real PPT files, screenshots, HTML previews, and SQLite databases stay on the user's machine by default.
- **Agent friendly**: the CLI supports JSON output and is safe to call from AI agents.
- **Human reviewable**: search, key page, compose, and governance results can be exported as review packs.
- **Team governable**: v2.0.0 adds workspace, RBAC, policy, approval, audit, and analytics foundations.
- **Clean public snapshot**: the public repository contains no real customer PPTs, screenshots, local databases, secrets, or build artifacts.

## Installation

The public release is intended to be installed from source until a PyPI package is published.

```bash
git clone https://github.com/MainQuestAI/PPT-Library.git
cd PPT-Library

# Development, test, and lint dependencies.
uv sync --extra test --extra lint

# Local Workbench dependencies.
uv sync --extra test --extra lint --extra workbench

# PaddleOCR MCP dependencies.
uv sync --extra test --extra lint --extra paddleocr

# Run the CLI from the source tree.
uv run ppt-lib --help

# Install as a local CLI tool.
uv tool install .
```

Editable install is also supported:

```bash
pip install -e .
```

`ppt-library` is the Python package name. `ppt-lib` is the command name.

## Quick Start

### 1. Initialize Local Config

```bash
uv run ppt-lib setup --quick
uv run ppt-lib doctor --output json
uv run ppt-lib capabilities --output json
```

### 2. Create a Source Manifest

```bash
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ./ppt-sources.json
```

Minimal manifest:

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

### 3. Preview the Scan Scope

```bash
uv run ppt-lib init --manifest ./ppt-sources.json --non-interactive
uv run ppt-lib sources scan --dry-run
```

After confirming the scope:

```bash
uv run ppt-lib sources scan --apply
```

### 4. Index and Search

```bash
uv run ppt-lib index --from-sources --file-workers 2
uv run ppt-lib search "technical architecture" --top-k 8 --output json
uv run ppt-lib search "technical architecture" --html
```

HTML search output is written to:

```text
~/.ppt-library/html/search-review-*.html
```

### 5. Key Pages, Reuse, and Compose

```bash
uv run ppt-lib enrich-decks --pending --limit 20 --output json
uv run ppt-lib insights key-pages --output json
uv run ppt-lib insights review-pack --output /tmp/ppt-lib-review-pack.jsonl

uv run ppt-lib compose --brief "Create a customer success proposal deck" --dry-run
uv run ppt-lib compose --confirm /path/to/narrative-plan.json
```

## Local Workbench

v2.0.0 includes the local Workbench service path:

```bash
uv sync --extra workbench

uv run ppt-lib workbench start --host 127.0.0.1 --port 8765
uv run ppt-lib workbench status --output json
```

The Workbench currently includes:

- FastAPI REST API
- Standard response envelope
- RBAC protection for write endpoints
- SSE job progress and health events
- audit log
- responsive dashboard shell

Full search, asset, and health detail pages are planned for later releases.

## Agent Usage

Agents should treat `ppt-lib` as the stable tool boundary and prefer JSON output.

```bash
# Use a temporary home-dir for smoke tests.
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test

# Build only after the user confirms the source scope.
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ~/.ppt-library/sources/sources-manifest.json \
  --output json
uv run ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
uv run ppt-lib sources scan --dry-run --output json
uv run ppt-lib sources scan --apply --output json
uv run ppt-lib index --from-sources

# Search with JSON and inspect _errors.
uv run ppt-lib search "customer success case study" --top-k 8 --output json
```

Agent integration rules:

- Prefer `--output json`.
- Check `_errors`, failed jobs, and fallback warnings before reporting success.
- Run `sources scan --dry-run` before indexing, then ask the user to confirm before `sources scan --apply`.
- Avoid downloads, trash, caches, dependency folders, and chat app file caches unless the user explicitly confirms the scope.
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

## Common Commands

| Goal | Command |
|---|---|
| Check version | `ppt-lib --version` |
| Initialize config | `ppt-lib setup --quick --non-interactive` |
| Inspect health | `ppt-lib doctor --output json` |
| Inspect capabilities | `ppt-lib capabilities --output json` |
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
| Start Workbench | `ppt-lib workbench start --host 127.0.0.1 --port 8765` |
| Check Workbench status | `ppt-lib workbench status --output json` |

## Data and Privacy

PPT Library stores local data under `~/.ppt-library/` by default:

- SQLite index database
- Slide screenshots
- Search HTML previews
- Compose manifests and local outputs

The public repository contains no real PPT files, customer materials, sample screenshots, or local databases. Keep `.pptx`, `.db`, `.env`, screenshots, and exported outputs out of public commits.

## Documentation

- [Quick Start Guide](docs/quick-start-guide.md)
- [v2.0.0 Release Notes](docs/releases/v2.0.0.md)
- [v1.5-v2.0 Iteration Report](docs/iterations/v1.5-v2.0-iteration-report.md)
- [Spec Pack](docs/ppt-library-v1.5-v2.0-spec-pack/README.md)
- [Asset Intelligence Demo](docs/guides/asset-intelligence-demo.md)
- [Library Build Guideline](docs/guides/library-build-guideline.md)
- [Agent Install and Guided Library Build](docs/guides/agent-install-and-build-guideline.md)
- [Model Compatibility](docs/guides/model-compatibility.md)
- [Recommended Implementation](docs/guides/recommended-implementation.md)
- [Open Source Release Checklist](docs/guides/open-source-release-checklist.md)
- [Specs](docs/specs/README.md)
- [ADR](docs/adr/001-stable-asset-identity.md)

## Development and Verification

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run python scripts/release_check.py --output json
uv build
```

v2.0.0 public snapshot baseline:

- 1083 automated tests
- ruff clean
- mypy clean
- `uv build` produces `ppt_library-2.0.0`
- `release_check` covers metadata, pytest, ruff, mypy, build, and demo smoke

## Known Limitations

- Job Engine commands such as `jobs list/inspect/cancel` are not wired into the main CLI yet.
- Workbench search, asset, and health detail pages are planned for later releases.
- Postgres backend, OIDC, and production deployment tooling are deferred.
- Visual pHash and palette are placeholder implementations until the rendered image pipeline is connected.

## License

Apache License 2.0. See [LICENSE](LICENSE).
