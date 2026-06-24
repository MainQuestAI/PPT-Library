# 09 — 数据模型、稳定身份与 Schema Migration Spec

---

## 1. 目的

本文件定义 v1.5～v2.0 的数据演进纪律。它解决三个不同问题：

1. **数据库主键：** 本地存储实现细节；
2. **Revision Identity：** 某一确定内容版本的可重算身份；
3. **Canonical Asset Identity：** 跨版本、跨路径、跨数据库保持的逻辑资产身份。

三者不得混用。

---

## 2. 当前基线

公开 v1.4.1 代码显示数据库 `SCHEMA_VERSION = 4`，核心对象包括 presentations、slides、screenshots、index_jobs、deals、slide_usage、duplicate groups、deck families、deck insights 和 slide importance。

执行前 Codex 必须核验：

```text
current SCHEMA_VERSION
all migration functions
current indexes
current foreign keys
current backfill behavior
actual databases in use
```

本文中的后续 Schema 编号是规划编号。若当前仓库已变化，必须形成 migration mapping，不可覆盖已有编号。

---

## 3. 目标数据对象

### 3.1 Source

```text
source_id
workspace_id
source_type
locator_json
display_name
policy_json
status
created_at
updated_at
```

### 3.2 Deck

```text
deck_asset_id
deck_revision_id
family_id
source_id
source_locator_id
package_fingerprint
revision_label
metadata
```

### 3.3 Slide

```text
canonical_asset_id
slide_revision_id
deck_revision_id
page_number
fingerprint_version
text_hash
visual_hash
layout_hash
content_hash
metadata
```

### 3.4 Relationships

```text
lineage_edges
duplicate_groups_v2
family_memberships
classification_values
review_decisions
feedback_events
health_findings
```

### 3.5 Operations

```text
jobs
job_stages
job_events
job_checkpoints
migration_journal
import_journals
audit_events
```

---

## 4. 身份定义

## 4.1 Local Row ID

用途：

- SQL join；
- 内部性能；
- 兼容现有代码。

限制：

- 不能进入长期跨系统 Contract 作为唯一引用；
- 不能被 Deck Master 当作稳定主键；
- 数据库重建后可变化。

---

## 4.2 Slide Revision ID

定义：

> 对确定页面内容和其所依赖资源的版本化 fingerprint。

格式建议：

```text
srev_<base32_sha256>
```

Fingerprint payload：

```json
{
  "algorithm": "slide-fingerprint-v1",
  "slide_xml": "<canonical hash>",
  "relationships": [],
  "media_hashes": [],
  "chart_hashes": [],
  "notes_hash": null,
  "normalized_text_hash": "...",
  "layout_hash": "..."
}
```

必须满足：

- 相同逻辑内容、zip entry 顺序不同：相同；
- volatile properties 不同：相同；
- 文本、图、图表数据或布局实质变化：不同；
- fingerprint algorithm 更新：新 algorithm version，不覆盖旧值。

---

## 4.3 Deck Revision ID

格式：

```text
drev_<base32_sha256>
```

由：

- ordered slide revision ids；
- masters/themes/media dependencies；
- deck properties relevant subset；

生成。

---

## 4.4 Canonical Asset ID

格式：

```text
asset_<ulid>
deck_<ulid>
```

特性：

- 首次创建时生成；
- 持久保存；
- 不由数据库 row id 派生；
- 不因路径移动改变；
- 不因新 Revision 改变；
- export/import 保持；
- manual split 生成新 canonical id；
- merge 保留 chosen canonical id，并写 alias/tombstone。

Canonical Identity 不能完全依赖算法自动恢复。跨库稳定性通过 Asset Registry/Asset Pack 保证。

---

## 4.5 Source Locator

```json
{
  "provider": "local",
  "opaque_id": "...",
  "display_path": "/optional/local/path",
  "revision": "...",
  "etag": null
}
```

Server Contract 默认返回 opaque id，是否返回 display path 由 policy 决定。

---

## 5. Identity Resolution

优先级：

```text
1 exact slide_revision_id
2 imported canonical mapping
3 same source locator + revision continuity
4 confirmed lineage/manual override
5 high-confidence matching → needs review
6 new canonical asset
```

禁止：

- 只按标题合并；
- 只按 embedding 合并；
- 只按页码合并；
- 只按文件名中的 final 合并；
- 自动覆盖人工 split。

---

## 6. Manual Override

表：

```text
identity_overrides
- override_id
- action: merge | split | assign | prefer
- source_ids
- target_id
- reason
- actor
- created_at
- revoked_at
```

自动治理必须先读取 override。

---

## 7. Schema 演进规划

| 产品版本 | 规划 DB Schema | 核心变化 |
|---|---:|---|
| v1.4.1 | 4 | 当前公开基线 |
| v1.5 | 5 | jobs、identity、contract、migration journal |
| v1.6 | 6 | search docs、profiles、vector indexes、query traces、benchmark |
| v1.7 | 7 | revisions、lineage、classification、feedback、health |
| v1.8 | 8 | review decisions、local sessions、audit、revision tokens |
| v1.9 | 9 | server users/RBAC/connectors/job leases/imports |
| v2.0 | 10 | organization/workspace/policies/approvals/promotion |

若真实仓库中 Schema 已占用编号，按顺序平移。

---

## 8. Migration Framework

### 8.1 Migration Record

