# PPT Library

PPT Library 是一个本地优先的 PPTX 资产库 CLI。它把历史 PPT 按页入库，让人类和 AI Agent 都可以搜索、审查、复用、组装和追踪幻灯片资产。

它适合这些场景：

- 方案团队希望从多年历史 PPT 中快速找可复用页面。
- 售前或咨询团队希望减少重复造页。
- AI Agent 需要一个稳定的 PPT 检索和组装工具，避免直接翻文件夹猜内容。
- 团队希望治理同一项目几十个版本的 PPT，默认只展示代表版本，必要时再展开历史版本。

## 核心能力

- **页级搜索**：按每一页抽取文本、截图和向量，支持关键词 + 语义检索。
- **版本治理**：同一项目的多个 PPT 版本会归入同一组，搜索默认优先展示代表版本。
- **Deck 理解**：支持整份 PPT 的项目、客户、行业、场景、章节结构和摘要补充。
- **重点页识别**：支持筛选高复用价值页面，便于后续做视觉理解或人工审查。
- **复用追踪**：记录页面在哪些机会或方案中被使用，并支持后续按战绩排序。
- **自动组装**：根据 brief 选择相关页面，生成可审查的组装清单和 PPTX 草稿。
- **Agent 友好**：CLI 支持 JSON 输出，便于 Codex、Claude Code、Hermes、OpenCode 等 Agent 调用。
- **本地优先**：SQLite、截图、HTML 预览和索引资产默认存储在本机。
- **推荐识别链路**：本地 embedding + PaddleOCR MCP，可在较低本地资源占用下补齐 PPT 页面的 OCR、版式和图表识别。

## 组成部分

| 路径 | 作用 |
|---|---|
| `ppt_lib/` | CLI 和核心运行逻辑 |
| `skills/ppt-library/` | 面向 Agent 的 Skill，说明 Agent 如何安全调用 `ppt-lib` |
| `docs/quick-start-guide.md` | 从安装到建库、搜索的完整上手指南 |
| `docs/guides/agent-install-and-build-guideline.md` | Agent 安装 CLI、收集高价值资产路径、生成 manifest 和启动建库的设计剧本 |
| `docs/guides/library-build-guideline.md` | 资料库构建流程和安全扫描边界 |
| `docs/guides/asset-intelligence-demo.md` | 用合成 PPT 演示关键页、战绩、复用追踪和业务排序闭环 |
| `docs/guides/model-compatibility.md` | LM Studio、PaddleOCR MCP、Ollama、OpenAI-compatible API 配置说明 |
| `docs/guides/recommended-implementation.md` | 推荐的本地 embedding + PaddleOCR MCP 实施方案 |
| `docs/specs/` | CLI、数据库、搜索、截图、视觉理解等模块规格 |

## Requirements

- Python 3.12+
- LibreOffice，可选，用于 PPTX 页面截图
- LM Studio、Ollama 或 OpenAI-compatible API，可选，用于 embedding
- PaddleOCR MCP，可选，推荐用于 PPT 页面 OCR、版式和图表识别

没有模型服务时，PPT Library 仍可做基础文本抽取和关键词搜索；配置 embedding 后，搜索质量会明显提升。

## Installation

当前公开版优先使用源码安装。PyPI 发布前，请以本仓库源码安装方式为准。

```bash
git clone https://github.com/MainQuestAI/PPT-Library.git
cd PPT-Library

# 安装开发和测试依赖
uv sync --extra test --extra lint

# 推荐：同时安装 PaddleOCR MCP 接入依赖
uv sync --extra test --extra lint --extra paddleocr

# 从源码目录运行 CLI
uv run ppt-lib --help

# 或安装为本地 CLI 工具
uv tool install .
```

也可以用 editable 模式安装：

```bash
pip install -e .
```

`ppt-library` 是 Python 包名，`ppt-lib` 是安装后的命令名。

## Quick Start for Humans

这条路径适合第一次手动建库和搜索。

```bash
# 1. 初始化配置
uv run ppt-lib setup --quick

# 推荐识别方案：本地 embedding + PaddleOCR MCP
uv run ppt-lib setup --mode lmstudio
uv run ppt-lib setup --mode paddleocr-mcp

# 2. 创建资料源清单
uv run ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output ./ppt-sources.json

# 3. 将资料源清单写入生效 profile
uv run ppt-lib init --manifest ./ppt-sources.json --non-interactive

# 4. 预览扫描范围
uv run ppt-lib sources scan --dry-run

# 5. 确认扫描范围并写入本地状态
uv run ppt-lib sources scan --apply

# 6. 建库
uv run ppt-lib index --from-sources --file-workers 2

# 7. 搜索并生成 HTML 结果页
uv run ppt-lib search "技术架构" --html

# 8. 补齐 Deck 理解并查看关键页
uv run ppt-lib enrich-decks --pending --limit 20
uv run ppt-lib insights key-pages --output json
```

搜索结果默认输出到 `~/.ppt-library/html/search-review-*.html`。

一个最小资料源清单示例：

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

建议首次建库先用少量 PPTX 验证流程，再扩大到完整资料库。

## Quick Start for Agents

Agent 调用时建议把 `ppt-lib` 当作稳定工具入口，并优先读取 JSON 输出。

