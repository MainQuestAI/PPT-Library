# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2026-06-24

### Added
- **Asset Intelligence & Lineage** (v1.7): asset/revision/lineage schema, visual fingerprinting, near-duplicate classifier, lineage inference + cycle detection, classification pipeline, Bayesian feedback ranking v2, asset health detectors.
- **Local Review Workbench** (v1.8): application service layer, FastAPI REST API (18 endpoints + RBAC on write endpoints), workbench dashboard HTML, Server-Sent Events streaming, audit log.
- **Team Preview** (v1.9): repository Protocol interfaces (SQLite implementation), RBAC (4 roles / 16 permissions), Connector SDK (local filesystem connector + registry).
- **Enterprise GA** (v2.0): policy engine (DENY > APPROVAL > ALLOW), multi-workspace isolation, approval workflows, analytics aggregation, GA release gate (10 checks).

### Changed
- Version bumped to 2.0.0; DB SCHEMA_VERSION 4 → 5 (init_db now creates v5 identity/job tables).
- `ppt-lib capabilities` now reports `db_schema_version=5`, `producer_version=2.0.0`, and feature flags reflect implemented capabilities (workbench, ft5_search, asset_identity, job_engine, incremental_governance = True).
- `ppt-lib workbench start/status` CLI command added (requires `[workbench]` extra: fastapi, uvicorn, httpx2).
- `release_check.py` baseline 1083, version gate 2.0.0, JSON output hardened against bytes serialization.

### Tests
- Current automated baseline: 1083 tests (up from 653 at v1.5.0).

## [1.5.0] - 2026-06-23

### Added
- **Contract Registry** (`ppt_lib/contracts/`): lazy-loading registry for 7 JSON Schema contracts with validation, envelope v2 builder, and stable error code system.
- **Runtime Capabilities** (`ppt-lib capabilities`): detects providers, features, storage backends, and contracts from the real environment.
- **Contract CLI** (`ppt-lib contract list/show/validate`): inspect and validate machine contracts against schemas.
- **Stable Asset Identity** (`ppt_lib/identity/`): content fingerprinting for `slide_revision_id` and `deck_revision_id`, canonical/revision identity mapping, registry export/import.
- **Schema v5 Migration** (`ppt_lib/migrations/`): plan/apply/verify/restore operations with backup, journal tracking, and identity backfill.
- **Job Engine** (`ppt_lib/jobs/`): state machine with create/start/complete/fail/cancel/retry lifecycle, stage tracking, event emission, idempotency keys, and progress reporting.
- **Incremental Governance** (`ppt_lib/governance.py`): affected-scope detection for duplicate groups and deck families, manual override preservation, consistency validation.
- **PPTX Safety** (`ppt_lib/pptx_safety.py`): archive limits, path traversal detection, external relationship inventory, embedded object warnings, and structured safety reports.

### Changed
- DB `SCHEMA_VERSION` bumped from 4 to 5 (identity + job engine + contract registry tables).
- New `ppt_lib/services/` directory for application services.
- New `ppt_lib/contracts/` directory for contract registry and error codes.

### Tests
- Current automated baseline: 653 tests.
- Added: contract registry (21), capabilities CLI (19), identity (21), migration (13), job engine (25), governance + safety (20).

## [1.4.1] - 2026-06-10

### Added
- PaddleOCR MCP vision provider for slide OCR, layout parsing, chart recognition, and Markdown extraction.
- `paddleocr` optional dependency extra for installing `paddleocr-mcp`.
- `ppt-lib setup --mode paddleocr-mcp` for switching vision recognition without changing the embedding provider.
- `ppt-lib index --from-sources --file-workers N` for PPTX file-level parallel indexing.
- Recommended implementation guide for local embeddings plus PaddleOCR MCP.

### Changed
- Recommended model guidance now prioritizes local embeddings plus PaddleOCR MCP for low-cash-cost batch recognition.
- SQLite connection timeout increased to make conservative file-level parallel indexing more reliable.
- Explicit PaddleOCR MCP failures stop indexing instead of silently falling back to text extraction.

### Tests
- Current automated baseline: 534 tests.

## [1.4.0] - 2026-06-06

### Added
- `ppt-lib insights key-pages` for reusable key page reports.
- `ppt-lib insights review-pack` for JSONL/JSON slide review exports.
- Structured `record-deal` description fields: `--description`, `--industry`, `--scenario`, and `--tags`.
- Search JSON and HTML now expose key page and business ranking signals.
- Synthetic asset intelligence demo deck generator.
- Open-source release check script and public release checklist.

### Changed
- Demo deck generation now uses `python-pptx` through the optional `demo` extra.
- Search review HTML has responsive mobile layout and wraps long metadata fields.
- README, English README, Quick Start, Agent Skill, and CLI spec now include the asset intelligence workflow.

### Tests
- Current automated baseline: 518 tests.
- Added CLI coverage for insights, review-pack exports, structured deal notes, and search explainability fields.

## [1.3.0] - 2026-05-28

### Added
- `ppt-lib setup --quick` — environment-aware auto-detection for Quick Start
- `ppt_lib/setup_probe.py` — module that detects OpenAI API key, LM Studio, or Ollama and recommends best config
- `docs/quick-start-guide.md` — complete first-time setup guide for Quick Pass and Full Pass
- `docs/guides/model-compatibility.md` — embedding and vision provider comparison matrix

### Changed
- `ppt-lib setup` now offers interactive Quick Start / Production mode selection when run without flags
- README rewritten — problem-first, user-oriented onboarding with 5-minute Quick Start

### Tests
- Added 10 tests for `setup_probe` module covering all detection paths and configuration recommendations

## [1.2.0] - 2026-05-27

### Added
- `ppt-lib models test` command to probe all configured model capabilities (embedding, chat, vision, json_schema)
- Model compatibility gate module (`model_compat.py`) with unified chat response extraction, embedding probe, and capability cache
- Independent embedding probe in diagnostics (`ppt-lib vision`) that sends a real embedding request to verify endpoint, model, and dimensions
- Explicit model selection for LM Studio calls — no more silent auto-detection of the first available model

### Changed
- `call_lmstudio()` now requires a configured model instead of auto-detecting from the `/models` endpoint
- Unified chat response extraction across `llm_client`, `vision`, and `diagnostics` via `model_compat.extract_chat_text()`
- Diagnostics prefer independent embedding probe over LM Studio status when available

### Fixed
- Ruff lint errors (unused imports, line length) in model compatibility gate files
