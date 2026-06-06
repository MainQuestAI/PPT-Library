# 模型适配指南

PPT Library 使用 embedding 模型将每页 PPT 的内容转换为向量，实现语义搜索。本指南列出各方案的配置方式、成本估算和推荐场景。

## 快速选择

| 你的情况 | 推荐方案 | 配置方式 |
|---------|---------|---------|
| 有 OpenAI API key | OpenAI text-embedding-3-small | `ppt-lib setup --quick`（自动检测） |
| 有 LM Studio | 本地 embedding 模型 | `ppt-lib setup --quick`（自动检测） |
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

## Vision 方案（可选）

PPT Library 默认不开启 vision（视觉识别）。如需识别图表和截图，可选择以下方案：

| 方案 | 模型 | 成本（1000 页） | 要求 |
|------|------|----------------|------|
| OpenAI | gpt-4o-mini | $5-10（图像输入计费） | API key |
| LM Studio | 本地视觉模型 | 免费 | 本地 GPU |
| Ollama | llava / moondream | 免费 | 本地 GPU |

```bash
# 开启 vision（OpenAI）
ppt-lib config set vision_provider cloud
ppt-lib config set cloud_vision_model gpt-4o-mini

# 开启 vision（LM Studio）
ppt-lib config set vision_provider lmstudio
ppt-lib config set lmstudio_vision_model your-vision-model
```

## 成本估算

| 页面数 | 仅 embedding（OpenAI） | embedding + vision（OpenAI） |
|--------|----------------------|-----------------------------|
| 100 | $0.02 | $0.50-1.00 |
| 1000 | $0.13 | $5.00-10.00 |
| 10000 | $1.30 | $50.00-100.00 |

> 以上为估算值，实际成本取决于每页文本长度和图片大小。

## 常见问题

### 没有 API key 怎么办？

可以用本地模型代替：
1. 安装 Ollama：`ollama pull nomic-embed-text`
2. 运行 `ppt-lib setup --mode openai`
3. 配置 `embedding_api_url=http://127.0.0.1:11434/v1`、`embedding_model=nomic-embed-text`、`embedding_dimensions=768`
4. 运行 `ppt-lib models test` 确认 embedding 能力可用

### 本地模型速度慢怎么办？

- 检查是否有 GPU 加速
- 考虑使用 CPU 版的 nomic-embed-text（小型模型）
- 如果需要更好的性能，建议切换到云端 API

### 如何切换 embedding 方案？

```bash
# 1. 重新配置
ppt-lib setup --quick

# 2. 重新索引（保留现有截图，只重算向量）
ppt-lib index --from-sources --full
```
