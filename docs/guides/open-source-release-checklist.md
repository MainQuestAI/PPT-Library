# Open Source Release Checklist

Use this checklist before preparing a public snapshot of PPT Library.

## Required Checks

- Working tree is clean except for intentional release files.
- `origin` points to the development repository.
- `public` points to `https://github.com/MainQuestAI/PPT-Library.git`.
- Stable release history is exactly `public/main` or one direct, non-merge snapshot commit above it; development versions may remain on the development repository history.
- Tracked files do not include `.pptx`, `.ppt`, `.db`, `.sqlite`, `.env`, screenshots, HTML exports, caches, or generated demo outputs.
- Repository content does not include local absolute paths, private repository URLs, secrets, or real customer material.
- Local `config.yml` has no plaintext secret fields; migrate any `CONFIG_PLAINTEXT_SECRET_DETECTED` warning to environment variables.
- `README.md`, `README.en.md`, `CHANGELOG.md`, and `VERSION` all match the release version.
- The built sdist and wheel contain only tracked, explicitly allowed release files, and their text content passes the private-data and secret-pattern scan.
- The direct build backend requirement is pinned exactly in `pyproject.toml`; dependency installation and validation use the committed lockfile.
- CI actions are pinned to full commit SHAs.

## Required Commands

```bash
uv lock --check
uv sync --locked --all-extras
uv run --locked --extra test --extra workbench pytest --cov=ppt_lib --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
uv run --locked python -c 'from pathlib import Path; from scripts.release_check import check_coverage_report; result = check_coverage_report(Path("coverage.json")); print(result); raise SystemExit(0 if result.status == "pass" else 1)'
uv run --locked --extra lint ruff check .
uv run --locked --extra lint mypy
uv export --all-extras --frozen --no-emit-project --no-hashes | uv run --locked --extra security pip-audit -r /dev/stdin --no-deps --disable-pip
uv run --locked --extra security bandit -r ppt_lib -lll
uv build --out-dir /tmp/ppt-lib-dist
uv run --locked python scripts/release_check.py --output json
```

`scripts/release_check.py` rebuilds the artifacts in an isolated temporary directory, verifies every archive member against the tracked release allowlist, rejects archive links, and scans archive text without printing matched secret values.

The coverage gate checks statement coverage at 80% or higher and branch coverage at 65% or higher as separate metrics. The quality job installs the `workbench` extra so API tests run with FastAPI available.

## Demo Smoke

```bash
uv run --locked --extra demo python scripts/create_demo_decks.py --output /tmp/ppt-lib-demo-decks
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo sources manifest --library /tmp/ppt-lib-demo-decks --manifest-output /tmp/ppt-lib-demo/sources-manifest.json --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo init --manifest /tmp/ppt-lib-demo/sources-manifest.json --non-interactive --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --dry-run --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --apply --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo index --from-sources
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo enrich-decks --pending --limit 20 --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo insights key-pages --output json
uv run --locked ppt-lib --home-dir /tmp/ppt-lib-demo search "业务架构 价值" --ranking business --threshold 0.0 --html
```

Expected result:

- Key page candidates are returned.
- Review-pack export succeeds.
- Search HTML shows key page labels and business fields.
- With LibreOffice installed, search HTML includes rendered slide screenshots.

## Public Snapshot Rule

Development versions use a PEP 440 pre-release suffix such as `2.0.1.dev0`. Their release check skips the public history gate so CI can validate normal development branches.

Stable versions use the exact `X.Y.Z` form. Their release check accepts `public/main` itself or one direct snapshot commit. Additional development commits and merge commits fail the gate.

Prepare stable public releases from a clean snapshot worktree based on `public/main`. Keep development repository history out of the public repository.
