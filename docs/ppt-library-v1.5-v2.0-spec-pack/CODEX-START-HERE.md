# Codex Start Here

## 1. 第一个任务

先执行 `1.5-A — Baseline Verification & ADR Pack`，不要直接开始 Job Engine 或 UI。

## 2. 核验命令

```bash
git fetch origin
git checkout main
git pull --ff-only
git rev-parse HEAD
cat VERSION
grep '^version' pyproject.toml
grep -R 'SCHEMA_VERSION' -n ppt_lib
uv sync --extra test --extra lint
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run ppt-lib schema --output json
uv run python scripts/release_check.py --output json
uv build
```

## 3. 必须输出的基线报告

```text
- HEAD
- version
- DB schema
- commands
- modules
- test baseline/result
- current migrations
- current release blockers
- current Deck Master contract shape
- Spec conflicts
- accepted ADR list
```

## 4. 开发顺序

```text
1.5-A → 1.5-B → 1.5-C
     ↘ 1.5-D → 1.5-E → 1.5-F
                    ↘ 1.5-G
                         ↓
                       1.5-H
```

v1.5 完成质量门后才能开始 v1.6 默认检索替换。

## 5. 开发边界

- 不做 Big Bang 目录重构；
- 不改变三项目边界；
- 不把 DB row id 作为跨系统主键；
- 不用新 UI 掩盖底层能力；
- 不提交真实 PPT/截图/数据库；
- 不宣称未实测的平台支持；
- 不静默 fallback；
- 不在 migration 失败后继续写入。

## 6. 标准任务 Prompt

请复制 `13-agent-execution-task-pack.md` 末尾模板，并填入唯一 Task ID。