如果用户要求 Agent 安装 PPT Library CLI，并希望安装后直接进入建库引导，先读 [Agent Install and Guided Library Build Design](docs/guides/agent-install-and-build-guideline.md)。该文档定义了安装、用户路径问答、`sources-manifest.json` 生成、dry-run 汇报和建库监控流程。

```bash
# 1. 用临时 home-dir 做 smoke test，避免误扫真实文件
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test

# 2. 用户确认资料源后再建库
uv run ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output ~/.ppt-library/sources/sources-manifest.json --output json
uv run ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
uv run ppt-lib sources scan --dry-run --output json
uv run ppt-lib sources scan --apply --output json
uv run ppt-lib index --from-sources
uv run ppt-lib status --output json

# 3. 搜索时使用 JSON，并检查 _errors
uv run ppt-lib search "会员运营案例" --top-k 8 --output json

# 4. 需要资产经营视角时先查关键页，再导出审查包
uv run ppt-lib enrich-decks --pending --limit 20 --output json
uv run ppt-lib insights key-pages --output json
uv run ppt-lib insights review-pack --output /tmp/ppt-lib-review-pack.jsonl

# 5. 需要组装时先 dry-run，再执行确认后的 plan
uv run ppt-lib compose --brief "生成一份客户成功案例方案" --dry-run
uv run ppt-lib compose --confirm /path/to/narrative-plan.json
```

Agent 集成要点：

- 默认用 `--output json`，以 stdout JSON 作为结果依据。
- 汇报成功前必须检查 `_errors`、failed jobs 和 fallback warning。
- 首次建库优先用 `sources manifest` 收敛用户确认的高价值路径，再 `init --manifest` 写入 profile。
- 建库前先执行 `sources scan --dry-run`，让用户确认范围后再 `sources scan --apply`。
- 不要扫描下载目录、回收站、缓存目录、依赖包目录、聊天软件文件缓存或其他高风险目录，除非用户明确确认。
- 长任务期间用 `status --output json` 查看 `sources_health.index_progress`。
- `watch` 是长运行命令，只在用户明确要求持续监听时启动。
- 客户文件路径、真实 PPT、截图、HTML 预览和本地数据库都应留在用户本机。

更多 Agent 规则见 [skills/ppt-library/SKILL.md](skills/ppt-library/SKILL.md)。

## Installing the Agent Skill

仓库内置 `ppt-library` Skill，可复制到不同 Agent 的本地 skill 目录。

```bash
# Codex
mkdir -p ~/.codex/skills/ppt-library
rsync -a skills/ppt-library/ ~/.codex/skills/ppt-library/

# Claude Code
mkdir -p ~/.claude/skills/ppt-library
rsync -a skills/ppt-library/ ~/.claude/skills/ppt-library/
```

其他 Agent 可把 `skills/ppt-library/SKILL.md` 作为任务上下文注入，或复制整个 `skills/ppt-library/` 目录到对应的本地 skills 目录。

安装后可用这个 smoke prompt 验证：

```text
Use the ppt-library skill. Check whether PPT Library is usable on this machine without indexing any private files. Report CLI availability, JSON schema health, index status, and model diagnostics.
```

不同 Agent 的适配说明见 [Agent Adapters](skills/ppt-library/references/agent-adapters.md)。

## Common Workflows

| 目标 | 命令 |
|---|---|
| 检查 CLI | `ppt-lib --version` |
| 初始化配置 | `ppt-lib setup --quick --non-interactive` |
| 查看健康状态 | `ppt-lib doctor --output json` |
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

## Version-Aware Search

PPT 项目经常会有几十个版本。PPT Library 会把相似文件归入同一个 deck family，并标记代表版本。

默认搜索只展示代表版本，减少同一项目不同版本反复刷屏：

```bash
ppt-lib search "长周期项目复盘"
```

需要审计历史版本时再展开：

```bash
ppt-lib search "长周期项目复盘" --include-versions
ppt-lib versions inspect <family-id>
```

代表版本只是默认搜索视图，历史版本仍保留在本地库中。

## Configuration

PPT Library 会优先使用本地能力。配置 embedding 模型后，搜索质量会从文本匹配升级为语义检索。

- OpenAI-compatible API：设置 `PPT_LIB_OPENAI_API_KEY` 或配置 `embedding_api_url`。
- LM Studio：启动本地 OpenAI-compatible 服务后运行 `ppt-lib setup --quick`。
- Ollama：配置 OpenAI-compatible endpoint 和对应 embedding 模型。

更多说明见 [Quick Start Guide](docs/quick-start-guide.md) 和 [Model Compatibility](docs/guides/model-compatibility.md)。

## Data and Privacy

PPT Library 默认将数据保存在本机 `~/.ppt-library/`：

- SQLite 索引库
- PPT 页面截图
- 搜索 HTML 预览
- 组装清单和本地产物

公开仓库不包含真实 PPT、真实客户资料、样本截图或本地数据库。使用时请确认 `.pptx`、`.db`、`.env`、截图和导出产物不要提交到公开仓库。

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

当前测试基线：1083 automated tests。

## License

Apache License 2.0. See [LICENSE](LICENSE).
