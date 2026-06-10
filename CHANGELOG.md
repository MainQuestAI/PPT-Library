# Changelog

All notable changes to this project will be documented in this file.

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
