# Quick Start Guide

首次建库完整指南，覆盖从安装到搜索的全流程。包含两种模式：
- **Quick Pass** — 自动检测环境，推荐最佳配置，适合新用户快速上手
- **Full Pass** — 手动指定 provider，精细控制每个环节

---

## 先决条件

- Python 3.12+（已在 3.14 上测试）
- 本机安装 [LibreOffice](https://www.libreoffice.org/)（用于 PPTX 截图渲染；如果不可用，部分流程走文本 fallback）
- 至少一种 embedding 模型来源（详见下文"Quick Pass"中的自动检测）

---

## Quick Pass（5 分钟上手）

Quick Pass 会自动检测你的本机环境，推荐最优配置，无需手动设置 provider。

### 1. 安装 CLI

```bash
uv sync --extra test --extra lint
uv run ppt-lib --version
```

确认安装成功：

```bash
uv run ppt-lib --help
```

> 当前公开版优先使用源码安装。安装为本地 CLI 工具时，可以使用 `uv tool install .`。

### 2. 自动检测配置

```bash
ppt-lib setup --quick
```

`setup --quick` 会自动检测：
1. 环境变量中是否存在 `PPT_LIB_OPENAI_API_KEY` → 检测到则推荐 OpenAI
2. LM Studio 是否在 `http://127.0.0.1:1234/v1` 运行 → 检测到则推荐 LM Studio
3. Ollama 是否安装并运行 → 检测到后提示使用 OpenAI-compatible endpoint 手动配置
4. 以上都不可用 → 提示安装 LM Studio、配置 API key，或先用单文件文本抽取验证

展示推荐配置后，确认即可写入 `~/.ppt-library/config.yml`。

> 非交互式环境（如 CI、Agent 自动调用）使用 `ppt-lib setup --quick --non-interactive`。

### 3. 创建源清单

用 `sources manifest` 从用户确认的 PPT 文件夹生成资料源清单：

```bash
ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --manifest-output ./sources-manifest.json \
  --output json
```

然后加载到 PPT Library：

```bash
ppt-lib init --manifest ./sources-manifest.json --non-interactive
```

> 提示：`library` 指向包含 `.pptx` 文件的目录。如有多个目录，可以添加多个路径到 `library` 数组。

### 4. 预览扫描范围

```bash
ppt-lib sources scan --dry-run
```

预览命令不会实际入库，只列出将被扫描的文件。确认文件清单无误后进入下一步。

### 5. 执行扫描

```bash
ppt-lib sources scan --apply
```

扫描结果写入本地索引库状态。如果之前执行过 `--dry-run`，这一步会按确认的清单执行。

### 6. 建库

```bash
ppt-lib index --from-sources
```

这会逐页提取 PPTX 内容（文字与截图），建立页级索引。建库时长取决于 PPTX 数量和页数。

查看建库结果：

```bash
ppt-lib status
```

关注 `total_slides` 是否大于 0、`failed_jobs` 是否为空。

### 7. 搜索

```bash
ppt-lib search "技术架构" --html
```

打开返回的 HTML 文件路径（默认 `~/.ppt-library/html/search.html`），即可看到搜索结果页面，包含匹配的页面截图和文字摘要。

JSON 输出（适合脚本和 Agent）：

```bash
ppt-lib search "技术架构" --top-k 5 --output json
```

### 8. 查看关键页候选

```bash
ppt-lib enrich-decks --pending --limit 20 --output json
ppt-lib insights key-pages --output json
```

需要只看需要视觉复核的页面：

```bash
ppt-lib insights key-pages --needs-visual --output text
```

需要交给 Agent 或人工批量审查标签：

```bash
ppt-lib insights review-pack --output /absolute/path/to/review-pack.jsonl
```

审查包是只读导出；标签修正继续通过 `import-metadata` 回写。

公开演示可直接使用合成 PPT：

```bash
uv run --extra demo python scripts/create_demo_decks.py --output /tmp/ppt-lib-demo-decks
```

这组 PPT 由 `python-pptx` 生成，适合用 LibreOffice 渲染缩略图。没有 LibreOffice 时仍可验证文本索引和关键页识别。

---

## Full Pass（手动配置模式）

当你需要精确控制 provider、模型或配置参数时，使用 Full Pass。

### 1. 安装 CLI

```bash
uv sync --extra test --extra lint
```

### 2. 手动指定 provider

```bash
# 使用 LM Studio
ppt-lib setup --mode lmstudio

# 推荐：本地 embedding + PaddleOCR MCP OCR/视觉识别
ppt-lib setup --mode lmstudio
ppt-lib setup --mode paddleocr-mcp

# 使用 OpenAI
ppt-lib setup --mode openai

# 使用 Ollama 的 OpenAI-compatible endpoint
ppt-lib setup --mode openai
ppt-lib config set embedding_api_url http://127.0.0.1:11434/v1
ppt-lib config set embedding_model nomic-embed-text
ppt-lib config set embedding_dimensions 768
```

各 provider 需要事先准备：

| Provider | 前提条件 |
|---|---|
| **LM Studio** | 启动 LM Studio，加载 embedding 模型（如 `text-embedding-nomic-embed-text-v1.5`），确保服务在 `http://127.0.0.1:1234/v1` 可用 |
| **PaddleOCR MCP** | 安装 `paddleocr` extra，并通过环境变量提供 AI Studio token；用于 OCR、版式和图表识别 |
| **OpenAI** | 设置环境变量 `PPT_LIB_OPENAI_API_KEY` |
| **Ollama** | 安装并启动 Ollama，拉取 embedding 模型（如 `nomic-embed-text`），再按 OpenAI-compatible endpoint 手动配置 |

### 3. 后续步骤

与 Quick Pass 第 3-7 步相同：

```bash
ppt-lib init --manifest ./sources-manifest.json --non-interactive
ppt-lib sources scan --dry-run
ppt-lib sources scan --apply
ppt-lib index --from-sources
ppt-lib search "查询内容" --html
```

批量使用 PaddleOCR MCP 时，可以先从保守并行开始：

```bash
ppt-lib index --from-sources --file-workers 2
```

---

## 从 Quick Pass 升级到 Full Pass

如果先用 Quick Pass 建了库，后续想切换 provider 或模型：

### 1. 重新配置

```bash
ppt-lib setup --mode openai
```

或手动修改 `~/.ppt-library/config.yml`，更新 `embedding_api_url`、`embedding_model`、`embedding_dimensions` 和相关参数。

### 2. 重建索引

```bash
ppt-lib index --from-sources --full
```

`--full` 会清空旧索引并重新全量建库，确保新 provider 的 embedding 覆盖所有页面。

> 只切换 provider 不需要重新扫描，`--from-sources` 会读取已有的扫描结果。

---

## 常见问题

### Q: 没有 API key 怎么办？

使用本地方案：**LM Studio**。

1. 下载安装 [LM Studio](https://lmstudio.ai/)
2. 加载一个 embedding 模型（如 `text-embedding-nomic-embed-text-v1.5`）
3. 启动本地服务（默认端口 1234）
4. 运行 `ppt-lib setup` — Quick Pass 会自动检测到 LM Studio

全程不需要 API key，所有计算在本地完成。

### Q: 搜索质量差怎么办？

确认 embedding 模型已正确配置：

```bash
ppt-lib config get embedding_provider
```

如果显示 `none` 或 `unknown`，表示未配置 embedding 模型，搜索退化为关键词匹配，质量会明显下降。重新运行 `ppt-lib setup` 配置 provider。

其他常见原因：
- `threshold` 过高导致结果太少：尝试 `--threshold 0.3`
- 索引库中的页面数量太少：检查 `ppt-lib status` 的 `total_slides`
- embedding 维度不匹配：重跑 `ppt-lib index --from-sources --full`

### Q: 可以搜索哪些文件格式？

当前版本**只支持 PPTX**。不支持 .ppt（旧格式）、.pptm、PDF 或其他文档格式。

### Q: 搜索结果为空？

按以下顺序排查：

1. `ppt-lib status` — 确认 `total_slides` > 0
2. `ppt-lib config get embedding_provider` — 确认 embedding 已配置
3. 降低 threshold：`ppt-lib search "关键词" --threshold 0.2`
4. 检查是否有错误：`ppt-lib search "关键词" --output json`，查看 `_errors` 字段

### Q: `ppt-lib init` 说找不到 PPT 文件夹？

编辑 `~/ppt-library/sources-manifest.json`，将 `source_dirs` 修改为实际 PPT 所在路径：

```json
{
  "source_dirs": ["/your/actual/ppt/path"],
  "file_patterns": ["*.pptx"]
}
```

然后重新执行 `ppt-lib sources scan --apply` 和 `ppt-lib index --from-sources`。

### Q: LibreOffice 截图失败？

截图失败不影响搜索功能，文字内容仍会被索引。确认本机已安装 LibreOffice：

```bash
soffice --version
```

如果未安装，从 [libreoffice.org](https://www.libreoffice.org/) 下载安装后重新建库即可。

### Q: 如何重新开始？

删除本地状态目录，重新走 Quick Pass 流程：

```bash
rm -rf ~/.ppt-library
ppt-lib setup --quick
ppt-lib init --manifest ./sources-manifest.json --non-interactive
# ...
```
