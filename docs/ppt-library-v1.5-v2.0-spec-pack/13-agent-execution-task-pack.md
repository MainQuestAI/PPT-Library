# 13 — Agent Execution Task Pack

**Purpose:** 将 v1.5～v2.0 拆成可独立开发、评审、验证的任务。
**Rule:** 下列路径是建议路径，Agent 开工前必须先在真实仓库中核验。
**PR Discipline:** 每个任务必须引用 Task ID；不得跨 Task 顺手扩 Scope。

---

# 0. Agent 通用执行协议

每个 Agent 开始前必须：

```text
1. 读取本 Spec Pack 总纲、目标版本 Spec 和本任务。
2. 核验当前 HEAD、VERSION、SCHEMA_VERSION、CLI Schema、全量测试。
3. 输出“已确认事实 / 需要调整的 Spec 假设 / 实施计划”。
4. 只修改任务允许范围；必要越界先形成 ADR。
5. 新增或修改 machine contract 时先写 schema 和 tests。
6. 新增迁移时先写 migration fixture 和恢复测试。
7. 新增长任务时必须支持 structured status 和 failure。
8. 完成后执行专项测试、全量测试、lint、type、release smoke。
```

每个 Agent 交付必须包含：

```text
- Task ID
- 修改文件
- 数据/Contract 变化
- 测试命令与真实结果
- Benchmark delta
- Migration/rollback
- Security impact
- Known limitations
- Remaining work
```

不得写“理论上通过”；实际未运行必须明确标注。

---

# Wave A — Production Foundation

# v1.5 Tasks

## 1.5-A — Baseline Verification & ADR Pack

**目标：** 固定真实实施基线，关闭 Spec 与代码漂移。

**必须完成：**

- HEAD/VERSION/Schema/CLI command inventory；
- 当前 DB migration 流程；
- 当前 release_check 中环境耦合；
- 当前 Deck Master Contract 差异；
- 当前 index/concurrency/global recompute 行为；
- ADR：
  - identity algorithm；
  - job staging；
  - writer model；
  - package publishing；
  - schema numbering。

**建议文件：**

```text
docs/adr/
docs/diagnostics/v1.5-baseline.md
```

**验证：** 当前全量测试、build、release_check。
**DoD：** 后续任务可以引用确定路径、Schema 和 ADR；无代码功能扩张。

---

## 1.5-B — Contract Registry & Capabilities

**目标：** 建立 Contract Registry 和运行时 capability negotiation。

**建议路径：**

```text
ppt_lib/contracts/
ppt_lib/services/capability_service.py
docs/contracts/
tests/test_contract_registry.py
tests/test_capabilities_cli.py
```

**必须实现：**

- `capabilities --output json`；
- `contract list/show/validate`；
- Envelope/Contract metadata；
- JSON Schema fixtures；
- provider/storage/feature capability；
- strict validator；
- stable error codes。

**非目标：** Deck Master selection 业务实现。
**验证：** schema valid/invalid、no-model、optional extras、subprocess stdout。
**DoD：** capability 来自真实环境；不硬编码虚假可用状态。

---

## 1.5-C — Deck Master Native Selection Contract

**目标：** 原生输出 `deck_master_ppt_library_selection.v1`。

**依赖：** 1.5-B。

**必须实现：**

- `select-slides --contract deck-master.v1 --run-id`；
- page_task/slot/query trace 映射；
- atomic write；
- run binding；
- idempotency；
- canonical candidate fields；
- vendored schema sync metadata；
- cross-repo contract UAT。

**非目标：** 修改 Deck Master narrative decision。
**验证：** valid output、run mismatch、invalid candidate、empty selections、legacy output regression。
**DoD：** Deck Master 可直接导入，不需要字段猜测。

---

## 1.5-D — Stable Identity & Schema 5 Migration

**目标：** 建立 revision/canonical identity 和 legacy mapping。

**建议路径：**

```text
ppt_lib/identity/
ppt_lib/migrations/
ppt_lib/db.py
tests/test_identity.py
tests/test_migration_v5.py
```

**必须实现：**

- canonicalized fingerprint；
- slide/deck revision ids；
- canonical ids；
- identity mapping；
- registry export/import；
- manual override foundation；
- migration backup/journal/verify；
- coverage report。

