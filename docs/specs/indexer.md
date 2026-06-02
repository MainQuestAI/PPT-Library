# Spec 09: Indexer

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/indexer.py`
Tasks: T5, T12

## 职责

Indexer 是索引编排层，负责把 PPTX 文件转换成数据库中的 presentation、slide、screenshot 和 embedding 记录。

它调用 screenshot、vision、embedding、db，不直接实现这些模块的底层能力。

## 索引流程

1. 校验输入路径。
2. 创建或更新 index job。
3. 判断增量状态：`path + file_size + file_mtime + content_hash`。
4. 截图生成。
5. PPTX XML 提取基础文本。
6. vision 描述和 fallback。
7. embedding 编码。
8. 写入 presentation、slides、screenshots。
9. job 标记 completed 或 failed。
10. 批量索引结束后触发 db backup。

## 公共接口

```python
@dataclass
class IndexResult:
    file_path: Path
    status: Literal["indexed", "skipped", "failed"]
    slides_indexed: int
    warnings: list[str]
    errors: list[ErrorRecord]

def index_file(path: Path, settings: Settings) -> IndexResult: ...
def index_batch(root: Path, settings: Settings, full: bool = False) -> list[IndexResult]: ...
def should_skip_file(path: Path, existing: PresentationRecord | None, full: bool) -> bool: ...
```

## 增量判断

跳过条件：

- `full=False`
- path 已存在
- file_size 一致
- file_mtime 一致
- content_hash 一致
- 对应 job 状态为 completed

任何一个条件不满足都重新索引该文件。

## 错误处理

| 场景 | 行为 |
|---|---|
| 文件不存在 | failed job，`INDEX_FILE_NOT_FOUND` |
| 加密 PPTX | skipped 或 failed，warning 必须可见 |
| 损坏 PPTX | failed job，继续批量 |
| 截图部分失败 | 对应 slide 记录 warning，继续 |
| embedding 失败 | 文件标记 failed，错误写入 job，批量任务继续 |
| DB 写入失败 | 回滚当前文件 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_index_single_pptx_roundtrip_records` | presentation 和 slides 写入 |
| `test_index_batch_scans_nested_dir` | 批量目录 |
| `test_incremental_skips_unchanged` | 增量跳过 |
| `test_incremental_reindexes_changed_size` | size 变化 |
| `test_incremental_reindexes_changed_hash` | hash 变化 |
| `test_corrupt_file_failed_job` | 损坏文件 |
| `test_encrypted_file_warning` | 加密文件 |
| `test_image_only_slide_indexed_with_screenshot` | 图片页 |
| `test_partial_screenshot_failure_continues` | 局部截图失败 |
| `test_embedding_failure_records_error` | embedding 错误 |
| `test_batch_continues_after_one_failure` | 批量不中断 |
| `test_batch_triggers_backup` | backup |

当前实现补充：

- 文本抽取使用 PPTX 内部 XML，避免引入额外解析依赖。
- 中文 fixture 覆盖在 `tests/test_real_fixtures.py`。
- CLI 端到端覆盖在 `tests/test_e2e_cli.py`。

## 验收标准

- 单个真实 PPTX 可完成 index。
- 批量索引中一个坏文件不影响其他文件。
- 重复运行默认跳过未变化文件。
- job 表能反映每个文件最终状态。