```text
migration_id
from_version
to_version
status
started_at
completed_at
app_version
backup_path
plan_hash
precheck_json
postcheck_json
error_json
```

### 8.2 状态

```text
planned
running
verifying
completed
failed
restored
```

### 8.3 流程

```text
preflight
→ backup
→ plan lock
→ transactional DDL/DML
→ backfill
→ derived index rebuild
→ verification
→ mark complete
```

### 8.4 锁

迁移期间：

- 禁止其他写任务；
- Local Mode 进入 read-only 或 maintenance；
- Server Mode readiness=false；
- migration owner heartbeat；
- stale lock 只能通过 recovery 命令处理。

---

## 9. Backup

Local：

- SQLite online backup API；
- config snapshot；
- schema/version；
- identities；
- artifact manifest。

Server：

- Postgres backup reference；
- object manifest；
- schema；
- vector rebuild metadata；
- policy/config sans secrets。

Backup 名称必须使用 UTC 和随机 suffix，避免同秒覆盖。

---

## 10. Backfill

### 10.1 Identity Backfill

v1.5：

1. 读取现有 slide；
2. 尽可能计算 revision fingerprint；
3. 对 exact duplicate 复用 revision id；
4. 为现有 canonical group 生成 canonical id；
5. 无 group 的 slide 独立 canonical；
6. 写 coverage report；
7. 不在迁移阶段运行 aggressive near duplicate merge。

### 10.2 Revision Backfill

v1.7：

- presentations → deck revisions；
- slides → slide revisions；
- current canonical mapping → slide assets；
- assembly lineage → lineage edge；
- deck family → deck asset/family；
- preserved legacy ids。

### 10.3 Review Backfill

v1.8：

- current status → initial review decision；
- unknown source 标记 `migration_derived`；
- 无人工信息不得标记 manual approved。

---

## 11. Compatibility Views

迁移期间可提供：

```sql
legacy_presentations_view
legacy_slides_view
```

现有代码通过 view/adapter 读取，直到 service layer 完成迁移。

不要长期双写相同事实到两套表而无 reconciliation。

---

## 12. Dual Read / Dual Write

仅在必要版本窗口使用：

- v1.5 identity map 与 legacy slides；
- v1.7 revision model 与 legacy search row；
- v1.8 review state 与 legacy status。

每个 dual-write 必须有：

- owner；
- start version；
- end version；
- reconciliation test；
- divergence metric；
- removal PR。

---

## 13. Derived Data

以下可重建：

- FTS；
- vector index；
- query traces；
- aggregates；
- health scan results（可重新扫描）；
- previews；
- HTML review；
- benchmark report。

以下不可随意丢失：

- canonical ids；
- manual overrides；
- review decisions；
- feedback events；
- audit；
- source policy；
- connector cursor；
- import journal。

Backup/restore 优先保护不可重建数据。

---

## 14. Consistency Validators

新增：

```bash
ppt-lib db validate
ppt-lib identity validate
ppt-lib lineage validate
ppt-lib search-index validate
ppt-lib blobs validate
```

检查：

- orphan FK；
- duplicate revision id；
- canonical preferred revision 不存在；
- missing blob；
- vector/search doc mismatch；
- lineage cycle（对不允许 cycle 的 relation）；
- multiple active representative；
- feedback target missing；
- completed job missing commit artifact；
- migration incomplete。

---

## 15. Restore

`restore` 不是简单复制数据库：

1. 目标进程停止或只读；
2. 验证 backup；
3. 保存当前失败现场；
4. 恢复 metadata；
5. 验证 blobs；
6. derived index rebuild/activate；
7. consistency validator；
8. smoke search；
9. 恢复写入；
10. 输出 restore report。

---

## 16. Local-to-Server Mapping

```text
local workspace → selected server workspace
local source_id → preserved or remapped
canonical_asset_id → preserved
revision_id → preserved
local path → source locator with redaction
local blobs → object store
local events → imported source tagged
local user → migration actor
```

冲突策略：

```text
same canonical + same revision → skip
same canonical + new revision → append
same canonical + incompatible metadata → conflict
same source locator + different canonical → review
```

---

## 17. Deletion / Tombstone

v2.0 前默认不硬删除核心资产。

```text
active
deprecated
archived
tombstoned
```

硬删除只在：

- policy 允许；
- retention 满足；
- 无 legal hold（若支持）；
- audit；
- blob inventory；
- dry-run；
- explicit apply。

Canonical id 不复用。

---

## 18. 数据库性能

- 为 workspace/status/family/identity/job 添加组合索引；
- 大 JSON 字段避免成为高频 filter；
- Query trace 分区/保留；
- feedback aggregate 异步；
- health finding 索引；
- Postgres explain plan 纳入性能测试；
- SQLite WAL/checkpoint 有监控；
- vacuum/analysis 有维护命令。

---

## 19. Migration Tests

每个 migration：

- empty DB；
- minimal DB；
- realistic fixture；
- corrupt DB；
- interrupted migration；
- repeated apply；
- restore；
- newer schema rejection；
- row counts；
- checksum；
- search smoke；
- identity mapping；
- downgrade behavior。

Fixture 不得包含客户数据。

---

## 20. Migration Release Gate

- pre/post validator pass；
- backup verified；
- no data loss；
- idempotent rerun；
- failure restores cleanly；
- current/previous supported versions；
- migration duration report；
- disk amplification report；
- release notes；
- operator guide；
- recovery commands tested。