**非目标：** aggressive near duplicate。
**验证：** volatile XML、file move、DB rebuild with registry、migration failure/restore。
**DoD：** 跨 Contract 不再使用 row id 作为唯一身份。

---

## 1.5-E — Job Engine & Resumable Index

**目标：** 把 index 内部改为 stage/checkpoint/idempotency Job。

**依赖：** 1.5-D。

**建议路径：**

```text
ppt_lib/jobs/
ppt_lib/services/ingest_service.py
ppt_lib/indexer.py
tests/test_jobs.py
tests/test_index_resume.py
```

**必须实现：**

- job state machine；
- stage artifacts；
- checkpoints；
- single writer；
- cancel/resume/retry；
- source change detection；
- structured progress/events；
- sync CLI compatibility；
- cleanup policy。

**验证：** kill、Ctrl+C、provider timeout、renderer fail、SQLite busy、disk pressure fixture。
**DoD：** crash 不造成半提交或重复资产。

---

## 1.5-F — Incremental Governance

**目标：** duplicate/version 只处理受影响范围。

**依赖：** 1.5-D、E。

**必须实现：**

- affected set；
- incremental group/family update；
- representative recalculation；
- manual override preservation；
- dry-run change summary；
- consistency validator；
- full rebuild repair command。

**验证：** 单文件更新不全表重建；manual split/representative preserved。
**DoD：** 多 worker 不再各自执行全局 destructive rebuild。

---

## 1.5-G — PPTX / Renderer Safety

**目标：** 加固不可信 PPTX 和外部 renderer。

**必须实现：**

- archive limits；
- path traversal；
- external relationship inventory；
- embedded object warning；
- renderer timeout；
- temp isolation；
- source mutation；
- resource errors；
- quarantine/report。

**验证：** malicious synthetic fixtures。
**DoD：** 无宏执行；异常文件有明确错误码且不污染 DB。

---

## 1.5-H — Distribution, CI & Release Gate

**目标：** 让 v1.5 可 clean install、迁移和发布。

**依赖：** B～G。

**必须实现：**

- environment-neutral release_check；
- wheel/sdist；
- clean install；
- platform CI；
- optional extra tests；
- SBOM/security scan；
- migration matrix；
- Deck Master UAT gate；
- release docs。

**DoD：** RC Artifact 可从 clean checkout 重建并验证。

---

# v1.6 Tasks

## 1.6-A — Search Document & FTS5

**目标：** 建立可重建 Search Document 和 FTS lexical recall。

**必须实现：**

- search document schema；
- FTS tables；
- title/body/summary/role fields；
- tokenizer/version；
- incremental update；
- rebuild/validate；
- lexical explain。

**验证：** Chinese/English/mixed、exact phrase、filters、no FTS fallback。
**DoD：** 默认 lexical recall 不再全量 Python 字符串扫描。

---

## 1.6-B — Vector Backend & ANN Lifecycle

**目标：** 建立 vector backend interface 和 local ANN。

**依赖：** 1.6-A。

**必须实现：**

- sqlite_scan compatibility；
- local ANN；
- index metadata；
- build/activate/rollback；
- model/dimension compatibility；
- atomic activation；
- backend health；
- optional dependency packaging。

**验证：** build failure 保持旧索引、dimension mismatch、reopen、100k fixture。
**DoD：** backend 可替换，上层 response 不变。

---

## 1.6-C — Fusion, Filters & Search Profiles

**目标：** RRF fusion、hard filters、versioned profiles。

**依赖：** A、B。

**必须实现：**

- dual recall；
- RRF；
- hard/soft semantics；
- duplicate/version collapse；
- profiles；
- deterministic query parsing；
- `deck_master` profile。

**验证：** hard filtered item 永不返回；profile schema；legacy search regression。
**DoD：** 权重不散落在代码中。

---

## 1.6-D — Reranker & Provider Egress

**目标：** 可选 rerank，且数据外发受控。

**依赖：** C。

**必须实现：**

- provider interface；
- local/cloud；
- top-N；
- timeout/fallback；
- egress policy；
- request minimization；
- capability；
- explain fields。

