# Spec 07: Discovery

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/discovery.py`
Task: T16

## 职责

Discovery 层负责扫描项目目录，找到 PPTX，识别项目归属，按版本规则去重，并生成软链接统一视图。

它不解析 PPTX 内容，不写 slide 表。

## 输入

- 目录路径。
- 可选 include/exclude pattern。
- 可选 project depth。
- settings 中的 `symlinks_dir`。

## 版本去重规则

优先级：

1. 文件名显式版本号，例如 `v3`、`V03`、`final2`。
2. 文件修改时间较新。
3. 文件大小较大。
4. 路径字典序稳定排序。

被去重掉的文件不删除，只在 discovery 输出里标记 `selected=false`。

## 公共接口

```python
@dataclass
class DiscoveredPresentation:
    path: Path
    project_name: str | None
    filename: str
    version_key: str | None
    file_size: int
    file_mtime: float
    selected: bool
    reason: str

def scan_presentations(root: Path, settings: Settings) -> list[DiscoveredPresentation]: ...
def deduplicate_versions(items: list[DiscoveredPresentation]) -> list[DiscoveredPresentation]: ...
def create_symlink_view(items: list[DiscoveredPresentation], settings: Settings) -> list[Path]: ...
```

## Symlink 命名

```text
{project_name}__{filename}
```

冲突时追加短 hash：

```text
{project_name}__{stem}__{hash8}.pptx
```

## 错误处理

| 场景 | 行为 |
|---|---|
| 目录不存在 | 返回 `DISCOVERY_ROOT_NOT_FOUND` |
| 无权限目录 | 跳过并记录 warning |
| 文件名编码异常 | 使用安全替代名，记录 warning |
| symlink 已存在但指向不同文件 | 使用 hash 后缀创建新链接 |
| 云盘路径变化导致断链 | status 检测，不自动修复 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_scan_empty_dir` | 空目录返回空 |
| `test_scan_mixed_files_only_pptx` | 只收 PPTX |
| `test_group_by_project_from_parent_dir` | 项目名识别 |
| `test_dedup_v_number_prefers_highest` | vN 规则 |
| `test_dedup_mtime_fallback` | mtime fallback |
| `test_dedup_size_fallback_stable` | 稳定排序 |
| `test_symlink_collision_adds_hash` | 命名冲突 |
| `test_permission_error_warning` | 无权限跳过 |
| `test_broken_symlink_reportable` | 断链可检测 |

## 验收标准

- discovery 输出可直接交给 indexer。
- 不删除、不移动用户原始 PPTX。
- 软链接视图可重复生成且结果稳定。
