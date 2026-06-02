# Spec 08: Watch

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/watch.py`
Task: T17

## 职责

Watch 层负责监听目录内 PPTX 新增和修改事件，做 debounce、文件稳定性检查、队列化索引和健康检查。

它不直接解析 PPTX，实际索引调用 indexer。

## 行为

- 默认只支持 macOS 本地开发路径，Linux 兼容性后置到 TODOS。
- 忽略 `.db`、临时文件、非 PPTX 文件。
- 快速重复保存只触发一次索引。
- 进程收到 SIGINT 时完成当前文件后退出。

## 公共接口

```python
@dataclass
class WatchEvent:
    path: Path
    event_type: Literal["created", "modified", "moved"]
    detected_at: datetime

def watch_directory(root: Path, settings: Settings, index_callback: Callable[[Path], None]) -> None: ...
def is_pptx_candidate(path: Path) -> bool: ...
def wait_until_file_stable(path: Path, interval_seconds: int = 2, attempts: int = 3) -> bool: ...
```

当前实现补充：

- `watch_directory(...)` 内部使用 `WatchService` 长驻运行。
- `WatchService` 使用 watchdog observer 监听新增、修改和移动事件。
- 快速重复保存会刷新同一路径的 debounce 时间，只保留一次队列项。
- Observer 停止后会记录 `WATCH_OBSERVER_RESTARTED` 并重启一次，仍失败时抛出 `WATCH_OBSERVER_STOPPED`。

## 队列策略

- 单 worker 默认顺序执行。
- 队列中相同路径去重。
- 50+ 文件批量进入时输出进度。
- 失败文件标记 job failed，不阻断队列。

## 健康检查

- observer 崩溃时记录 `WATCH_OBSERVER_STOPPED`。
- 可配置 heartbeat 日志间隔。
- 长时间无事件时不输出噪音。

## 错误处理

| 场景 | 行为 |
|---|---|
| watch root 不存在 | 立即返回结构化错误 |
| watchdog observer 异常 | 尝试重启一次，失败后退出 |
| 文件持续写入不稳定 | 延后重试，最终 failed job |
| indexer 异常 | 记录 job failed，继续后续队列 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_non_pptx_ignored` | 文件过滤 |
| `test_temp_files_ignored` | 临时文件过滤 |
| `test_debounce_double_save_single_trigger` | debounce |
| `test_queue_deduplicates_same_path` | 队列去重 |
| `test_wait_until_file_stable_success` | 稳定性检查 |
| `test_wait_until_file_stable_failure` | 持续写入 |
| `test_indexer_failure_continues_queue` | 单文件失败不中断 |
| `test_observer_restart_once` | 健康检查 |
| `test_sigint_graceful_shutdown` | 优雅退出 |

## 验收标准

- 新文件保存后能触发索引。
- 快速重复保存不会重复索引。
- watch 异常可见，不会静默停止。
