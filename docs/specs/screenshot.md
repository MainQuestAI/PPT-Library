# Spec 04: Screenshot

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/screenshot.py`
Tasks: T4, T11

## 职责

截图层负责把 PPTX slide 渲染为 PNG，计算 SHA256，做本地文件去重，并隔离 LibreOffice 进程。

它不负责 embedding，不写业务表，只返回截图结果对象。

## 公共接口

```python
@dataclass
class ScreenshotResult:
    slide_index: int
    png_path: Path
    sha256: str
    width: int
    height: int
    warnings: list[str]

def render_pptx_slides(
    pptx_path: Path,
    output_dir: Path,
    *,
    max_workers: int = 4,
    timeout_seconds: int = 30,
) -> list[ScreenshotResult]: ...

def compute_sha256(path: Path) -> str: ...
def store_deduped_png(temp_png: Path, screenshots_dir: Path) -> Path: ...
```

## LibreOffice 策略

- 每个 worker 使用独立 profile：`-env:UserInstallation=file://...`。
- 单次渲染 timeout 默认 30 秒。
- stderr 写入日志，由调用方决定是否暴露给用户。
- 渲染失败的 slide 返回 warning，不阻断整份 PPTX。

## 输出路径规则

PNG 文件名使用完整 SHA256：

```text
~/.ppt-library/screenshots/{sha256}.png
```

相同内容只存一份。

## 错误处理

| 场景 | 行为 |
|---|---|
| LibreOffice 不存在 | 返回 `SCREENSHOT_RENDERER_MISSING` |
| 渲染 timeout | 终止进程，记录 warning |
| 某页渲染失败 | 跳过该页，继续其他页 |
| PNG 文件损坏 | 返回 `SCREENSHOT_INVALID_OUTPUT` |
| 输出目录不可写 | 返回 `SCREENSHOT_OUTPUT_NOT_WRITABLE` |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_compute_sha256_stable` | hash 稳定 |
| `test_store_deduped_png_reuses_existing` | 去重 |
| `test_render_invokes_isolated_profile` | 独立 profile 参数 |
| `test_render_timeout_kills_process` | timeout 行为 |
| `test_render_stderr_captured` | stderr 捕获 |
| `test_missing_libreoffice_error` | 缺依赖错误 |
| `test_corrupt_png_rejected` | 输出校验 |
| `test_partial_slide_failure_continues` | 局部失败不中断 |

## 验收标准

- 相同截图只存一份。
- LibreOffice 单页失败不会让整批索引失败。
- timeout 和 stderr 可被 indexer 记录到 job/warnings。