**DoD：** reranker 失败不产生假成功或静默结果变化。

---

## 1.6-E — Query Trace & Explainability

**目标：** 每次搜索可复现和解释。

**依赖：** C。

**必须实现：**

- query_trace_id；
- backend counts；
- timings；
- model/profile versions；
- fallback；
- candidate score breakdown；
- matched fields；
- redaction/retention。

**验证：** trace rank 与 response 一致；无 secret/content leak。
**DoD：** Deck Master 和 Workbench 可读取同一 explanation。

---

## 1.6-F — Evaluation v2 & Datasets

**目标：** 建立 release benchmark。

**依赖：** C。

**必须实现：**

- graded relevance；
- Recall/Precision/MRR/nDCG；
- useful review schema；
- public synthetic suite；
- private manifest contract；
- protected query；
- compare/promote baseline。

**DoD：** release gate 可自动判断 pass/fail。

---

## 1.6-G — Scale & Performance Harness

**目标：** 10k/50k/100k 可复跑性能报告。

**依赖：** B、F。

**必须实现：**

- dataset generator；
- cold/warm；
- latency/memory/index time；
- hardware manifest；
- concurrency；
- regression compare。

**DoD：** 报告记录环境，不允许只写主观结论。

---

## 1.6-H — Search Release Gate

**目标：** 固化默认 Profile 和发布证据。

**依赖：** D～G。

**必须完成：**

- private golden；
- public suite；
- default profile；
- protected queries；
- benchmark summary；
- docs；
- no-model mode；
- Deck Master profile UAT。

---

# Wave B — Intelligence & Human Review

# v1.7 Tasks

## 1.7-A — Asset/Revision/Lineage Schema

**目标：** 将 v1.5 identity 提升为正式 Asset/Revision model。

**必须实现：**

- slide/deck assets/revisions；
- lineage edge；
- classification values/suggestions；
- feedback/health tables；
- legacy adapters；
- migration 7。

**DoD：** authoritative、derived、suggested 数据明确分层。

---

## 1.7-B — Layout & Visual Fingerprints

**目标：** 提取结构和视觉指纹。

**依赖：** A。

**必须实现：**

- normalized boxes/type hierarchy；
- media/palette/font/master signals；
- pHash；
- algorithm version；
- cached artifacts；
- performance report。

**DoD：** fingerprint 可重算，不依赖路径。

---

## 1.7-C — Near Duplicate Classifier

**目标：** 多信号近重复和 client variant 分类。

**依赖：** A、B。

**必须实现：**

- blocking；
- scoring；
- safety rules；
- review queue；
- manual merge/split；
- metrics；
- false merge guard。

**DoD：** 达到 precision/recall gate；不自动删除。

---

## 1.7-D — Deck/Slide Lineage

**目标：** 自动和人工维护版本、复制、修改关系。

**依赖：** A、C。

**必须实现：**

- edge inference；
- direction；
- representative policy；
- manual confirm/reject；
- supersede；
- change summary；
- cycle validator。

**DoD：** manual override 100% 保持。

---

## 1.7-E — Classification & Suggestion Pipeline

**目标：** page archetype 等元数据具备 provenance。

**依赖：** A。

**必须实现：**

- label schema；
- deterministic + model suggestion；
- abstain；
- confidence；
- review state；
- import/export；
- classification benchmark。

**DoD：** model suggestion 不覆盖 manual approved。

---

## 1.7-F — Feedback Events & Ranking v2

**目标：** 完整事件和保守业务排序。

**依赖：** A、v1.6。

**必须实现：**

- event contract/idempotency；
- rejection reasons；
- aggregates；
- Bayesian shrinkage；
- context segments；
- demo isolation；
- score explanation；
- recompute。

**DoD：** 少量样本不能造成异常 boost。

---

## 1.7-G — Asset Health

**目标：** 健康扫描和 finding 生命周期。

**依赖：** C～F。

**必须实现：**

- detectors；
- severity；
- finding state；
- suggested action；
- resolve/rescan；
- report；
- policy hooks。

**DoD：** high severity 可被 selection hard filter。

---

## 1.7-H — Asset Pack & Release Gate

