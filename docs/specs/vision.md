# Spec 05: Vision

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/vision.py`
Task: T10

## 职责

Vision 层负责从 slide 截图中提取语义描述、结构化元数据和置信度。它提供本地模型优先、云端 fallback、文本提取兜底的统一接口。

## Provider 链路

自动模式优先级：

1. 本地 Ollama vision model。
2. 本地 LM Studio vision model。
3. mmx vision provider。
4. 云端 vision provider。
5. PPTX 文本提取 fallback。

推荐批量 OCR 方案：

- `vision_provider=paddleocr_mcp` 时，使用 PaddleOCR MCP / PaddleOCR-VL-1.6 读取页面截图，输出 Markdown 作为 slide 文本。
- 显式选择 `paddleocr_mcp` 时，如果 OCR 服务失败，索引任务会停止并返回错误，避免悄悄降级成普通文本抽取。
- `--file-workers` 可并行处理多份 PPTX 文件；`max_workers` 继续控制单份 PPTX 内的截图渲染并发。

当前实现说明：

- Ollama 走 `/api/generate`，默认 `http://127.0.0.1:11434`。
- LM Studio 走 OpenAI-compatible `/v1/chat/completions`，默认 `http://127.0.0.1:1234/v1`。
- 云端 provider 走 OpenAI-compatible chat completions，默认 `https://api.openai.com/v1`。
- PaddleOCR MCP 通过 `paddleocr-mcp` 包或自托管 `/layout-parsing` endpoint 调用，token 只能走环境变量或外部密钥管理。
- Provider 输出统一解析为 `VisionResult`，非 JSON 内容会以 warning 保留摘要。

## 公共接口

```python
@dataclass
class VisionResult:
    source: Literal["vision_model", "text_extraction", "hybrid"]
    title: str | None
    text_content: str
    metadata: dict[str, object]
    confidence: float
    warnings: list[str]

class VisionProvider(Protocol):
    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult: ...

def build_vision_chain(settings: Settings) -> list[VisionProvider]: ...
def describe_slide_with_fallback(image_path: Path, fallback_text: str, settings: Settings) -> VisionResult: ...
```

## Metadata 契约

`metadata` 建议包含：

- `layout_type`
- `chart_types`
- `business_domain`
- `key_entities`
- `visual_elements`
- `use_cases`
- `language`

字段缺失允许，但类型必须稳定。

## 错误处理

| 场景 | 行为 |
|---|---|
| 本地模型不可用 | warning，继续下一 provider |
| provider 返回非 JSON | 尝试提取文本摘要，记录 warning |
| 图像过大 | 压缩或拒绝，记录 `VISION_IMAGE_TOO_LARGE` |
| 所有 vision provider 失败 | 使用文本 fallback，`source=text_extraction` |
| 显式 PaddleOCR MCP 失败 | 直接返回阻塞错误，不写入降级结果 |
| fallback 文本也为空 | 返回空内容和 warning，仍允许 slide 入库 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_build_chain_local_first` | provider 顺序 |
| `test_ollama_success_returns_vision_model` | 本地成功 |
| `test_lmstudio_fallback_after_ollama_failure` | 链式 fallback |
| `test_cloud_fallback_used_when_local_missing` | 云端 fallback |
| `test_text_extraction_last_resort` | 最终兜底 |
| `test_invalid_json_response_records_warning` | 非 JSON 响应 |
| `test_empty_image_and_empty_text_returns_warning` | 空内容 |
| `test_metadata_types_stable` | metadata 类型 |
| `test_confidence_range_enforced` | confidence 0 到 1 |
| `test_paddleocr_mcp_provider_formats_markdown_result` | PaddleOCR Markdown 结果 |
| `test_paddleocr_mcp_explicit_provider_error_stops_instead_of_fallback` | 显式 PaddleOCR 失败不降级 |

## 验收标准

- indexer 不关心具体 provider，只接收 `VisionResult`。
- 降级路径对用户可见。
- 任意 provider 异常不会阻断整批索引。
