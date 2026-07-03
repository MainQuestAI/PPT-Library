# PPT Library

> Local-first PPT asset intelligence for humans and AI agents.

[English](README.en.md) | 中文

PPT Library 是一个本地优先的 PPTX 资产库工具。它把历史 PPT 按页入库，让团队和 AI Agent 可以搜索、审查、复用、组装和治理幻灯片资产。

当前公开版本：**v2.0.0**
数据库 schema：**v5**
许可证：**Apache-2.0**

## 适合谁

- 方案、售前、咨询团队：从多年历史 PPT 中快速找可复用页面。
- 个人开发者和 AI Coding 用户：给 Codex、Claude Code、OpenCode 等 Agent 一个稳定的 PPT 工具入口。
- 有大量版本沉淀的团队：默认展示代表版本，需要审计时再展开历史版本。
- 想把 PPT 从“文件夹资产”升级成“可搜索、可复用、可治理资产”的团队。

## v2.0.0 能力概览

| 能力 | 状态 | 说明 |
|---|---:|---|
| 页级搜索 | 已实现 | 关键词、FTS5、本地 embedding 和 HTML 审查页 |
| 版本治理 | 已实现 | 相似 deck 自动归族，默认优先展示代表版本 |
| 资产身份 | 已实现 | schema v5，引入 asset/revision/lineage 身份体系 |
| 近重复识别 | 已实现 | 文本、视觉指纹和结构信号组合判断 |
| 关键页与复用追踪 | 已实现 | 支持关键页候选、战绩、使用记录和业务排序 |
| 自动组装 | 已实现 | 根据 brief 选择页面，生成可审查组装计划和 PPTX 草稿 |
| Job Engine | 已实现 | 后台任务模型、状态流转和测试覆盖已完成 |
| Local Workbench | 已实现 | FastAPI 服务、Workbench shell、SSE 进度和健康事件 |
| RBAC / Workspace | 已实现 | 角色、权限、workspace 隔离和审计日志 |
| 策略与审批 | 已实现 | policy engine、approval workflow、治理指标 |
| Server deployment | 未部署 | 当前公开版聚焦本地运行，生产部署工具后续补齐 |
| ANN search | 未部署 | 当前默认使用 SQLite/FTS5/embedding 检索链路 |

## 核心理念

- **本地优先**：真实 PPT、截图、HTML 预览和 SQLite 数据库默认留在用户本机。
- **Agent 友好**：CLI 默认可输出 JSON，适合被 AI Agent 安全调用。
- **人类可审查**：搜索、关键页、组装和治理结果都能导出审查包。
- **团队可治理**：v2.0.0 加入 workspace、RBAC、policy、approval、audit 和 analytics。
- **开源快照干净**：公开仓库不包含真实客户 PPT、截图、本地数据库、密钥或构建产物。

## 安装

当前公开版优先从源码安装。PyPI 发布前，请以本仓库源码安装方式为准。

```bash
git clone https://github.com/MainQuestAI/PPT-Library.git
cd PPT-Library

# 基础开发、测试、代码检查依赖
uv sync --extra test --extra lint

# 使用 Local Workbench 时安装
uv sync --extra test --extra lint --extra workbench

# 使用 PaddleOCR MCP 时安装
uv sync --extra test --extra lint --extra paddleocr

# 查看 CLI
uv run ppt-lib --help

# 安装为本地 CLI 工具
uv tool install .
```

也可以用 editable 模式安装：

```bash
pip install -e .
```

`ppt-library` 是 Python 包名，`ppt-lib` 是命令名。

## 快速开始

### 1. 初始化本地配置

```bash
uv run ppt-lib setup --quick
uv run ppt-lib doctor --output json
uv run ppt-lib capabilities --output json
```

### 2. 创建资料源清单

```bash
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ./ppt-sources.json
```

最小清单示例：

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

### 3. 预览扫描范围

```bash
uv run ppt-lib init --manifest ./ppt-sources.json --non-interactive
uv run ppt-lib sources scan --dry-run
```

确认范围后再写入本地状态：

```bash
uv run ppt-lib sources scan --apply
```

### 4. 建库和搜索

```bash
uv run ppt-lib index --from-sources --file-workers 2
uv run ppt-lib search "技术架构" --top-k 8 --output json
uv run ppt-lib search "技术架构" --html
```

HTML 搜索结果默认输出到：

```text
~/.ppt-library/html/search-review-*.html
```

### 5. 关键页、复用和组装

```bash
uv run ppt-lib enrich-decks --pending --limit 20 --output json
uv run ppt-lib insights key-pages --output json
uv run ppt-lib insights review-pack --output /tmp/ppt-lib-review-pack.jsonl

uv run ppt-lib compose --brief "生成一份客户成功案例方案" --dry-run
uv run ppt-lib compose --confirm /path/to/narrative-plan.json
```

## Local Workbench

v2.0.0 已接入本地 Workbench 服务链路：

```bash
uv sync --extra workbench

uv run ppt-lib workbench start --host 127.0.0.1 --port 8765
uv run ppt-lib workbench status --output json
```

Workbench 当前包括：

- FastAPI REST API
- 标准响应 envelope
- RBAC 写操作保护
- SSE job progress 和 health events
- audit log
- responsive dashboard shell

