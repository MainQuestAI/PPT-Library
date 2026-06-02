# Spec 03: Embedding

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/embedding.py`
Task: T3

## 职责

Embedding 层负责把文本转换为向量，并提供 provider 抽象、重试、限流处理和维度校验。

它不读取 PPTX，不写数据库，不直接处理搜索排序。

## Provider 抽象

```python
class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def encode(self, text: str) -> np.ndarray: ...
    def encode_batch(self, texts: Sequence[str]) -> list[np.ndarray]: ...

def build_embedding_provider(settings: Settings) -> EmbeddingProvider: ...
```

V1 provider：

- `OpenAIEmbeddingProvider`
- `LMStudioEmbeddingProvider`
- `FakeEmbeddingProvider`，仅用于测试

## 输入输出

| 输入 | 输出 |
|---|---|
| 非空文本 | `np.ndarray(dtype=float32, shape=(settings.embedding_dimensions,))` |
| 空文本 | 允许编码为固定占位文本，或返回结构化 warning 后跳过 embedding；实现需在测试中固定 |
| 超长文本 | 由 provider 截断或分段，必须记录 warning |

LM Studio 使用 OpenAI-compatible `/embeddings` 端点，本地样本链路默认模型为 `text-embedding-nomic-embed-text-v1.5`，当前实测维度为 `768`。

## 重试策略

- timeout：最多重试 2 次。
- 429：指数退避，最多重试 3 次。
- 5xx：最多重试 2 次。
- 4xx 非 429：不重试。

HTTP 超时由 `settings.embedding_timeout_seconds` 控制。

## 错误处理

| 场景 | 错误 code |
|---|---|
| API key 缺失 | `EMBEDDING_AUTH_MISSING` |
| timeout 后仍失败 | `EMBEDDING_TIMEOUT` |
| rate limit 后仍失败 | `EMBEDDING_RATE_LIMIT` |
| provider 返回维度不符 | `EMBEDDING_DIMENSION_MISMATCH` |
| provider 未知 | `EMBEDDING_PROVIDER_UNSUPPORTED` |
| provider 返回结构异常 | `EMBEDDING_INVALID_RESPONSE` |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_build_openai_provider_from_settings` | provider 选择 |
| `test_build_lmstudio_provider_from_settings` | 本地 provider 配置 |
| `test_encode_returns_float32_vector` | dtype 和 shape |
| `test_encode_timeout_retry_then_success` | timeout 重试 |
| `test_encode_rate_limit_backoff` | 429 退避 |
| `test_encode_4xx_no_retry` | 非可重试错误 |
| `test_dimension_mismatch_raises` | 维度校验 |
| `test_lmstudio_provider_uses_local_embeddings_endpoint` | 本地 endpoint 和 payload |
| `test_empty_text_policy_is_stable` | 空文本策略固定 |
| `test_fake_provider_deterministic` | 测试 provider 可复现 |

## 验收标准

- 搜索和索引都通过同一 provider 接口调用 embedding。
- 所有 provider 错误能被 CLI 映射成 `_errors`。
- 测试不依赖真实外部 API。
