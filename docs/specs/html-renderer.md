# Spec 11: HTML Renderer

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/html_renderer.py`
Task: T18

## 职责

HTML Renderer 负责把 search results 渲染为自包含 HTML 审查页，方便用户查看截图、文本摘要、来源文件和页码。

它不负责搜索，不读取数据库，只消费搜索结果对象。

## 状态

| 状态 | 触发条件 | 行为 |
|---|---|---|
| empty | 0 个结果 | 显示空状态和调整建议 |
| single | 1 个结果 | 静态详情页 |
| normal | 2 到 10 个结果 | 轮播和键盘导航 |
| truncated | 超过 10 个结果 | 只展示前 10 个，提示优化 query |

## 公共接口

```python
@dataclass
class HtmlRenderOptions:
    title: str
    max_results: int = 10
    embed_images: bool = True

def render_search_review(results: list[SearchResult], options: HtmlRenderOptions, output_dir: Path) -> Path: ...
```

## HTML 要求

- 单文件自包含。
- 默认 base64 内嵌截图。
- 键盘支持左右切换。
- 缺失截图显示 placeholder。
- 每个结果显示：标题、score、source、页码、文件路径、摘要、metadata。
- 文件超过 5MB 时输出 warning。

## 错误处理

| 场景 | 行为 |
|---|---|
| output_dir 不可写 | `HTML_OUTPUT_NOT_WRITABLE` |
| 截图路径不存在 | placeholder + warning |
| 图片 base64 失败 | placeholder + warning |
| 结果过多 | truncated 状态 |
| metadata 不可序列化 | 转字符串，记录 warning |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_empty_state_html` | 空状态 |
| `test_single_result_html` | 单结果 |
| `test_normal_carousel_contains_keyboard_js` | 轮播和键盘 |
| `test_truncated_state_limits_results` | 截断 |
| `test_missing_screenshot_placeholder` | 缺图 |
| `test_base64_embed_image` | 图片内嵌 |
| `test_large_html_warning` | 文件大小 warning |
| `test_metadata_render_safe` | metadata 安全渲染 |
| `test_output_filename_stable_and_unique` | 输出文件名 |

## 验收标准

- search `--html` 能生成可直接打开的 HTML。
- 所有状态都有明确页面。
- HTML 不依赖本地服务器。