搜索、资产、健康详情等完整前端页面仍在后续版本中补齐。

## Agent 使用方式

Agent 应把 `ppt-lib` 当作稳定工具入口，并优先读取 JSON 输出。

```bash
# 用临时 home-dir 做 smoke test，避免误扫真实文件
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test

# 用户确认资料源后再建库
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ~/.ppt-library/sources/sources-manifest.json \
  --output json
uv run ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
uv run ppt-lib sources scan --dry-run --output json
uv run ppt-lib sources scan --apply --output json
uv run ppt-lib index --from-sources

# 搜索时检查 _errors
uv run ppt-lib search "会员运营案例" --top-k 8 --output json
```

Agent 集成要点：

- 默认使用 `--output json`。
- 汇报成功前检查 `_errors`、failed jobs 和 fallback warning。
- 建库前先执行 `sources scan --dry-run`，让用户确认范围后再 `sources scan --apply`。
- 不扫描下载目录、回收站、缓存目录、依赖包目录、聊天软件文件缓存，除非用户明确确认。
- `watch` 是长运行命令，只在用户明确要求持续监听时启动。
- 客户文件路径、真实 PPT、截图、HTML 预览和本地数据库都应留在用户本机。

完整 Agent 规则见 [skills/ppt-library/SKILL.md](skills/ppt-library/SKILL.md)。

## 安装 Agent Skill

仓库内置 `ppt-library` Skill，可复制到不同 Agent 的本地 skill 目录。

```bash
# Codex
mkdir -p ~/.codex/skills/ppt-library
rsync -a skills/ppt-library/ ~/.codex/skills/ppt-library/

# Claude Code
mkdir -p ~/.claude/skills/ppt-library
rsync -a skills/ppt-library/ ~/.claude/skills/ppt-library/
```

其他 Agent 可以把 `skills/ppt-library/SKILL.md` 作为任务上下文注入，或复制整个 `skills/ppt-library/` 目录。

安装后可用这个 smoke prompt 验证：

```text
Use the ppt-library skill. Check whether PPT Library is usable on this machine without indexing any private files. Report CLI availability, JSON schema health, index status, and model diagnostics.
```

不同 Agent 的适配说明见 [Agent Adapters](skills/ppt-library/references/agent-adapters.md)。

## 常用命令

| 目标 | 命令 |
|---|---|
| 查看版本 | `ppt-lib --version` |
| 初始化配置 | `ppt-lib setup --quick --non-interactive` |
| 查看健康状态 | `ppt-lib doctor --output json` |
| 查看能力声明 | `ppt-lib capabilities --output json` |
| 查看索引状态 | `ppt-lib status --output json` |
| 索引单个文件 | `ppt-lib index /path/to/deck.pptx` |
| 按资料源建库 | `ppt-lib index --from-sources` |
| 搜索页面 | `ppt-lib search "查询内容" --top-k 8` |
| 生成 HTML 审查页 | `ppt-lib search "查询内容" --html` |
| 展开历史版本 | `ppt-lib search "查询内容" --include-versions` |
| 查看版本治理状态 | `ppt-lib versions status` |
| 查看某个 PPT 家族 | `ppt-lib versions inspect <family-id>` |
| 重算版本归族 | `ppt-lib versions recompute --dry-run` |
| 补齐 Deck 理解 | `ppt-lib enrich-decks --pending --limit 20` |
| 查看关键页候选 | `ppt-lib insights key-pages --output json` |
| 导出审查包 | `ppt-lib insights review-pack --output /path/to/review-pack.jsonl` |
| 录入战绩描述 | `ppt-lib record-deal --name "..." --outcome won --description "..." --industry retail --scenario proposal --tags demo,key-page` |
| 按战绩增强搜索 | `ppt-lib search "查询内容" --ranking business --output json` |
| 自动组装预览 | `ppt-lib compose --brief "..." --dry-run` |
| 按确认计划组装 | `ppt-lib compose --confirm /path/to/narrative-plan.json` |
| 启动 Workbench | `ppt-lib workbench start --host 127.0.0.1 --port 8765` |
| 查看 Workbench 状态 | `ppt-lib workbench status --output json` |

## 数据和隐私

PPT Library 默认将数据保存在本机 `~/.ppt-library/`：

- SQLite 索引库
- PPT 页面截图
- 搜索 HTML 预览
- 组装清单和本地产物

公开仓库不包含真实 PPT、真实客户资料、样本截图或本地数据库。使用时请确认 `.pptx`、`.db`、`.env`、截图和导出产物不进入公开提交。

## 文档

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

## 开发和验证

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run python scripts/release_check.py --output json
uv build
```

v2.0.0 公开快照验证基线：

- 1083 automated tests
- ruff clean
- mypy clean
- `uv build` 产出 `ppt_library-2.0.0`
- `release_check` 覆盖 metadata、pytest、ruff、mypy、build、demo smoke

## 已知限制

- Job Engine 的 `jobs list/inspect/cancel` 主 CLI 入口还未接入。
- Workbench 的 search/asset/health 详情页面仍在后续版本补齐。
- Postgres backend、OIDC、生产部署工具后续迭代。
- Visual pHash 和 palette 仍是占位实现，需要后续接入渲染图像流水线。

## License

Apache License 2.0. See [LICENSE](LICENSE).
