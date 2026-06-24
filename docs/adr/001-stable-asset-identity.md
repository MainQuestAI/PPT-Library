# ADR-001: Stable Asset Identity Algorithm

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** Project Owner, Architecture Review
**Superseded-By:** None

---

## Context

PPT Library v1.4.1 当前使用 SQLite row id（`INTEGER PRIMARY KEY`）作为资产唯一标识。这导致以下问题：

1. **跨环境断裂**：数据库重建、文件移动、Server Migration 后引用失效
2. **无法导出/导入**：资产 registry 无法跨库迁移
3. **Deck Master 集成脆弱**：上层系统无法稳定引用逻辑资产
4. **去重/血缘不可追溯**：duplicate group 和 deck family 依赖 row id，无法跨会话保持

Spec Pack 03-v1.5 §4.3 要求建立分层身份模型，区分"逻辑资产"和"内容版本"。

---

## Decision

采用 **分层身份 + 内容指纹 + 显式 canonical mapping** 方案：

### 1. 身份分层

| 字段 | 生成方式 | 用途 |
|---|---|---|
| `source_id` | 注册时 UUIDv7/ULID | 来源逻辑身份 |
| `deck_revision_id` | `drev_` + package fingerprint | 某一 Deck 内容版本 |
| `slide_revision_id` | `srev_` + canonical content fingerprint | 某一页确定内容版本 |
| `canonical_asset_id` | 首次创建时生成并持久化 | 逻辑可复用页面（跨 revision） |
| `deck_asset_id` | 首次归族时生成并持久化 | 逻辑 Deck（跨版本） |
| `source_locator_id` | provider + opaque locator hash | 来源定位（可变化） |

### 2. Fingerprint 算法

`slide_revision_id` 的 fingerprint 输入：
- canonicalized slide XML（排除 volatile modified time）
- resolved relationship targets
- embedded media hashes
- visible text normalized hash
- chart/workbook relationship hashes
- optional rendered perceptual hash
- fingerprint algorithm version（`slide-fingerprint-v1`）

**排除**：
- 文件路径
- 数据库 row id
- OOXML volatile modified time
- zip entry order
- 无业务意义的 relationship id 差异

### 3. Canonical ID 行为

- canonical id 是持久身份，不要求完全由内容推导
- exact revision 命中时复用 canonical id
- source locator continuity 强且内容近似时进入 lineage matcher
- 不确定时创建新 canonical id 并标记 `identity_status=needs_review`
- 禁止仅因 embedding 相似就自动合并
- 资产 registry 可导出/导入，保证跨库迁移

### 4. Legacy Mapping

新增表 `asset_identity_map`：

```sql
CREATE TABLE asset_identity_map (
  canonical_asset_id TEXT NOT NULL,
  slide_revision_id TEXT NOT NULL,
  legacy_slide_id INTEGER,
  identity_status TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (canonical_asset_id, slide_revision_id)
);
```

现有 slide row 先建立 legacy mapping，不强制第一次迁移完成所有 lineage。

---

## Consequences

### Positive

- ✅ 跨数据库重建、文件移动、导入导出时引用稳定
- ✅ Deck Master 可直接使用 canonical id，不依赖 row id
- ✅ 资产 registry 可导出/导入，支持 Server Migration
- ✅ duplicate/version 治理可追溯
- ✅ 人工 override 有明确记录

### Negative

- ⚠️ 首次迁移需要 backfill identity，10 万页规模预计 2-5 分钟
- ⚠️ fingerprint 算法需要覆盖 OOXML 各种 edge case（chart、embedded object、external relationship）
- ⚠️ 需要维护 `identity_status` 状态机（`resolved`、`needs_review`、`legacy_unresolved`）

### Neutral

- 🔘 Canonical id 不是纯内容推导，需要额外存储和索引
- 🔘 Fingerprint 算法版本升级时需要重算 revision id

---

## Alternatives Considered

### Option A: 纯内容哈希（rejected）

**描述**：canonical id 完全由内容哈希推导，无需额外存储。

**拒绝原因**：
- 人工标注、审批、feedback 无法绑定到内容哈希
- 同一内容在不同上下文（客户 A vs 客户 B）可能需要不同治理策略
- 无法支持"逻辑资产跨多个 revision"的场景

### Option B: UUID 随机生成（rejected）

**描述**：每个 slide 生成随机 UUID 作为 canonical id。

**拒绝原因**：
- 无法区分"同一内容的不同 revision"
- duplicate detection 仍需内容比对
- 跨库迁移时无法自动重建映射

### Option C: 混合方案（accepted）

**描述**：revision id 由内容推导，canonical id 持久化并支持人工 override。

**选择原因**：
- 平衡了内容确定性和人工治理需求
- 支持跨库迁移和 registry 导出
- 符合 spec pack 要求

---

## Compliance

- ✅ 符合 03-v1.5 §4.3 Stable Asset Identity v1
- ✅ 支持 09-data-schema-migrations-and-identity.md 的 migration 要求
- ✅ 不影响 02-cross-version-contracts-and-compatibility.md 的 contract 兼容性

---

## Notes

- Fingerprint 算法实现建议放在 `ppt_lib/identity/fingerprint.py`
- Identity registry 实现建议放在 `ppt_lib/identity/registry.py`
- Migration 4→5 时需要 backfill identity，建议提供 `ppt-lib migrate plan` 预览
- 后续 v1.7 的 near duplicate detection 可以基于 revision id 的近似匹配扩展
