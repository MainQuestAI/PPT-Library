# ADR-002: Job Engine & Stage/Checkpoint Model

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** Project Owner, Architecture Review
**Superseded-By:** None

---

## Context

PPT Library v1.4.1 的 `ppt-lib index` 是一个同步、不可恢复的长任务。当前问题：

1. **崩溃无恢复**：OCR/embedding/renderer 失败后无法从断点继续
2. **无进度可见性**：用户无法知道当前 stage、完成百分比、失败原因
3. **无法取消**：Ctrl+C 后数据库可能处于半提交状态
4. **多 worker 全局治理**：每个 worker 独立执行 duplicate/version 全局重算，存在竞态风险
5. **无幂等保证**：同一文件重复索引可能产生重复记录

Spec Pack 03-v1.5 §4.4 要求建立 stage/checkpoint/idempotency/cancel/resume 模型。

---

## Decision

采用 **自研轻量 Job Engine + Stage/Checkpoint 模型 + Single Writer** 方案：

### 1. Job Tables

新增表：

```sql
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  source_id TEXT,
  source_locator TEXT,
  source_content_hash TEXT,
  pipeline_config_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  current_stage TEXT,
  total_units INTEGER DEFAULT 0,
  completed_units INTEGER DEFAULT 0,
  failed_units INTEGER DEFAULT 0,
  attempt INTEGER DEFAULT 1,
  cancel_requested INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  error_json TEXT,
  warning_json TEXT
);

CREATE TABLE job_stages (
  stage_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  stage_name TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  artifact_path TEXT,
  error_json TEXT
);

CREATE TABLE job_events (
  event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  payload_json TEXT
);

CREATE TABLE job_checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  stage_name TEXT NOT NULL,
  checkpoint_data_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE staged_assets (
  staged_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  slide_revision_id TEXT,
  asset_data_json TEXT NOT NULL,
  committed INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
```

### 2. Pipeline Stages

```text
discover → extract → render → recognize → embed → stage → commit → govern → finalize
```

每阶段输出可重放 artifact：

```text
~/.ppt-library/jobs/<job_id>/
├── job.json
├── checkpoints/
├── extracted/
├── rendered/
├── recognized/
├── embeddings/
└── logs/
```

### 3. Idempotency Key

```text
source_locator_id
+ source_content_hash
+ pipeline_config_hash
+ fingerprint_algorithm_version
```

同一 key：
- 已 completed：返回已有结果
- running：返回现有 job
- failed：由 `--retry` 决定
- config 变化：创建新 job
- `--full`：强制新 pipeline config hash

### 4. Writer Model（v1.5 Local Mode）

- extract/render/OCR/embed 可并行（多 worker）
- metadata commit 由单 writer 串行执行（避免 SQLite 全局锁竞态）
- SQLite transaction 以文件或 staging batch 为单位
- governance 在 commit 后增量执行（只处理 affected set）
- worker 不直接全局删除 duplicate/version 表

### 5. CLI

```bash
ppt-lib index --from-sources --detach
ppt-lib jobs list --status running
ppt-lib jobs inspect <job-id>
ppt-lib jobs cancel <job-id>
ppt-lib jobs resume <job-id>
ppt-lib jobs retry <job-id>
```

兼容模式下，未加 `--detach` 可以同步等待，但内部仍使用 Job Engine。

### 6. Crash Recovery

必须覆盖：
- OCR 进程失败
- embedding endpoint timeout
- LibreOffice 卡死
- SQLite busy
- 用户 Ctrl+C
- 主进程被 kill
- 磁盘空间不足
- source 文件在运行期间变化

文件发生变化时，不得把不同版本阶段结果混为同一 revision。

---

## Consequences

### Positive

- ✅ 索引中断可恢复，不丢失已完成工作
- ✅ 进度可见，用户可监控长任务
- ✅ 可取消，不产生半提交状态
- ✅ 幂等保证，重复索引不产生重复记录
- ✅ Single writer 避免 SQLite 全局锁竞态
- ✅ Stage artifact 可重放，便于调试

### Negative

- ⚠️ Job Engine 实现复杂度较高，预计 2-3 周开发
- ⚠️ 需要维护 job/stage/checkpoint 状态机
- ⚠️ Staging artifact 占用额外磁盘空间（建议 TTL 7 天）
- ⚠️ Single writer 可能成为高并发场景瓶颈（v1.9 Server Mode 需要重新设计）

### Neutral

- 🔘 Job Engine 是自研轻量实现，不引入 Celery/Dramatiq 等外部依赖
- 🔘 v1.5 只覆盖 Local Mode，Server Mode 的 Queue/Worker/Leases 在 v1.9 实现

---

## Alternatives Considered

### Option A: Celery/Dramatiq（rejected）

**描述**：引入成熟的分布式任务队列框架。

**拒绝原因**：
- 需要 Redis/RabbitMQ 等外部依赖，违背 local-first 原则
- 框架复杂度高，学习曲线陡峭
- v1.5 Local Mode 不需要分布式能力
- 增加运维负担

### Option B: SQLite-only 同步任务（rejected）

**描述**：保持当前同步、不可恢复的任务模型。

**拒绝原因**：
- 无法支持崩溃恢复
- 无法支持进度监控和取消
- 多 worker 全局治理存在竞态风险
- 不符合 spec pack 要求

### Option C: 自研轻量 Job Engine（accepted）

**描述**：基于 SQLite + 文件系统实现 stage/checkpoint/idempotency 模型。

**选择原因**：
- 无外部依赖，符合 local-first 原则
- 复杂度可控，可针对 PPT Library 场景优化
- 支持崩溃恢复、进度监控、取消
- Single writer 避免 SQLite 全局锁竞态
- v1.9 Server Mode 可以在此基础上扩展 Queue/Worker/Leases

---

## Compliance

- ✅ 符合 03-v1.5 §4.4 Job Engine v1
- ✅ 支持 10-benchmark-quality-gates-and-test-matrix.md 的 crash recovery 测试要求
- ✅ 不影响 02-cross-version-contracts-and-compatibility.md 的 CLI 兼容性

---

## Notes

- Job Engine 实现建议放在 `ppt_lib/jobs/`
- Ingest service 实现建议放在 `ppt_lib/services/ingest_service.py`
- v1.5-E 任务需要实现完整的 Job Engine 和 crash recovery 测试
- v1.9-C 任务需要在此基础上实现 Queue/Worker/Leases 支持 Server Mode
