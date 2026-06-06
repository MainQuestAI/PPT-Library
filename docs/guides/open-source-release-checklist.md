# Open Source Release Checklist

Use this checklist before preparing a public snapshot of PPT Library.

## Required Checks

- Working tree is clean except for intentional release files.
- `origin` points to the development repository.
- `public` points to `https://github.com/MainQuestAI/PPT-Library.git`.
- Tracked files do not include `.pptx`, `.ppt`, `.db`, `.sqlite`, `.env`, screenshots, HTML exports, caches, or generated demo outputs.
- Repository content does not include local absolute paths, private repository URLs, secrets, or real customer material.
- `README.md`, `README.en.md`, `CHANGELOG.md`, and `VERSION` all match the release version.
- The automated test baseline in README files matches the current test count.

## Required Commands

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv build
uv run python scripts/release_check.py --output json
```

## Demo Smoke

```bash
uv run --extra demo python scripts/create_demo_decks.py --output /tmp/ppt-lib-demo-decks
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources manifest --library /tmp/ppt-lib-demo-decks --manifest-output /tmp/ppt-lib-demo/sources-manifest.json --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo init --manifest /tmp/ppt-lib-demo/sources-manifest.json --non-interactive --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --dry-run --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --apply --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo index --from-sources
uv run ppt-lib --home-dir /tmp/ppt-lib-demo enrich-decks --pending --limit 20 --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo insights key-pages --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo search "业务架构 价值" --ranking business --threshold 0.0 --html
```

Expected result:

- Key page candidates are returned.
- Review-pack export succeeds.
- Search HTML shows key page labels and business fields.
- With LibreOffice installed, search HTML includes rendered slide screenshots.

## Public Snapshot Rule

Prepare public releases from a clean snapshot worktree based on `public/main`. Do not push development repository history to the public repository.
