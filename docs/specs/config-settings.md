# Spec 01: Config and Settings

Status: ACTIVE / REQUIRED BEFORE CODING
Modules: `ppt_lib/config.py`, `ppt_lib/settings.py`
Tasks: T1, T15

## 职责

配置层负责把所有运行时路径、模型 provider、并发参数、HTML 输出目录、日志目录和 schema 版本收口到一个可验证对象里。

它不直接读写业务数据，不调用模型，不访问 PPTX 内容。

## 输入

- CLI 参数，优先级最高。
- 环境变量，前缀固定为 `PPT_LIB_`。
- `~/.ppt-library/config.yml`。
- 默认值。

## 输出

- `Settings` 对象，供其他模块注入使用。
- 默认目录结构。
- 可安全打印的配置摘要，敏感值只显示 `present` 或 `missing`。

## 配置键

| 键 | 默认值 | 说明 |
|---|---|---|
| `home_dir` | `~/.ppt-library` | 数据根目录 |
| `db_path` | `{home_dir}/index.db` | SQLite 文件 |
| `screenshots_dir` | `{home_dir}/screenshots` | 截图目录 |
| `symlinks_dir` | `{home_dir}/symlinks` | discovery 统一视图 |
| `html_dir` | `{home_dir}/html` | HTML 审查页输出 |
| `logs_dir` | `{home_dir}/logs` | 日志目录 |
| `backups_dir` | `{home_dir}/backups` | SQLite backup 输出 |
| `embedding_provider` | `openai` | V1 至少支持 OpenAI |
| `embedding_model` | `text-embedding-3-small` | 默认 embedding 模型 |
| `embedding_dimensions` | `1536` | 当前库使用的向量维度，LM Studio nomic 样本链路使用 `768` |
| `embedding_timeout_seconds` | `30` | embedding provider HTTP 超时 |
| `vision_provider` | `auto` | 本地优先，云端 fallback |
| `paddleocr_mcp_pipeline` | `PaddleOCR-VL-1.6` | PaddleOCR MCP 使用的产线 |
| `paddleocr_mcp_source` | `aistudio` | PaddleOCR MCP 来源，支持 `aistudio` 或 `self_hosted` |
| `paddleocr_mcp_base_url` | `null` | 可选 AI Studio 或自托管 endpoint；token 不写入普通配置 |
| `lmstudio_base_url` | `http://127.0.0.1:1234/v1` | LM Studio OpenAI-compatible API |
| `lmstudio_embedding_model` | `text-embedding-nomic-embed-text-v1.5` | 本地 embedding 模型 |
| `lmstudio_vision_model` | `""` | 本地 vision/chat 模型；LM Studio setup 会尽量自动探测，失败时需用户显式配置 |
| `vision_max_slides_per_file` | `null` | 可选 vision 调用上限；用于复杂样本测试限流 |
| `max_workers` | `4` | 截图/索引默认并发 |
| `index --from-sources --file-workers` | `1` | PPTX 文件级并行；适合 PaddleOCR MCP 批量识别时手动提高 |
| `schema_version` | `1.0` | JSON Schema 版本 |
| `search_top_k` | `5` | 默认搜索结果数 |
| `search_threshold` | `0.5` | 默认相似度阈值 |
| `watch_debounce_seconds` | `5` | 文件监听 debounce |

## 公共接口

```python
class Settings(BaseModel):
    home_dir: Path
    db_path: Path
    screenshots_dir: Path
    symlinks_dir: Path
    html_dir: Path
    logs_dir: Path
    backups_dir: Path
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    vision_provider: str
    lmstudio_base_url: str
    lmstudio_embedding_model: str
    lmstudio_vision_model: str
    vision_max_slides_per_file: int | None
    max_workers: int
    schema_version: str
    search_top_k: int
    search_threshold: float
    watch_debounce_seconds: int

def load_settings(overrides: dict[str, object] | None = None) -> Settings: ...
def ensure_dirs(settings: Settings) -> None: ...
def write_default_config(path: Path) -> bool: ...
def settings_summary(settings: Settings) -> dict[str, object]: ...
```

## 错误处理

| 场景 | 行为 |
|---|---|
| `config.yml` 不存在 | 自动生成默认配置并继续 |
| YAML 语法错误 | 抛出 `ConfigError`，CLI 转成 `_errors` |
| 路径不可写 | 抛出 `ConfigError`，指明具体路径 |
| 数值越界 | Pydantic 校验失败，输出清晰错误 |
| 敏感环境变量存在 | summary 只显示存在状态 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_default_settings_paths` | 默认路径展开到用户 home 或临时 home |
| `test_write_default_config_once` | 首次生成，第二次不覆盖 |
| `test_env_override_wins_config` | 环境变量优先于 config.yml |
| `test_cli_override_wins_env` | CLI override 优先级最高 |
| `test_invalid_yaml_returns_config_error` | YAML 错误可读 |
| `test_ensure_dirs_creates_all_dirs` | 创建全部目录 |
| `test_settings_summary_redacts_sensitive_values` | 不泄漏 key |
| `test_invalid_threshold_rejected` | 阈值范围校验 |

## 验收标准

- 其他模块只依赖 `Settings`，不直接拼接 `~/.ppt-library`。
- 缺配置文件时项目可以自启动。
- 配置错误不会以 Python traceback 直接暴露给用户。
