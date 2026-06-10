# Recommended Implementation: Local Embeddings + PaddleOCR MCP

This is the recommended setup for users who need a practical, low-cash-cost PPT asset library with useful slide-level visual understanding.

## Why This Stack

PPT Library has two separate model needs:

- **Embedding** turns slide text into vectors for search and ranking.
- **Vision/OCR** reads rendered slide images so pages with diagrams, screenshots, tables, and low-text layouts can still become searchable assets.

For most local machines, a small local embedding model is inexpensive to run and usually consumes around 1GB of memory per model instance. PaddleOCR MCP then handles page-level OCR and layout parsing through an external document OCR service, avoiding the higher local memory cost of running a large multimodal model.

PaddleOCR-VL is designed for document parsing and can return structured Markdown/JSON from images or PDFs. AI Studio account quota and free allowance can change; check the quota shown in your AI Studio console before a large run.

## Recommended Setup

Install the CLI with the PaddleOCR MCP extra:

```bash
uv sync --extra test --extra lint --extra paddleocr
```

Configure local embeddings first:

```bash
uv run ppt-lib setup --mode lmstudio
```

Then configure PaddleOCR MCP as the vision provider:

```bash
uv run ppt-lib setup --mode paddleocr-mcp
```

Keep the AI Studio token outside `config.yml`:

```bash
export PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN="<your-token>"
```

If your AI Studio endpoint is not the default package endpoint, set:

```bash
export PADDLEOCR_MCP_AISTUDIO_BASE_URL="<your-aistudio-base-url>"
```

Run diagnostics:

```bash
uv run ppt-lib doctor --output json
uv run ppt-lib models test --output json
```

## Build Flow

Create and confirm a sources manifest before indexing:

```bash
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ~/.ppt-library/sources/sources-manifest.json \
  --output json

uv run ppt-lib init \
  --manifest ~/.ppt-library/sources/sources-manifest.json \
  --non-interactive \
  --output json

uv run ppt-lib sources scan --dry-run --output json
uv run ppt-lib sources scan --apply --output json
```

For a first run, keep the worker count conservative:

```bash
uv run ppt-lib index --from-sources --file-workers 2
```

Increase workers only after a small run succeeds:

```bash
uv run ppt-lib index --from-sources --file-workers 4
```

`--file-workers` parallelizes PPTX files. `max_workers` in `config.yml` still controls per-file screenshot rendering. For cloud OCR, start with 2 file workers to avoid service timeouts and database write contention, then increase carefully.

## Operational Notes

- Do not write access tokens to `config.yml`.
- Use `setup --mode paddleocr-mcp` only after local embedding is configured; it changes the vision provider and keeps embedding settings unchanged.
- Explicit `paddleocr_mcp` failures stop the indexing job instead of silently falling back to text extraction. This prevents false success when OCR service calls fail.
- If AI Studio returns 5xx errors or timeouts, pause the full run and retry later with fewer file workers.
- Use `ppt-lib status --output json` and `~/.ppt-library/sources/index-progress.json` to inspect progress.
- Confirm actual quota in AI Studio before large runs. If the console grants a daily page allowance, this path is usually the lowest cash-cost option compared with cloud multimodal LLM calls.
