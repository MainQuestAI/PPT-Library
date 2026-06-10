# 模型适配指南

PPT Library 使用 embedding 模型将每页 PPT 的内容转换为向量，实现语义搜索。本指南列出各方案的配置方式、成本估算和推荐场景。

## 快速选择

| 你的情况 | 推荐方案 | 配置方式 |
|---------|---------|---------|
| 有 OpenAI API key | OpenAI text-embedding-3-small | `ppt-lib setup --quick`（自动检测） |
| 有 LM Studio | 本地 embedding 模型 | `ppt-lib setup --quick`（自动检测） |
| 需要低成本 OCR/视觉识别 | 本地 embedding + PaddleOCR MCP | `ppt-lib setup --mode lmstudio` 后执行 `ppt-lib setup --mode paddleocr-mcp` |
| 有 Ollama | 本地 embedding 模型 | 手动配置 OpenAI-compatible endpoint |
| 有国产 API key | OpenAI-compatible API | `PPT_LIB_OPENAI_API_KEY` 环境变量 |
| 没有符合条件的方案 | 尝试本地模型安装 | 见"无 API key 怎么办" |

## Embedding 方案

### OpenAI text-embedding-3-small（推荐）

- **维度：** 1536
- **成本：** 约 $0.13/百万 token（约 10000 页）
- **配置：** `PPT_LIB_OPENAI_API_KEY` 环境变量
- **优点：** 质量稳定、延迟低、无需本地 GPU
- **缺点：** 需要 API key、有成本

```bash
export PPT_LIB_OPENAI_API_KEY="<your-openai-key>"
ppt-lib setup --quick
```

### LM Studio（本地免费）

- **推荐模型：** `text-embedding-nomic-embed-text-v1.5`（768 维）
- **成本：** 免费（需本地 GPU）
- **配置：** LM Studio 启动后自动检测
- **优点：** 数据不出本地、无 API 费用
- **缺点：** 需要 GPU、配置步骤较多（下载模型、启动服务）

```bash
# LM Studio 运行在 http://127.0.0.1:1234
ppt-lib setup --quick
# 自动检测到 LM Studio → 推荐本地模式
```

### Ollama（本地免费）

- **推荐模型：** `nomic-embed-text`（768 维）
- **成本：** 免费（需本地 GPU）
- **配置：** 通过 OpenAI-compatible endpoint 手动配置
- **优点：** 开源、社区活跃、部署简单
- **缺点：** 需要 GPU、性能取决于硬件

```bash
ollama pull nomic-embed-text
# Ollama 运行在 http://127.0.0.1:11434
ppt-lib setup --mode openai
ppt-lib config set embedding_api_url http://127.0.0.1:11434/v1
ppt-lib config set embedding_model nomic-embed-text
ppt-lib config set embedding_dimensions 768
```

### OpenAI-compatible API（国产方案）

如果你使用 Infini AI、DeepSeek、豆包等国产 embedding 服务，只要实现了 OpenAI 兼容的 `/v1/embeddings` 接口即可。

- **配置：** 设置环境变量
- **优点：** 可选供应商、国内访问低延迟
- **缺点：** 各供应商模型质量不一

```bash
export PPT_LIB_OPENAI_API_KEY="your-key"
# 并修改 config.yml 中的 embedding 相关配置指向你的 API 地址
ppt-lib setup --mode openai
```

## Vision / OCR 方案（可选）

PPT Library 默认不开启 vision（视觉识别）。如需识别图表、截图、复杂版式和图片里的文字，推荐优先使用 PaddleOCR MCP。

| 方案 | 模型 | 推荐场景 | 要求 |
|------|------|----------------|------|
| PaddleOCR MCP | PaddleOCR-VL-1.6 | 批量 OCR、版式、表格、图表识别 | `paddleocr-mcp`、AI Studio token 或自托管 endpoint |
| LM Studio | 本地视觉模型 | 小批量本地视觉理解 | 本地 GPU |
| Ollama | llava / moondream | 本地实验和低频使用 | 本地 GPU |
| OpenAI-compatible vision | gpt-4o-mini 等 | 高质量视觉摘要或小批量复杂页面 | API key |

```bash
# 推荐：本地 embedding + PaddleOCR MCP
uv sync --extra paddleocr
ppt-lib setup --mode lmstudio
ppt-lib setup --mode paddleocr-mcp
export PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN="<your-token>"

# 开启 vision（LM Studio）
ppt-lib config set vision_provider lmstudio
ppt-lib config set lmstudio_vision_model your-vision-model

# 开启 vision（OpenAI-compatible）
ppt-lib config set vision_provider cloud
ppt-lib config set cloud_vision_model gpt-4o-mini
```

## 成本估算

| 页面数 | 本地 embedding + PaddleOCR MCP | embedding + vision（OpenAI-compatible） |
|--------|-------------------------------|---------------------------------------|
| 100 | 通常仅消耗 OCR 服务页额 | 取决于图像输入计费 |
| 1000 | 通常仅消耗 OCR 服务页额 | 取决于图像输入计费 |
| 10000 | 需确认 AI Studio 当日可用页额 | 取决于图像输入计费 |

> AI Studio 免费页额和计费规则可能变化。大批量建库前，先以 AI Studio 控制台显示为准。

## 常见问题

### 没有 API key 怎么办？

可以用本地模型代替：
1. 安装 Ollama：`ollama pull nomic-embed-text`
2. 运行 `ppt-lib setup --mode openai`
3. 配置 `embedding_api_url=http://127.0.0.1:11434/v1`、`embedding_model=nomic-embed-text`、`embedding_dimensions=768`
4. 运行 `ppt-lib models test` 确认 embedding 能力可用

### PaddleOCR MCP 什么时候适合？

- PPT 页面有大量截图、图表、表格或图片文字。
- 不希望在本机跑大型多模态模型。
- 需要把 OCR 结果作为可搜索 Markdown 写入 slide 文本。
- AI Studio 账号有可用免费页额，或已经准备了自托管 PaddleOCR endpoint。

### 本地模型速度慢怎么办？

- 检查是否有 GPU 加速
- 考虑使用 CPU 版的 nomic-embed-text（小型模型）
- 视觉识别优先考虑 PaddleOCR MCP，把本地模型只用于 embedding

### 如何切换 embedding 方案？

```bash
# 1. 重新配置
ppt-lib setup --quick

# 2. 重新索引（保留现有截图，只重算向量）
ppt-lib index --from-sources --full
```
