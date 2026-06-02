# Spec 02: Database

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/db.py`
Tasks: T2, T9, T21, T22

## 职责

数据库层负责 SQLite schema、连接管理、事务、WAL、CRUD、失败恢复状态和一致性备份。

它不负责解析 PPTX，不调用 embedding，不生成截图。

## Schema

以当前 `ppt_lib/db.py` 的 schema 和迁移逻辑为基线。实现时可以增加索引，但不能减少已有字段。

必须创建的索引：

```sql
CREATE INDEX IF NOT EXISTS idx_presentations_path ON presentations(path);
CREATE INDEX IF NOT EXISTS idx_slides_presentation ON slides(presentation_id);
CREATE INDEX IF NOT EXISTS idx_slides_screenshot_hash ON slides(screenshot_hash);
CREATE INDEX IF NOT EXISTS idx_index_jobs_file_status ON index_jobs(file_path, status);
```

## 公共接口

```python
def connect(db_path: Path) -> sqlite3.Connection: ...
def init_db(conn: sqlite3.Connection) -> None: ...
def backup_db(conn: sqlite3.Connection, backups_dir: Path) -> Path: ...

def upsert_presentation(conn, record: PresentationRecord) -> int: ...
def upsert_slide(conn, record: SlideRecord) -> int: ...
def insert_screenshot(conn, record: ScreenshotRecord) -> None: ...

def get_all_embeddings(conn) -> list[EmbeddingRow]: ...
def get_stats(conn) -> LibraryStats: ...
def list_orphan_presentations(conn) -> list[PresentationRecord]: ...

def create_or_update_job(conn, file_path: Path, status: str, **fields) -> int: ...
def mark_job_completed(conn, job_id: int) -> None: ...
def mark_job_failed(conn, job_id: int, error_msg: str) -> None: ...
def list_failed_jobs(conn) -> list[IndexJobRecord]: ...
```

数据对象优先用 dataclass 或 Pydantic model，避免裸 tuple 在模块间传递。

## 事务策略

- `init_db` 必须幂等。
- 批量写入由调用方控制事务边界。
- 单文件索引失败时，只回滚该文件相关写入和 job 状态，不影响其他文件。
- `backup_db` 必须使用 `sqlite3.Connection.backup()`，不能直接复制 db 文件。

## 错误处理

| 场景 | 行为 |
|---|---|
| 数据库不存在 | `init_db` 创建 |
| schema 旧版本 | V1 可直接迁移新增字段；失败时给出 `DB_MIGRATION_FAILED` |
| 写入失败 | 抛出 `DatabaseError`，保留原始异常信息摘要 |
| backup 磁盘满 | 删除不完整 backup，返回结构化错误 |
| embedding BLOB 不是一维 float32 | 拒绝写入 slide |
| embedding 维度与当前搜索配置不一致 | 写入允许，搜索阶段按当前维度过滤 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_init_db_creates_schema` | 全部表和索引存在 |
| `test_init_db_idempotent` | 重复执行无副作用 |
| `test_wal_enabled` | `PRAGMA journal_mode` 为 WAL |
| `test_upsert_presentation_updates_by_path` | path 唯一 |
| `test_upsert_slide_unique_by_presentation_and_index` | slide 幂等 |
| `test_insert_screenshot_deduplicates_by_hash` | 截图去重 |
| `test_get_all_embeddings_shape` | embedding 可还原为 float32 |
| `test_upsert_slide_accepts_configurable_embedding_dimensions` | 支持本地模型 768 维 |
| `test_stats_include_failed_jobs_and_orphans` | status 所需统计齐全 |
| `test_index_job_lifecycle` | pending 到 completed/failed |
| `test_backup_uses_consistent_snapshot` | backup 可打开且数据完整 |
| `test_source_field_accepts_only_allowed_values` | `source` 约束 |
| `test_extraction_warnings_roundtrip` | warning 可写可读 |

## 验收标准

- 空数据库初始化后，`status` 所需信息全部可查询。
- index 和 search 并发时，读操作不阻塞写操作。
- 失败 job 可查询、可重试、可被 status 展示。
