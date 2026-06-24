# ADR-003: Single Writer Model for Local Mode

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** Project Owner, Architecture Review
**Superseded-By:** None

---

## Context

PPT Library v1.4.1 使用 SQLite 作为主数据库。当前 `ppt-lib index` 支持 `--file-workers N` 参数实现文件级并行索引，但存在以下问题：

1. **SQLite 全局锁竞态**：多个 worker 同时写入时触发 `SQLITE_BUSY` 错误
2. **Duplicate/Version 全局重算**：每个 worker 独立执行全局 duplicate/version 治理，存在竞态风险
3. **事务边界不清**：单个文件的索引结果可能部分提交、部分失败
4. **无法支持 cancel/resume**：多 worker 并行时取消和恢复逻辑复杂

Spec Pack 03-v1.5 §4.4.4 要求建立 Single Writer 模型，区分可并行阶段和必须串行阶段。

---

## Decision

采用 **多 Reader/Worker + Single Writer + Staging Batch Commit** 方案：

### 1. Pipeline 阶段划分

| 阶段 | 并行性 | 说明 |
|---|---|---|
| discover | 单线程 | 扫描 source 目录，生成文件清单 |
| extract | 多 worker | 并行抽取 PPTX XML/文本 |
| render | 多 worker | 并行调用 LibreOffice 渲染截图 |
| recognize | 多 worker | 并行调用 OCR/vision provider |
| embed | 多 worker | 并行调用 embedding provider |
| **stage** | **单 writer** | 将 worker 结果写入 staging 表 |
| **commit** | **单 writer** | 从 staging 表原子提交到主表 |
| govern | 单线程 | 增量执行 duplicate/version 治理 |
| finalize | 单线程 | 更新 job 状态、清理 staging |

### 2. Staging Table

```sql
CREATE TABLE staged_assets (
  staged_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  slide_revision_id TEXT,
  asset_data_json TEXT NOT NULL,
  committed INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
```

Worker 将结果写入 `staged_assets`，Single Writer 负责从 staging 表原子提交到主表（`slides`、`screenshots`、`embeddings` 等）。

### 3. Transaction Boundary

- 每个文件的 staging 结果是独立事务
- commit 阶段以 staging batch 为单位（默认 batch size = 1，即单文件提交）
- governance 在 commit 后增量执行，只处理 affected set
- worker 不直接修改 duplicate/version 表

### 4. Writer 配置

```yaml
jobs:
  worker_count: 2
  writer_batch_size: 1
  checkpoint_interval_seconds: 10
```

- `worker_count`：extract/render/recognize/embed 阶段的并行 worker 数
- `writer_batch_size`：commit 阶段每次提交的 staging 记录数
- `checkpoint_interval_seconds`：checkpoint 写入间隔

### 5. CLI 兼容性

```bash
ppt-lib index --from-sources --file-workers 2
```

`--file-workers` 参数映射到 `jobs.worker_count`，内部仍使用 Job Engine 和 Single Writer 模型。

---

## Consequences

### Positive

- ✅ 避免 SQLite 全局锁竞态
- ✅ 事务边界清晰，单文件失败不影响其他文件
- ✅ Duplicate/version 治理只处理 affected set，不全局重算
- ✅ 支持 cancel/resume，staging 表提供清晰的恢复点
- ✅ CLI 兼容性保持，`--file-workers` 参数仍可用

### Negative

- ⚠️ Single writer 可能成为高并发场景瓶颈（extract/render 很快、commit 很慢时）
- ⚠️ Staging 表占用额外磁盘空间（建议 TTL 7 天）
- ⚠️ v1.9 Server Mode 需要重新设计 Queue/Worker/Leases 模型

### Neutral

- 🔘 v1.5 只覆盖 Local Mode，Server Mode 的并发模型在 v1.9 实现
- 🔘 `writer_batch_size` 默认 1，高吞吐场景可以调大（需要测试 SQLite 事务性能）

---

## Alternatives Considered

### Option A: 多 writer 并行提交（rejected）

**描述**：每个 worker 直接写入主表，使用 SQLite WAL 模式支持并发写入。

**拒绝原因**：
- SQLite WAL 模式仍有全局锁竞态（特别是 `PRAGMA journal_mode=WAL` 下多个 writer）
- Duplicate/version 全局重算存在竞态风险
- 事务边界不清，单文件失败可能导致部分提交
- 不符合 spec pack 要求

### Option B: 完全串行（rejected）

**描述**：所有阶段单线程执行，不使用多 worker。

**拒绝原因**：
- extract/render/recognize/embed 是 CPU/IO 密集型，串行性能差
- 10 万页规模预计需要 10+ 小时
- 违背 v1.4.1 已有的 `--file-workers` 并行能力

### Option C: 多 worker + Single writer + staging（accepted）

**描述**：extract/render/recognize/embed 多 worker 并行，stage/commit 单 writer 串行。

**选择原因**：
- 平衡了并行性能和事务安全性
- Staging 表提供清晰的恢复点
- Duplicate/version 治理只处理 affected set
- 符合 spec pack 要求

---

## Compliance

- ✅ 符合 03-v1.5 §4.4.4 Writer Model
- ✅ 支持 03-v1.5 §4.5 Incremental Duplicate/Version Governance
- ✅ 不影响 02-cross-version-contracts-and-compatibility.md 的 CLI 兼容性

---

## Notes

- Single writer 实现建议放在 `ppt_lib/jobs/writer.py`
- Staging 表清理建议放在 `ppt_lib/jobs/cleanup.py`
- v1.5-E 任务需要实现完整的 writer 模型和 staging commit 测试
- v1.9-C 任务需要在此基础上实现 Queue/Worker/Leases 支持 Server Mode
