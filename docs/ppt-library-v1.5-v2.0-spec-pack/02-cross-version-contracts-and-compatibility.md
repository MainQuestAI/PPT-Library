# 02 — 跨版本 Contract、CLI 与兼容策略

---

## 1. Contract 原则

1. JSON Shape 必须有明确名称，不只使用模糊的 `schema_version=1.0`。
2. Contract 和数据库 Schema 独立版本化。
3. 跨仓库 Contract 由 JSON Schema 验证。
4. Contract 字段只增不改；删除或语义变化必须升 major。
5. 机器输出不得混入日志。
6. error/warning/fallback 必须可区分。
7. 路径字段不得作为稳定身份。
8. Contract 测试必须使用真实 CLI 子进程执行。

---

## 2. Envelope v2

建议新增：

```json
{
  "_meta": {
    "envelope": "ppt_library.envelope.v2",
    "contract": "ppt_library.search_response.v2",
    "contract_version": "2.0.0",
    "producer": "ppt-library",
    "producer_version": "1.6.0",
    "command": "search",
    "request_id": "req_...",
    "run_id": null,
    "generated_at": "2026-06-23T00:00:00Z",
    "duration_ms": 123
  },
  "data": {},
  "_warnings": [],
  "_errors": []
}
```

### 2.1 Error

```json
{
  "code": "SEARCH_BACKEND_UNAVAILABLE",
  "message": "Local ANN index is unavailable.",
  "module": "retrieval.vector",
  "severity": "error",
  "retryable": true,
  "stage": "vector_recall",
  "details": {},
  "cause_chain": []
}
```

### 2.2 Warning

```json
{
  "code": "SEARCH_FALLBACK_SQLITE_SCAN",
  "message": "ANN index unavailable; used SQLite scan.",
  "module": "retrieval",
  "severity": "warning",
  "fallback": {
    "from": "local_hnsw",
    "to": "sqlite_scan"
  }
}
```

---

## 3. 1.x 兼容政策

### 3.1 默认输出

- v1.5～v1.9：保留当前 CLI 默认 JSON envelope；
- 新的稳定 Contract 通过 `--contract <name>` 或专用命令启用；
- 机器集成必须显式指定 Contract；
- v2.0：Envelope v2 成为新命令默认值；
- legacy v1 contract 至少保留到 v2.1。

### 3.2 CLI

以下命令和核心参数在 v1.x 不得破坏：

```text
setup
init
doctor
sources
index
search
status
versions
assets
insights
record-deal
record-usage
select-slides
assemble
compose
schema
```

可以：

- 增加参数；
- 增加子命令；
- 修正明确 Bug；
- 为旧行为增加 warning。

不可以：

- 改变字段含义但不升 Contract；
- 在相同参数下静默改变成功/失败语义；
- 删除当前命令；
- 把 stderr 日志写入 stdout JSON。

---

## 4. Capability Contract

新增命令：

```bash
ppt-lib capabilities --output json
```

最少返回：

```json
{
  "contract": "ppt_library.capabilities.v1",
  "producer_version": "1.5.0",
  "modes": ["local"],
  "features": {
    "index.resume": true,
    "search.hybrid_v2": false,
    "selection.deck_master_v1": true,
    "workbench": false,
    "server_mode": false
  },
  "contracts": [
    "deck_master_ppt_library_selection.v1",
    "ppt_library.search_response.v2"
  ],
  "providers": {
    "embedding": [],
    "vision": [],
    "rerank": []
  },
  "storage": {
    "metadata": ["sqlite"],
    "vector": ["sqlite_scan"]
  }
}
```

Deck Master 必须先读取 capability，再决定是否启用某一功能。

---

## 5. Deck Master Selection Contract

v1.5 原生支持：

```bash
ppt-lib select-slides \
  --plan narrative-plan.json \
  --brief "..." \
  --contract deck-master.v1 \
  --run-id <run_id> \
  --output selection.json
```

输出顶层：

```json
{
  "schema_version": "deck_master_ppt_library_selection.v1",
  "run_id": "run_...",
  "source": "ppt-library",
  "producer_version": "1.5.0",
  "selections": []
}
```

每个 selection：

```json
{
  "beat_id": "beat_01",
  "page_task_id": "page_01",
  "slot_id": "main_visual",
  "query_trace_id": "qry_...",
  "role": "architecture",
  "candidates": []
}
```

候选最少字段：