**目标：** 可迁移资产与完整 intelligence QA。

**必须实现：**

- export/import/dry-run；
- identity preserved；
- conflict report；
- hashes；
- round trip；
- release benchmark；
- docs。

---

# v1.8 Tasks

## 1.8-A — Application Service Completion

**目标：** 让 CLI/API/UI 共用服务。

**必须实现：**

- search/asset/review/health/job services；
- transaction boundaries；
- repository usage；
- error mapping；
- permission hook interface；
- no UI SQL。

---

## 1.8-B — Local API & Session Security

**目标：** `/api/v1`、localhost session、CSRF、revision token。

**依赖：** A。

**必须实现：**

- FastAPI app；
- health/status；
- session/bootstrap；
- CSRF/CSP；
- API envelope；
- optimistic concurrency；
- OpenAPI；
- API tests。

---

## 1.8-C — Workbench Shell & Dashboard

**依赖：** B。

**必须实现：**

- start/stop/status；
- packaged static/template；
- Dashboard actions；
- responsive/accessibility shell；
- provider/job/quality widgets；
- empty/degraded states。

---

## 1.8-D — Search & Asset Detail

**依赖：** B、C。

**必须实现：**

- filters/profile/explain；
- preview；
- version expand；
- asset metadata/review/feedback/health；
- keyboard；
- pagination/lazy load。

---

## 1.8-E — Duplicate & Version Review

**依赖：** B、C。

**必须实现：**

- visual/text/layout compare；
- merge/split/client variant；
- representative；
- lineage edit；
- impact preview；
- audit。

---

## 1.8-F — Health & Job Monitor

**依赖：** B、C。

**必须实现：**

- findings queue；
- resolve/rescan；
- job progress；
- retry/cancel；
- SSE；
- provider diagnostics。

---

## 1.8-G — Batch, Audit & Accessibility

**依赖：** D～F。

**必须实现：**

- safe batch actions；
- local audit；
- bulk validation；
- WCAG critical flows；
- revision conflict UX；
- export review pack。

---

## 1.8-H — Packaging, Browser E2E & Release

**依赖：** A～G。

**必须实现：**

- optional extra；
- wheel assets；
- Playwright；
- security tests；
- 50k performance；
- no-workbench install regression；
- docs。

---

# Wave C — Team & GA

# v1.9 Tasks

## 1.9-A — Repository Interfaces & Postgres

**目标：** 同一领域行为运行在 SQLite/Postgres。

**必须实现：**

- repository protocols；
- Postgres implementation；
- migrations；
- transaction/idempotency；
- pagination；
- repository contract suite。

---

## 1.9-B — Object & Vector Storage Adapters

**依赖：** A。

**必须实现：**

- blob interface；
- local/S3-compatible；
- opaque keys；
- signed URLs；
- pgvector/external interface；
- workspace scope；
- lifecycle。

---

## 1.9-C — Queue, Worker & Leases

**依赖：** A、B。

**必须实现：**

- DB queue；
- SKIP LOCKED/lease；
- heartbeat/reclaim；
- capabilities；
- retry/cancel；
- quotas；
- worker metrics；
- staging commit。

---

## 1.9-D — Users, RBAC & Tokens Preview

**依赖：** A。

**必须实现：**

- user/role/permission；
- admin bootstrap；
- session/token；
- permission middleware；
- service account；
- revoke；
- tests。

---

## 1.9-E — Audit, Secrets & Server Security

**依赖：** D。

**必须实现：**

- immutable audit；
- before/after hashes；
- secret references；
- redaction；
- SSRF/CORS/CSRF/rate limit；
- non-root container；
- security test suite。

---

## 1.9-F — Local-to-Server Migration

**依赖：** A、B。

**必须实现：**

- encrypted transfer pack；
- dry-run；
- identity preservation；
- staged blobs；
- journal；
- resume/rollback；
- conflict report。

---

## 1.9-G — Connector SDK Preview

**依赖：** C、E。

**必须实现：**

- connector protocol；
- change cursor；
- revision；
- tombstone；
- permission snapshot；
- local/NAS + generic reference；
- test harness。

---

## 1.9-H — Deploy, Backup, Observability & Load

**依赖：** A～G。

