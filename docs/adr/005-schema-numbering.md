# ADR-005: Database Schema Numbering Strategy

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** Project Owner, Architecture Review
**Superseded-By:** None

---

## Context

PPT Library v1.4.1 当前 DB `SCHEMA_VERSION = 4`。Spec Pack 03-v1.5 §4.6 要求建立明确的 schema migration 流程，支持 backup/verify/recovery。

当前状态：
- `SCHEMA_VERSION` 定义在 `ppt_lib/db.py:12`
- Migration 逻辑分散在 `db.py` 的 `init_db()` 和 `migrate_schema()` 函数
- 无 migration journal、无 backup、无 verify、无 recovery
- 启动时仅检查 schema version，不检查 migration 状态

---

## Decision

采用 **线性版本号 + Migration Journal + Backup/Verify/Recovery** 方案：

### 1. Schema Version Numbering

**线性递增**：`4 → 5 → 6 → ...`

- 每个 PPT Library 版本对应一个目标 schema version
- Schema version 独立于 PPT Library 版本号（避免 semver 混淆）
- Migration 必须线性执行，不支持 skip（如 4 → 6 必须经过 4 → 5 → 6）

**版本映射**：

| PPT Library Version | Target Schema Version |
|---|---|
| v1.4.1 | 4 |
| v1.5.0 | 5 |
| v1.6.0 | 6 |
| v1.7.0 | 7 |
| v1.8.0 | 7（无 schema 变更） |
| v1.9.0 | 8（Postgres 引入） |
| v2.0.0 | 9 |

### 2. Migration Journal

新增表：

```sql
CREATE TABLE migration_journal (
  migration_id TEXT PRIMARY KEY,
  from_version INTEGER NOT NULL,
  to_version INTEGER NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  backup_path TEXT,
  error_json TEXT,
  row_counts_json TEXT,
  verify_result_json TEXT
);
```

每次 migration 写入 journal，状态包括：
- `planned`：migration 计划已写入
- `backup_created`：backup 已创建
- `in_progress`：migration 正在执行
- `completed`：migration 成功，verify 通过
- `failed`：migration 失败，需要 recovery
- `rolled_back`：migration 失败，已从 backup 恢复

### 3. Migration Flow

```text
1. Check DB integrity (PRAGMA integrity_check)
2. Create timestamped backup (~/.ppt-library/backups/schema_v4_20260623_120000.db)
3. Write migration journal (status=planned)
4. Create new tables and indexes
5. Backfill data (e.g., identity mapping)
6. Verify row counts, foreign keys, hash uniqueness
7. Update SCHEMA_VERSION in _meta table
8. Mark migration completed in journal
9. On failure: rollback transaction, restore from backup
```

### 4. Startup Check

启动时检查：

| 状态 | 行为 |
|---|---|
| Schema 当前（program version == DB version） | 正常启动 |
| Schema 旧且可迁移（program version > DB version） | 提示用户执行 `ppt-lib migrate apply` |
| Schema 新于程序（program version < DB version） | 拒绝写入，提示升级 PPT Library |
| Migration incomplete（journal status != completed） | 进入 recovery mode，提示 `ppt-lib migrate restore` |

### 5. CLI

```bash
ppt-lib migrate plan
ppt-lib migrate apply
ppt-lib migrate verify
ppt-lib migrate restore <backup>
```

- `plan`：显示 migration 计划、预计时间、affected rows
- `apply`：执行 migration，创建 backup，写入 journal
- `verify`：校验 row counts、foreign keys、hash uniqueness
- `restore`：从 backup 恢复，标记 journal status=rolled_back

### 6. Backup Strategy

**备份位置**：`~/.ppt-library/backups/`

**备份命名**：`schema_v<from_version>_<timestamp>.db`

**备份保留策略**：
- 最近 3 次 migration backup 永久保留
- 更早的 backup 可手动清理

### 7. Schema 5 Migration（v1.4.1 → v1.5.0）

新增表和索引：

```sql
-- Jobs
CREATE TABLE jobs (...);
CREATE TABLE job_stages (...);
CREATE TABLE job_events (...);
CREATE TABLE job_checkpoints (...);
CREATE TABLE staged_assets (...);

-- Identity
CREATE TABLE asset_identity_map (...);
CREATE TABLE deck_asset_identity (...);
CREATE TABLE identity_overrides (...);

-- Contracts
CREATE TABLE contract_registry (...);

-- Migration
CREATE TABLE migration_journal (...);
```

Backfill：
- 为所有现有 slides 生成 `slide_revision_id`
- 为所有现有 slides 生成 `canonical_asset_id`（标记 `identity_status=legacy_unresolved`）
- 为所有现有 presentations 生成 `deck_asset_id`

---

## Consequences

### Positive

- ✅ Schema migration 流程清晰，可追溯
- ✅ Backup 提供 recovery 能力
- ✅ Journal 提供 migration 历史和状态
- ✅ Startup check 防止不一致状态
- ✅ CLI 提供用户友好的 migration 操作界面

### Negative

- ⚠️ Migration journal 和 backup 占用额外磁盘空间
- ⚠️ Migration flow 复杂度高，需要充分测试
- ⚠️ Recovery 流程需要用户干预
- ⚠️ Linear numbering 不支持 parallel migration branches

### Neutral

- 🔘 Schema version 独立于 PPT Library 版本号，增加认知负担但避免 semver 混淆
- 🔘 Backup 保留策略平衡了磁盘空间和安全需求

---

## Alternatives Considered

### Option A: Semver-style schema versioning（rejected）

**描述**：使用 `MAJOR.MINOR.PATCH` 格式（如 `4.0.0 → 5.0.0`）。

**拒绝原因**：
- Semver 语义与 schema migration 不匹配（什么是 "breaking change"？）
- 增加复杂度，无实际收益
- 不符合 SQLite 生态惯例

### Option B: Timestamp-based versioning（rejected）

**描述**：使用 timestamp 作为 schema version（如 `20260623120000`）。

**拒绝原因**：
- 无法直观判断版本新旧
- 不支持 linear migration ordering
- 增加 journal 查询复杂度

### Option C: Linear numbering + journal + backup（accepted）

**描述**：线性递增版本号 + migration journal + backup/verify/recovery。

**选择原因**：
- 简单直观，符合 SQLite 生态惯例
- Journal 提供完整的 migration 历史
- Backup 提供 recovery 能力
- 符合 spec pack 要求

---

## Compliance

- ✅ 符合 03-v1.5 §4.6 Database Migration
- ✅ 符合 09-data-schema-migrations-and-identity.md 的 migration 要求
- ✅ 支持 12-release-rollout-and-backward-compatibility.md 的升级策略

---

## Notes

- Migration engine 实现建议放在 `ppt_lib/migrations/`
- Journal 和 backup 管理建议放在 `ppt_lib/migrations/journal.py` 和 `ppt_lib/migrations/backup.py`
- v1.5-D 任务需要实现完整的 schema 5 migration 和 recovery 测试
- v1.9-A 任务需要在此基础上实现 Postgres repository 和跨数据库 migration