```text
candidate_id
canonical_asset_id
slide_revision_id
slide_id                  # legacy local id, optional externally
title
text_summary
source_file               # local only
source_locator
page_number
screenshot_path
preview_uri
confidence
score
score_breakdown
narrative_role
page_role
page_archetype
importance_reason
duplicate_count
deck_family_id
version_role
is_representative_version
health_warnings
confidentiality
candidate_origin
library_source
```

### 5.1 Run Binding

- `run_id` 必填；
- 输出文件若已存在且 run_id 不同，拒绝覆盖；
- `query_trace_id` 必须唯一；
- 同一请求重跑必须支持 idempotency key；
- Contract validator 必须在写文件前执行。

---

## 6. Search Request/Response v2

### 6.1 Request

```json
{
  "contract": "ppt_library.search_request.v2",
  "request_id": "req_...",
  "query": "汽车行业 AI 搜索平台架构",
  "top_k": 10,
  "search_profile": "balanced",
  "filters": {
    "industry": ["automotive"],
    "page_role": ["architecture"],
    "review_state": ["approved"],
    "include_versions": false
  },
  "context": {
    "scenario": "proposal",
    "audience": "executive"
  },
  "explain": true
}
```

### 6.2 Response Candidate

```json
{
  "candidate_id": "cand_...",
  "canonical_asset_id": "asset_...",
  "slide_revision_id": "srev_...",
  "title": "...",
  "summary": "...",
  "score": 0.87,
  "score_breakdown": {
    "lexical": 0.76,
    "semantic": 0.91,
    "rerank": 0.88,
    "business": 0.10,
    "context": 0.05,
    "health_penalty": -0.03
  },
  "provenance": {},
  "warnings": []
}
```

---

## 7. Job Contract

Job 状态：

```text
queued
running
paused
cancelling
cancelled
completed
completed_with_warnings
failed
```

Stage：

```text
discover
extract
render
recognize
embed
stage
commit
govern
finalize
```

接口：

```bash
ppt-lib jobs list
ppt-lib jobs inspect <job-id>
ppt-lib jobs cancel <job-id>
ppt-lib jobs resume <job-id>
ppt-lib jobs retry <job-id>
```

Job 必须暴露：

- idempotency key；
- current stage；
- completed units / total units；
- checkpoint；
- error list；
- provider version；
- config hash；
- source hash；
- timestamps。

---

## 8. Event Contract

事件采用 append-only JSONL 或事件表：

```json
{
  "event_version": "ppt_library.event.v1",
  "event_id": "evt_...",
  "event_type": "job.stage.completed",
  "occurred_at": "...",
  "actor": {"type": "system", "id": "local"},
  "workspace_id": "local",
  "job_id": "job_...",
  "asset_id": null,
  "request_id": null,
  "payload": {}
}
```

要求：

- event_id 唯一；
- 写入失败不得阻塞主事务提交，但必须记录 degraded warning；
- Team Mode 审计事件与运行事件分开；
- event payload 不写入密钥和大段客户正文。

---

## 9. Python API

v1.x 不承诺所有内部模块为稳定 SDK。仅以下接口可逐步标记稳定：

```python
from ppt_lib.application import (
    IngestService,
    SearchService,
    SelectionService,
)
from ppt_lib.contracts import validate_contract
```

v2.0 才正式发布 Python SDK 支持政策。

---

## 10. Schema Registry

建议仓库新增：

```text
ppt_lib/contracts/schemas/
docs/contracts/
```

每个 Contract 包含：

- JSON Schema；
- valid example；
- invalid examples；
- changelog；
- owner；
- compatibility notes；
- unit test；
- CLI subprocess test。

新增：

```bash
ppt-lib contract list
ppt-lib contract show <name>
ppt-lib contract validate <name> <file>
```

---

## 11. 弃用政策

弃用必须：

1. 在 release notes 声明；
2. CLI stderr 输出一次 warning；
3. Contract capability 标记 deprecated；
4. 至少跨一个 minor 版本；
5. 提供迁移说明；
6. 有测试确保旧入口仍可运行；
7. v2.0 删除 1.x 行为时提供 `--contract legacy.v1`。

---

## 12. Contract 验收

- 所有 schema 通过 Draft 2020-12 validator；
- Deck Master canonical schema 与本仓库 vendored schema SHA 一致；
- valid examples 全部通过；
- invalid examples 全部失败且错误码正确；
- stdout 可被单次 `json.loads`；
- 非零 exit code 与 `_errors.severity=error` 一致；
- Contract UAT 在 CI 中对真实 CLI 子进程执行；
- 不允许测试只调用 Python 内部函数绕过 CLI。
