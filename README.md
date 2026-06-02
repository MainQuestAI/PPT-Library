# PPT Library

页级语义搜索 + 战绩追踪 + 自动组装。PPT Library 帮助方案团队把历史 PPT 资产变成可搜索、可复用、可追踪的本地资料库。

## 核心能力

- **页级搜索**：按每一页抽取文本、截图和向量，支持关键词 + 语义检索。
- **版本治理**：同一项目的多个 PPT 版本会归入同一组，默认优先展示代表版本。
- **复用追踪**：记录页面在哪些机会或方案中被使用，并支持后续胜率排序。
- **自动组装**：根据 brief 选择相关页面，生成可审查的组装清单和 PPTX。
- **本地优先**：SQLite 存储在本机，基础搜索不依赖外部服务。

## Requirements

- Python 3.12+
- LibreOffice（可选，用于截图）
- LM Studio、Ollama 或 OpenAI-compatible API（可选，用于 embedding、视觉理解和 LLM 标注）

## Installation

当前公开版优先使用源码安装。PyPI 发布前，请以本仓库源码安装方式为准。

```bash
# Clone the repository first.
uv sync --extra test --extra lint

# Run the CLI from the source tree.
uv run ppt-lib --help

# Or install it as a local CLI tool.
uv tool install .
```

`ppt-library` 是 Python 包名，`ppt-lib` 是安装后的命令名。

## Quick Start

```bash
# 1. 初始化配置
uv run ppt-lib setup --quick

# 2. 创建资料源清单
uv run ppt-lib init --manifest ./ppt-sources.json --non-interactive

# 3. 预览并确认扫描范围
uv run ppt-lib sources scan --dry-run
uv run ppt-lib sources scan --apply

# 4. 建库
uv run ppt-lib index --from-sources

# 5. 搜索
uv run ppt-lib search "技术架构" --html
```

搜索结果默认输出到 `~/.ppt-library/html/search.html`。

## Configuration

PPT Library 会优先使用本地能力。配置 embedding 模型后，搜索质量会从文本匹配升级为语义检索。

- OpenAI-compatible API：设置 `PPT_LIB_OPENAI_API_KEY` 或配置 `embedding_api_url`。
- LM Studio：启动本地 OpenAI-compatible 服务后运行 `ppt-lib setup --quick`。
- Ollama：配置 OpenAI-compatible endpoint 和对应 embedding 模型。

更多说明见 [Quick Start Guide](docs/quick-start-guide.md) 和 [Model Compatibility](docs/guides/model-compatibility.md)。

## Documentation

- [Quick Start Guide](docs/quick-start-guide.md)
- [Library Build Guideline](docs/guides/library-build-guideline.md)
- [Model Compatibility](docs/guides/model-compatibility.md)
- [Specs](docs/specs/README.md)

## Development

```bash
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv build
```

当前测试基线：506 automated tests。

## License

MIT. See [LICENSE](LICENSE).
