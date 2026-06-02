# Spec 06: Diagnostics

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/diagnostics.py`
Task: T19

## 职责

Diagnostics 层负责回答“当前机器是否具备 PPT Library 所需运行能力”。它输出结构化诊断结果，供 `ppt-lib vision --test` 和 `index` 启动前预检使用。

## 检查项

| 项 | 必要性 | 检查内容 |
|---|---|---|
| LibreOffice | V1 必需 | `soffice` 是否可执行 |
| SQLite | V1 必需 | Python sqlite3 可用 |
| screenshots dir | V1 必需 | 可创建可写 |
| OpenAI embedding | 条件必需 | key 是否存在，model 是否配置 |
| Ollama | 可选 | 服务是否启动，是否有 vision model |
| LM Studio | 可选 | 服务是否启动，是否有 vision endpoint |
| Cloud vision | 可选 | key 是否存在 |

## 公共接口

```python
@dataclass
class DiagnosticCheck:
    name: str
    status: Literal["ok", "warning", "error", "skipped"]
    message: str
    details: dict[str, object]

@dataclass
class DiagnosticReport:
    checks: list[DiagnosticCheck]
    recommended_chain: list[str]
    can_index: bool
    can_use_vision: bool

def run_diagnostics(settings: Settings) -> DiagnosticReport: ...
```

## JSON 输出

`ppt-lib vision --test` 输出：

```json
{
  "_meta": {"schema_version": "1.0", "command": "vision --test"},
  "checks": [],
  "recommended_chain": ["ollama", "cloud", "text_extraction"],
  "can_index": true,
  "can_use_vision": false,
  "_errors": []
}
```

## 错误处理

- 检查失败不抛出裸异常，转为 `DiagnosticCheck`。
- 网络检查 timeout 默认 2 秒。
- key 只显示存在状态。
- 本地服务 API 格式变化时返回 warning，不能直接判定全局失败。

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_soffice_detected` | LibreOffice 存在 |
| `test_soffice_missing_blocks_index` | 缺少渲染器 |
| `test_ollama_detected_with_vision_model` | Ollama 可用 |
| `test_ollama_no_vision_model_warning` | 有服务无模型 |
| `test_lmstudio_timeout_warning` | timeout 不崩溃 |
| `test_api_key_redacted` | 不泄漏 key |
| `test_recommended_chain_text_fallback_only` | 降级链 |
| `test_report_json_shape` | 输出契约 |

## 验收标准

- 用户能通过一条命令知道当前可用链路。
- index 启动前可以复用诊断结果输出 warning。
- 诊断不会触发真实长耗时模型调用。
