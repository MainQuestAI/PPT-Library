# 01 — 产品边界与目标架构

---

## 1. 设计结论

PPT Library v2.0 应采用**双模、同核、端口适配器架构**：

```text
                    ┌─────────────────────────┐
                    │ CLI / Agent / Workbench │
                    │ REST API / Python SDK   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Application Services   │
                    │ ingest/search/review/... │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │ Domain: Asset / Revision / Family   │
              │ Lineage / Feedback / Policy / Job   │
              └──────────────────┬──────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │ Repository / Provider    │
                    │ Interfaces               │
                    └───────┬─────────┬───────┘
                            │         │
              ┌─────────────▼──┐   ┌──▼────────────────┐
              │ Local Mode      │   │ Team Server Mode  │
              │ SQLite + Files  │   │ Postgres + Object │
              │ Local ANN       │   │ Store + Vector    │
              └─────────────────┘   └───────────────────┘
```

同一业务逻辑不得在 CLI、Workbench 和 Server API 中各实现一遍。

---

## 2. 建议代码结构

### 2.1 渐进新增结构

```text
ppt_lib/
├── cli.py                         # 保留兼容入口
├── contracts/
│   ├── registry.py
│   ├── envelope.py
│   ├── deck_master.py
│   └── schemas/
├── services/
│   ├── ingest_service.py
│   ├── search_service.py
│   ├── selection_service.py
│   ├── review_service.py
│   ├── feedback_service.py
│   └── migration_service.py
├── identity/
│   ├── fingerprints.py
│   ├── registry.py
│   └── lineage_matcher.py
├── jobs/
│   ├── model.py
│   ├── runner.py
│   ├── checkpoint.py
│   ├── writer.py
│   └── events.py
├── retrieval/
│   ├── lexical.py
│   ├── vector.py
│   ├── fusion.py
│   ├── reranker.py
│   ├── filters.py
│   └── profiles.py
├── intelligence/
│   ├── duplicates.py
│   ├── versions.py
│   ├── classification.py
│   ├── health.py
│   └── ranking.py
├── repositories/
│   ├── protocols.py
│   ├── sqlite/
│   └── postgres/                 # v1.9+
├── api/                          # v1.8+
├── workbench/                    # v1.8+
├── server/                       # v1.9+
└── providers/
    ├── embedding/
    ├── vision/
    ├── rerank/
    └── storage/
```

### 2.2 现有模块处理原则

- `db.py`、`indexer.py`、`searcher.py`、`versioning.py` 等不在 v1.5 一次性删除；
- 新 service 可以调用旧模块，再逐步把逻辑下沉到新 domain/repository；
- CLI 先切到 service 层；
- 每次迁移一个能力时增加行为等价测试；
- v2.0 前允许保留兼容 wrapper；
- 删除旧模块必须经过一个 minor 版本 deprecation。

---

## 3. 领域模型

### 3.1 Source

代表资料来源，不等同于路径。

```text
Source
- source_id
- workspace_id
- source_type: local_folder | local_file | connector
- locator
- display_name
- policy
- scan_state
- created_at / updated_at
```

### 3.2 Deck Asset 与 Deck Revision

```text
DeckAsset
- deck_asset_id             # 逻辑 Deck
- family_id
- title
- project / client / industry
- governance_state

DeckRevision
- deck_revision_id          # 具体内容版本
- deck_asset_id
- source_locator
- package_fingerprint
- revision_label
- created_at / indexed_at
```

### 3.3 Slide Asset 与 Slide Revision

```text
SlideAsset
- canonical_asset_id        # 逻辑可复用页面
- preferred_revision_id
- review_state
- confidentiality
- business metadata

SlideRevision
- slide_revision_id         # 确定内容版本
- canonical_asset_id
- deck_revision_id
- page_number
- text_fingerprint
- visual_fingerprint
- structure_fingerprint
- rendered_asset
- extracted content
```

### 3.4 Lineage

```text
LineageEdge
- from_revision_id
- to_revision_id
- relation:
  copied | modified | derived | supersedes | same_visual | same_text
- confidence
- evidence
- review_status
```

### 3.5 Job

```text
Job
- job_id
- job_type
- idempotency_key
- state
- stage
- progress
- checkpoint
- attempts
- config_hash
- provider_versions
- errors / warnings
- timestamps
```

### 3.6 Feedback Event

```text
FeedbackEvent
- event_id
- idempotency_key
- canonical_asset_id / revision_id
- context
- event_type
- actor
- source_system
- metadata
- occurred_at
```

---

## 4. 运行模式

### 4.1 Local Mode

默认模式，适用于个人和小团队单机：

