# 15 — Definition of Done 与验收清单

---

## 1. 单任务 DoD

```text
[ ] 基线已核验
[ ] Task scope 完成
[ ] 代码路径与当前仓库一致
[ ] Contract/Schema 版本化
[ ] 错误码和 fallback 明确
[ ] Unit tests
[ ] Integration tests
[ ] Failure tests
[ ] Migration/rollback（如适用）
[ ] Security/privacy review
[ ] Docs
[ ] Benchmark delta（如适用）
[ ] 全量测试真实运行
[ ] lint/type/build
[ ] 无真实客户资产
[ ] PR 描述包含已知限制
```

---

## 2. v1.5 DoD

```text
[ ] capabilities
[ ] Contract registry
[ ] Deck Master native contract
[ ] stable revision/canonical identity
[ ] migration 5
[ ] job stages/checkpoint/idempotency
[ ] cancel/resume/retry
[ ] incremental governance
[ ] archive/renderer safety
[ ] environment-neutral release check
[ ] wheel clean install
[ ] contract UAT 100%
[ ] migration/restore
[ ] crash recovery
[ ] 10k report
```

---

## 3. v1.6 DoD

```text
[ ] search documents
[ ] FTS5/BM25
[ ] vector backend and local ANN
[ ] atomic index activation
[ ] RRF fusion
[ ] hard/soft filters
[ ] search profiles
[ ] optional reranker with egress policy
[ ] query trace/explain
[ ] evaluation v2
[ ] public synthetic suite
[ ] private golden run
[ ] 10k/50k/100k performance
[ ] quality targets
[ ] protected queries
```

---

## 4. v1.7 DoD

```text
[ ] asset/revision model
[ ] layout/visual fingerprint
[ ] near duplicate
[ ] client variant guard
[ ] lineage
[ ] representative policy
[ ] classification provenance
[ ] feedback events
[ ] business ranking v2
[ ] health findings
[ ] confidentiality enforcement
[ ] asset pack round-trip
[ ] labeled benchmark
[ ] no destructive automation
```

---

## 5. v1.8 DoD

```text
[ ] application services
[ ] /api/v1
[ ] localhost session/CSRF
[ ] Workbench packaged
[ ] Dashboard
[ ] Search
[ ] Asset Detail
[ ] Duplicate/Version Review
[ ] Health
[ ] Job Monitor
[ ] safe batch
[ ] local audit
[ ] browser E2E
[ ] accessibility critical
[ ] 50k performance
[ ] no direct UI SQL
```

---

## 6. v1.9 DoD

```text
[ ] SQLite/Postgres contract
[ ] object store
[ ] vector adapter
[ ] queue/worker/lease
[ ] users/RBAC/token
[ ] audit
[ ] secret handling
[ ] local-to-server migration
[ ] connector SDK preview
[ ] Docker Compose
[ ] health/metrics/logs
[ ] backup/restore drill
[ ] 250k/20-user
[ ] Local Mode no regression
[ ] Preview limitations
```

---

## 7. v2.0 DoD

```text
[ ] organization/workspace
[ ] isolation tests
[ ] OIDC
[ ] role lifecycle
[ ] policy engine
[ ] approval/promotion
[ ] shared library
[ ] connector SDK GA
[ ] reference connectors
[ ] analytics
[ ] audit export
[ ] deployment reference
[ ] upgrade/rollback
[ ] DR
[ ] API/SDK freeze
[ ] search quality targets
[ ] 500k/50-user
[ ] independent security review
[ ] SBOM/attestation
[ ] docs/support policy
[ ] GA sign-off
```

---

## 8. 最终业务验收

### 8.1 个人用户

```text
[ ] 源码/正式包安装后可快速初始化
[ ] 明确确认扫描范围
[ ] 中断建库可继续
[ ] 10万页内检索可用
[ ] 结果可解释
[ ] 人工可治理
[ ] 数据默认本地
```

### 8.2 Deck Master

```text
[ ] capability negotiation
[ ] native selection contract
[ ] run/page/slot/query binding
[ ] canonical identity
[ ] score/provenance/health
[ ] no adapter guessing
[ ] feedback idempotent
```

### 8.3 资产管理员

```text
[ ] duplicate/version compare
[ ] manual override
[ ] key page approve
[ ] metadata batch
[ ] confidentiality
[ ] health backlog
[ ] export/review pack
```

### 8.4 团队/企业

```text
[ ] multi workspace
[ ] OIDC/RBAC
[ ] source connector
[ ] policy
[ ] audit
[ ] backup/restore
[ ] capacity
[ ] upgrade
[ ] no cross-workspace leak
```

---

## 9. 不通过条件

任意一项成立则版本不得宣称完成：

- 只完成 happy path；
- 测试结果未实际运行；
- 真实 migration 未验证；
- benchmark 未提供；
- fallback 静默；
- Contract 未验证；
- row id 仍作为跨系统唯一身份；
- Workbench 直接写 SQL；
- Server 模式无 Local 回归；
- 安全/隐私 P0/P1 未关闭；
- 公开仓库包含客户资产；
- release notes 未说明限制。