**必须实现：**

- Docker Compose；
- readiness/liveness；
- metrics/logs；
- backup/restore；
- 250k load；
- worker/DB/storage failure；
- operator docs；
- Preview release gate。

---

# v2.0 Tasks

## 2.0-A — Organization & Workspace Isolation

**目标：** 多 Workspace 严格隔离。

**必须实现：**

- organization/workspace schema；
- scope middleware；
- metadata/vector/blob/cache/audit isolation；
- cross-workspace tests；
- per-workspace backup/export。

---

## 2.0-B — OIDC & Identity Lifecycle

**依赖：** A。

**必须实现：**

- OIDC PKCE；
- discovery/JWKS；
- JIT；
- role mapping；
- disable/logout；
- service account；
- break-glass；
- security tests。

---

## 2.0-C — Policy Engine

**依赖：** A、B。

**必须实现：**

- policy schema；
- egress/confidentiality/export/retention/connector；
- backend enforcement hooks；
- decision explanation；
- policy test matrix；
- deny by default for unknown high risk。

---

## 2.0-D — Approval, Promotion & Shared Library

**依赖：** A、C。

**必须实现：**

- review request；
- approval/reject/revoke；
- promotion；
- health/policy gates；
- shared visibility；
- lineage preserved；
- expiry；
- audit。

---

## 2.0-E — Connector SDK GA & References

**依赖：** A、C。

**必须实现：**

- stable SDK；
- two reference enterprise connectors；
- incremental sync；
- permission changes；
- rate limit；
- secrets；
- docs/examples；
- compatibility tests。

---

## 2.0-F — Analytics & Audit Export

**依赖：** A、D。

**必须实现：**

- aggregate metrics；
- role restrictions；
- no content leakage；
- audit export；
- retention；
- dashboard；
- query/reuse/health/policy metrics。

---

## 2.0-G — Deployment, Upgrade & DR

**依赖：** A～F。

**必须实现：**

- Compose GA；
- Helm reference；
- external services；
- rolling upgrade；
- rollback；
- backup/restore；
- capacity tiers；
- operational runbooks；
- failure drills。

---

## 2.0-H — API/SDK Freeze, Security & GA Gate

**依赖：** A～G。

**必须完成：**

- REST API diff；
- CLI compatibility；
- Python SDK；
- Contract freeze；
- search/intelligence benchmark；
- 500k load；
- OIDC/RBAC/Policy；
- independent security review；
- SBOM/attestation；
- docs/support policy；
- GA sign-off。

---

# 14. PR Review Checklist for Every Task

Reviewer 必须确认：

```text
[ ] Scope 与 Task ID 一致
[ ] 未引入隐藏 breaking change
[ ] Contract/Schema 有版本
[ ] Migration 有 backup/verify/recovery
[ ] 错误不是 generic INTERNAL_ERROR-only
[ ] stdout JSON 稳定
[ ] secrets/content 不进日志
[ ] long task 可诊断
[ ] tests 覆盖失败路径
[ ] benchmark delta 可解释
[ ] docs 已更新
[ ] known limitations 真实
```

---

# 15. 标准 Agent Prompt

```text
你正在开发 MainQuestAI/PPT-Library。

基线：
- 先核验当前 origin/main、VERSION、SCHEMA_VERSION、CLI schema 和全量测试。
- 阅读 docs/specs/v1.5-v2.0/README.md、00-master-program-spec.md、
  对应版本 Spec，以及 13-agent-execution-task-pack.md。

本次只实现：<TASK_ID> <TASK_NAME>

目标：
<copy task goal>

允许修改：
<verified paths>

禁止：
- 扩展到其他 Task；
- 破坏现有 CLI；
- 用数据库 row id 作为跨系统稳定身份；
- 写入真实客户资产；
- 静默 fallback；
- 未测试迁移覆盖原库。

必须交付：
- 代码与文档；
- unit/integration/failure tests；
- 真实执行结果；
- migration/rollback；
- contract/benchmark delta；
- security impact；
- known limitations。

完成后输出：
1. 已确认事实；
2. 修改文件；
3. 设计决策；
4. 测试及结果；
5. Benchmark；
6. 风险与遗留项。
```