- SQLite；
- 本地截图和导出目录；
- 本地 FTS5；
- 本地 ANN 或 NumPy fallback；
- 本地 Workbench；
- 无账户体系；
- 模型 Provider 可本地或云端；
- 所有数据默认不离开设备。

### 4.2 Team Server Mode

v1.9 起提供 Preview，v2.0 GA：

- Postgres；
- S3-compatible Object Store；
- 可插拔 Vector Backend；
- API/Worker 分离；
- 多用户；
- RBAC/Audit；
- OIDC；
- Workspace policy；
- 备份和恢复；
- Docker Compose 为最小参考部署。

### 4.3 Embedded/Agent Mode

面向 Deck Master 和其他 Agent：

- 优先使用 CLI Contract；
- 可选本地进程调用；
- `capabilities` 做功能协商；
- 不依赖 UI；
- 不允许解析人类文本判断成功；
- 必须读取 JSON `_errors`、warnings 和 fallback 状态。

---

## 5. 数据存储抽象

### 5.1 Metadata Repository

协议至少包含：

```python
class AssetRepository(Protocol):
    def get_slide_revision(...)
    def upsert_slide_revision(...)
    def assign_canonical_asset(...)
    def list_search_documents(...)
    def record_feedback(...)
    def begin_transaction(...)
```

Local 实现可继续使用 `sqlite3`，不要求立即引入 ORM。

### 5.2 Blob Store

用于：

- screenshots；
- OCR markdown；
- preview HTML；
- review-pack；
- exported asset pack；
- benchmark artifacts。

接口：

```text
put
get
exists
delete
list
signed_url (server only)
content_hash
```

### 5.3 Vector Backend

```text
sqlite_scan        # compatibility / small
local_hnsw         # v1.6 default for large local
remote_vector      # v1.9+ optional
```

所有 backend 必须返回统一 candidate 结构，并能报告：

- backend_name；
- index_version；
- embedding_model；
- dimensions；
- build_state；
- fallback_reason。

---

## 6. Provider 架构

Embedding、Vision/OCR、LLM Annotation、Rerank 均采用相同生命周期：

```text
configure
→ capabilities
→ health probe
→ execute
→ structured result
→ usage/cost metadata
→ structured error
```

每个 Provider 必须声明：

- 是否会外发数据；
- 支持的最大输入；
- 模型/version；
- timeout；
- retry policy；
- concurrency；
- deterministic level；
- data retention note。

默认不得将 token 写入 `config.yml`。

---

## 7. Workbench 架构

v1.8 推荐：

- FastAPI/Starlette；
- Jinja2 + HTMX，避免要求最终用户安装 Node；
- 前端静态资源随 wheel 打包；
- `127.0.0.1` 默认绑定；
- one-time local session token；
- 所有写操作调用 Application Service；
- API 路径 `/api/v1`；
- 资源更新使用 `revision_token` 防止覆盖并发修改。

核心页面：

```text
Dashboard
Search
Asset Detail
Version Family
Duplicate Review
Key Page Review
Health Review
Job Monitor
Settings / Provider Diagnostics
```

---

## 8. Team Server 架构

v1.9 Preview：

```text
reverse proxy
    ↓
api service
    ↓
application services
    ↓
postgres / object store / vector backend
    ↑
worker service
```

v2.0 增加：

- org/workspace；
- OIDC；
- policy engine；
- approval workflow；
- connector workers；
- audit export；
- observability stack；
- deployment charts。

---

## 9. 与 Deck Master 的集成边界

### 9.1 调用输入

Deck Master 应传入：

- `run_id`
- `page_task_id`
- `slot_id`
- `query_trace_id`
- query/brief
- page role/archetype
- industry/scenario
- evidence need
- filters
- max candidates

### 9.2 返回输出

PPT Library 返回：

- canonical/revision identity；
- title/summary；
- source provenance；
- screenshot/preview；
- score 与分项；
- duplicate/version 状态；
- confidentiality/health warnings；
- selection explanation；
- contract/schema/producer version。

### 9.3 不返回

- 最终页面是否应使用；
- Deck 中的最终位置；
- 完整叙事是否正确；
- 最终客户版交付结论。

---

## 10. 架构验收

- CLI、Workbench、API 对同一输入返回一致领域结果；
- Local/Server Repository contract tests 共用；
- 所有 Provider 有 capability 和 health probe；
- 任何 backend 替换不改变上层 Contract；
- 现有 v1.4.1 核心 CLI 在 v1.x 保持兼容；
- 无 UI 代码直接执行 SQL；
- 无业务模块直接读取环境变量；
- 所有长任务经过 Job Runner；
- 所有资产引用使用 canonical/revision identity，不以 row id 作为跨系统主键。
