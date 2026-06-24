# PPT Library v1.5～v2.0 完整迭代 Spec Pack（合并版）
> 该文件由拆分版 Spec 自动合并。实际执行优先按拆分文件和 Task ID 工作。


---

<!-- SOURCE: README.md -->

# PPT Library v1.5～v2.0 完整迭代 Spec Pack

**项目：** `MainQuestAI/PPT-Library`
**规划范围：** v1.5.0 ～ v2.0.0
**基线：** 公开仓库默认分支在 2026-06-23 检查时呈现为 v1.4.1；当前包按该公开代码结构设计。
**状态：** PROPOSED / IMPLEMENTATION-READY AFTER BASELINE VERIFICATION
**目标读者：** 项目 Owner、Tech Lead、Codex、Claude Code、OpenCode、代码评审 Agent、QA Agent

> 本包不是方向性 Roadmap，而是连续开发合同。每个版本均包含目标、非目标、架构边界、数据契约、CLI/API、迁移、错误处理、测试、发布门禁和 Agent 任务拆分。

---

## 1. 使用前必须做的基线核验

公开仓库事实可能在本包生成后继续变化。执行任何开发前，Codex 必须在真实仓库中完成：

```bash
git fetch origin
git checkout main
git pull --ff-only
git rev-parse HEAD
cat VERSION
grep '^version' pyproject.toml
uv sync --extra test --extra lint
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run python scripts/release_check.py --output json
uv build
```

并输出：

1. 当前 HEAD、版本号、数据库 `SCHEMA_VERSION`；
2. 当前测试数量与结果；
3. 当前 CLI Schema；
4. 当前已有但本包未识别的能力；
5. 与本包发生冲突的路径或契约；
6. 建议调整后的实施基线。

**未经上述核验，不得把本文档中的“建议路径”直接当作当前仓库事实。**

---

## 2. 总体判断

v1.5～v2.0 应作为一个连续大轮次实施，分为三个 Wave：

| Wave | 版本 | 业务目标 |
|---|---|---|
| Wave A：生产基础 | v1.5、v1.6 | 从功能 Beta 进入可靠、可度量的本地生产版本 |
| Wave B：资产智能 | v1.7、v1.8 | 从搜索工具进入可治理、可审查、可学习的 Asset Intelligence 产品 |
| Wave C：团队化与 GA | v1.9、v2.0 | 从个人本地工具进入可部署、可治理的团队/企业双模产品 |

版本之间不是六个相互独立的功能包。后续版本必须继承前序版本的稳定契约和质量门，禁止通过旁路实现绕开底层能力。

---

## 3. 文档索引

| 文件 | 用途 |
|---|---|
| `00-master-program-spec.md` | 总目标、版本地图、产品成熟度跃迁和全局成功标准 |
| `01-product-boundaries-and-target-architecture.md` | 三项目边界、目标架构、模块和部署模式 |
| `02-cross-version-contracts-and-compatibility.md` | JSON Contract、CLI、错误、事件、兼容策略 |
| `03-v1.5-production-core-and-contract-closure.md` | v1.5 完整实施 Spec |
| `04-v1.6-search-quality-and-benchmark.md` | v1.6 完整实施 Spec |
| `05-v1.7-asset-intelligence-and-lineage.md` | v1.7 完整实施 Spec |
| `06-v1.8-local-review-workbench.md` | v1.8 完整实施 Spec |
| `07-v1.9-team-preview-and-operations.md` | v1.9 完整实施 Spec |
| `08-v2.0-team-enterprise-ga.md` | v2.0 完整实施 Spec |
| `09-data-schema-migrations-and-identity.md` | 数据模型、稳定身份、Schema Migration |
| `10-benchmark-quality-gates-and-test-matrix.md` | Benchmark、质量门、测试矩阵 |
| `11-security-privacy-and-governance.md` | 本地隐私、模型外发、安全和企业治理 |
| `12-release-rollout-and-backward-compatibility.md` | 发布、灰度、回滚和支持策略 |
| `13-agent-execution-task-pack.md` | 可直接分配给开发 Agent 的任务包 |
| `14-risk-register-and-decision-log.md` | 风险清单与必须形成 ADR 的决策 |
| `15-definition-of-done-and-acceptance-checklists.md` | 版本 DoD 和最终验收清单 |
| `contracts/` | 建议新增的 JSON Schema 草案 |
| `examples/` | Contract 示例 |
| `ppt-library-v1.5-v2.0-complete-spec.md` | 全部正文合并版 |
| `MANIFEST.json` | 文件清单和 SHA-256 |

---

## 4. 执行原则

1. **先稳定身份与契约，再提升检索，再做 UI，再做团队化。**
2. **不做 Big Bang 重构。** 现有 CLI 和模块先保留，通过新增 service/repository 层渐进迁移。
3. **默认 local-first。** 团队 Server Mode 是可选部署形态，不反向破坏个人本地模式。
4. **搜索质量必须有数据。** 测试数量不能替代 Retrieval Benchmark。
5. **PPT Library 不扩张为第二个 Deck Master。** 它提供资产与候选，不承担完整方案叙事生产。
6. **所有长期任务必须可恢复、可取消、可追踪、可重放。**
7. **所有机器契约必须版本化。**
8. **所有迁移必须先备份、可验证、失败不覆盖原库。**
9. **真实客户资产不得进入公开仓库、公开 benchmark 或日志样例。**
10. **每个 PR 只实施明确任务包，不跨版本顺手扩 Scope。**

---

## 5. 推荐仓库存放位置

合并进仓库时建议放置：

```text
docs/specs/v1.5-v2.0/
├── README.md
├── 00-master-program-spec.md
├── ...
├── 15-definition-of-done-and-acceptance-checklists.md
├── contracts/
└── examples/
```

主 README 只增加入口链接，不复制全部正文。

---

## 6. 最终产品定义

到 v2.0，PPT Library 应成为：

> **一个 local-first、agent-native、human-governed、team-capable 的 PPT Asset Intelligence System：能够可靠摄取、理解、检索、治理、审查、追踪和复用历史幻灯片资产，并通过稳定契约为 Deck Master 等上层生产系统提供高质量候选。**

它不是：

- 全功能 PPT 编辑器；
- 完整 Narrative/Proposal Authoring OS；
- 云端模型代理平台；
- 无约束扫描用户整台电脑的工具；
- 仅凭向量相似度返回页面的普通 RAG Demo。


---

<!-- SOURCE: CODEX-START-HERE.md -->

# Codex Start Here

## 1. 第一个任务

先执行 `1.5-A — Baseline Verification & ADR Pack`，不要直接开始 Job Engine 或 UI。

## 2. 核验命令

```bash
git fetch origin
git checkout main
git pull --ff-only
git rev-parse HEAD
cat VERSION
grep '^version' pyproject.toml
grep -R 'SCHEMA_VERSION' -n ppt_lib
uv sync --extra test --extra lint
uv run --extra test pytest
uv run --extra lint ruff check .
uv run --extra lint mypy
uv run ppt-lib schema --output json
uv run python scripts/release_check.py --output json
uv build
```

## 3. 必须输出的基线报告

```text
- HEAD
- version
- DB schema
- commands
- modules
- test baseline/result
- current migrations
- current release blockers
- current Deck Master contract shape
- Spec conflicts
- accepted ADR list
```

## 4. 开发顺序

```text
1.5-A → 1.5-B → 1.5-C
     ↘ 1.5-D → 1.5-E → 1.5-F
                    ↘ 1.5-G
                         ↓
                       1.5-H
```

v1.5 完成质量门后才能开始 v1.6 默认检索替换。

## 5. 开发边界

- 不做 Big Bang 目录重构；
- 不改变三项目边界；
- 不把 DB row id 作为跨系统主键；
- 不用新 UI 掩盖底层能力；
- 不提交真实 PPT/截图/数据库；
- 不宣称未实测的平台支持；
- 不静默 fallback；
- 不在 migration 失败后继续写入。

## 6. 标准任务 Prompt

请复制 `13-agent-execution-task-pack.md` 末尾模板，并填入唯一 Task ID。


---

<!-- SOURCE: 00-master-program-spec.md -->

# 00 — PPT Library v1.5～v2.0 总体开发 Spec

**Status:** PROPOSED
**Baseline:** v1.4.1 public main, requires Codex verification
**Program:** Production Core → Search Quality → Asset Intelligence → Review Workbench → Team Preview → Enterprise GA

---

## 1. 背景与问题定义

当前版本已经具备本地资料源管理、PPTX 文本抽取、截图、OCR/视觉识别、embedding、页级检索、版本治理、重点页识别、复用追踪、自动组装和 Agent JSON 输出等能力。它已经跨过原型阶段，但仍存在六个结构性缺口：

1. **接口缺口：** 与 Deck Master 等上层系统仍依赖适配器重组结果，PPT Library 不能原生输出对方所需的 versioned contract。
2. **身份缺口：** SQLite row id 和文件路径不是稳定资产身份，文件移动、重建库和跨环境迁移会破坏引用。
3. **运行缺口：** 索引任务缺少完整 stage/checkpoint/cancel/resume 模型，多 worker 与 SQLite 全局治理存在扩展风险。
4. **质量缺口：** 已有检索评测代码，但真实质量没有成为发布硬门禁，搜索仍依赖内存全量向量扫描和固定权重。
5. **治理缺口：** 去重、版本归族、页面价值和业务排序仍以规则为主，人工反馈与资产生命周期不完整。
6. **产品缺口：** CLI 适合 Agent 和技术用户，但缺少人类资产审查工作台；团队模式、权限、审计和部署能力尚未闭合。

v1.5～v2.0 的任务不是继续堆命令，而是把上述能力收敛成稳定产品架构。

---

## 2. 产品北极星

### 2.1 核心价值

PPT Library 的核心价值函数定义为：

```text
Asset Value
= Discoverability
× Retrieval Relevance
× Reuse Readiness
× Governance Confidence
× Feedback Learning
```

任何新能力若不能提高其中至少一项，或不能降低使用成本、风险和运维成本，不进入主路线。

### 2.2 终局能力闭环

```text
Source Registration
→ Safe Discovery
→ Resumable Ingestion
→ Stable Identity
→ Text / Visual Understanding
→ Duplicate & Version Governance
→ Hybrid Retrieval
→ Human Review
→ Selection Contract
→ Usage / Outcome Feedback
→ Asset Health & Learning
```

### 2.3 目标用户

| 用户 | 核心任务 |
|---|---|
| 方案/售前专家 | 找到可复用页面，判断来源和风险 |
| 咨询与提案团队 | 治理多年历史 Deck 和高价值页面 |
| AI Agent | 通过稳定 JSON Contract 检索、选择、解释候选 |
| 资产管理员 | 审查重复、版本、标签、过期和保密状态 |
| 团队负责人 | 观察资产利用率、检索质量和复用结果 |
| 企业 IT/安全 | 部署、权限、审计、备份和数据边界治理 |

---

## 3. 产品边界

### 3.1 PPT Library 负责

- PPT/PPTX 资产摄取与注册；
- Slide/Deck 稳定身份；
- 文本、视觉、结构和元数据理解；
- 搜索、过滤、解释和候选排序；
- 重复、近重复、版本与血缘；
- 人工标签、审批和反馈；
- 资产健康、生命周期与可复用性；
- 向上层系统提供 versioned selection contract；
- 轻量组装作为独立使用的 convenience path。

### 3.2 不负责

- 客户需求理解与 Claim Map；
- 完整 Deck Narrative Planning；
- 页面文案生成；
- 高保真版式编辑和品牌模板应用；
- 最终投标/汇报交付质量裁决；
- 代替 Deck Master 的 Run OS；
- 代替 PPT Deck Pro Max 的编辑和渲染引擎。

### 3.3 三项目责任模型

```text
PPT Library
  回答：有哪些可信、可复用的历史资产？

Deck Master
  回答：为什么用、是否用、放在哪里、如何形成完整方案？

PPT Deck Pro Max
  回答：如何编辑、修复、套版并高保真输出？
```

---

## 4. 版本地图

| 版本 | 主题 | 成熟度跃迁 | 强制产出 |
|---|---|---|---|
| v1.5 | Production Core & Contract Closure | Functional Beta → Reliable Local Beta | 稳定契约、资产身份、可恢复索引、增量治理、发布工程 |
| v1.6 | Search Quality & Benchmark | 有搜索 → 可度量检索产品 | Hybrid Retrieval v2、ANN、RRF、Rerank、Benchmark Gate |
| v1.7 | Asset Intelligence & Lineage | 检索工具 → 资产智能系统 | Near Duplicate、Lineage、Feedback、Health、Ranking v2 |
| v1.8 | Local Review Workbench | 技术工具 → 人机协作产品 | 本地 Web Workbench、审查、批量治理、任务监控 |
| v1.9 | Team Preview & Operations | 单机产品 → 单租户团队服务 | Server Mode、Postgres/Object Store、RBAC、Audit、DR |
| v2.0 | Team / Enterprise GA | Team Preview → 双模 GA 产品 | 多 Workspace、SSO、治理策略、审批、连接器、稳定 API/SDK |

---

## 5. Wave 划分及退出条件

### Wave A：v1.5 + v1.6

**目标：** 证明它是可靠、可集成、可度量的本地产品。

退出条件：

- Deck Master Contract UAT 100%；
- 10 万页规模存在可复跑性能报告；
- Recall@10、MRR、nDCG 达到发布门；
- 索引中断可恢复；
- 资产引用不依赖数据库 row id；
- macOS/Ubuntu Tier-1 安装通过，Windows 至少 Tier-2；
- 当前 CLI 关键链路不回归。

### Wave B：v1.7 + v1.8

**目标：** 证明它能把历史页面变成可持续经营的资产，而不仅是搜索结果。

退出条件：

- Near duplicate 和版本关系有人工标注集；
- 页面反馈能影响排序但不会被少量样本污染；
- 资产管理员可通过 Workbench 完成核心审查；
- 所有 UI 写操作经过 service layer；
- 关键资产状态和操作有可追踪历史；
- 无需直接编辑 SQLite。

### Wave C：v1.9 + v2.0

**目标：** 证明同一核心可同时支持个人本地和团队部署。

退出条件：

- Local Mode 与 Server Mode 契约一致；
- 单租户团队 Preview 经容量和故障测试；
- v2.0 完成多 Workspace、OIDC、RBAC、审计、备份和升级；
- API/CLI/Schema 进入明确兼容政策；
- 参考部署、运维手册和恢复演练齐备；
- 企业模式不破坏 local-first 产品定位。

---

## 6. 全局工程约束

### 6.1 不允许 Big Bang Rewrite

现有模块可以继续作为兼容入口。新增架构通过以下层次逐步引入：

```text
CLI / API / Workbench
        ↓
Application Services
        ↓
Domain Services
        ↓
Repository Interfaces
        ↓
SQLite / Postgres / File Assets / Vector Backend
```

v1.5 不得为了“目录漂亮”一次性移动全部现有模块。任何重命名必须有 import shim 和弃用测试。

### 6.2 契约优先

所有跨进程、跨仓库、跨版本的输出必须具备：

- `schema_version`
- `contract`
- `producer_version`
- `request_id` 或 `run_id`
- `generated_at`
- 结构化 errors/warnings
- JSON Schema
- 最少一份合法示例和非法示例
- Contract Test

### 6.3 任务优先

索引、OCR、embedding、版本治理、批量标注、导入和迁移均视为 Job，不再视为一个不可恢复的同步函数。

### 6.4 本地优先

- 默认数据留在用户本机；
- 模型外发必须显式配置；
- Workbench 默认只绑定 `127.0.0.1`；
- Team Mode 必须是可选 extra/deployment；
- 不得要求用户使用特定云向量数据库。

### 6.5 可观察性

从 v1.5 开始，关键流程统一写入结构化事件：

```text
job.created
job.stage.started
job.stage.completed
job.stage.failed
asset.created
asset.revision.created
search.executed
candidate.surfaced
review.recorded
feedback.recorded
migration.started
migration.completed
```

### 6.6 正确性优先于静默降级

- 配置明确指定 PaddleOCR MCP 时失败，不得无提示退化；
- Contract 不合法，不得输出“成功”；
- Schema migration 失败，不得继续使用半迁移数据库；
- 资产身份不确定时标记 `identity_status=needs_review`，不得强行合并；
- Search backend 不可用时必须暴露 fallback 状态。

---

## 7. 全局成功指标

### 7.1 可靠性

| 指标 | v1.5 | v1.9 | v2.0 |
|---|---:|---:|---:|
| 索引文件成功率（有效 PPTX） | ≥99% | ≥99.5% | ≥99.5% |
| 中断恢复成功率 | 100% 基准用例 | 100% | 100% |
| 幂等重跑重复记录 | 0 | 0 | 0 |
| Migration 数据丢失 | 0 | 0 | 0 |
| Contract UAT | 100% | 100% | 100% |

### 7.2 检索

| 指标 | v1.6 目标 | v2.0 目标 |
|---|---:|---:|
| Recall@10 | ≥0.85 | ≥0.88 |
| MRR | ≥0.65 | ≥0.70 |
| nDCG@10 | ≥0.75 | ≥0.80 |
| Top-5 人工可用率 | ≥70% | ≥75% |
| 重复候选比例 | ≤10% | ≤5% |

### 7.3 规模

| 模式 | 目标容量 |
|---|---|
| Local Small | 10k slides |
| Local Standard | 50k slides |
| Local Large | 100k slides |
| Team Preview | 250k slides / 20 concurrent users |
| Enterprise Reference | 500k slides / 50 concurrent users |
| Extended Reference | 1M slides，通过可插拔远程向量后端验证 |

### 7.4 业务效果

- 用户从查询到确认候选的中位时间显著下降；
- 高价值页面复用率可追踪；
- 被拒绝候选的原因可分类；
- 资产过期、重复和来源缺失可治理；
- Deck Master 可直接消费候选，不再依赖非正式字段推断。

---

## 8. 全局非目标

- 在 v1.5～v1.7 期间建设 SaaS；
- 把所有模型能力内置到仓库；
- 用复杂 UI 掩盖检索质量不足；
- 用赢单率直接推断单页因果价值；
- 自动删除重复或过期资产而无 dry-run/审批；
- 允许 Agent 无确认扫描 Home、Downloads 或聊天缓存；
- 把 compose 扩展为完整方案生成系统；
- 在 v2.0 前承诺多租户公网 SaaS 运维。

---

## 9. Program Definition of Done

v2.0 Program 只有在以下条件全部满足后才结束：

1. Local Mode 与 Team Mode 都有可复跑安装和升级路径；
2. 当前 v1.4.1 用户可迁移，无资产丢失；
3. Deck Master 原生 Contract 稳定；
4. 检索、去重、版本和索引均有 benchmark；
5. Workbench 可完成人工资产治理；
6. Team Mode 有 RBAC、审计、备份、恢复和 OIDC；
7. 发布包、SBOM、依赖扫描和文档齐全；
8. 公开示例不包含真实客户资产；
9. 所有 P0/P1 风险关闭或经 Owner 书面接受；
10. v2.0 发布说明明确兼容、已知限制和支持周期。


---

<!-- SOURCE: 01-product-boundaries-and-target-architecture.md -->

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


---

<!-- SOURCE: 02-cross-version-contracts-and-compatibility.md -->

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


---

<!-- SOURCE: 03-v1.5-production-core-and-contract-closure.md -->

# 03 — v1.5 Production Core & Contract Closure Spec

**Version:** 1.5.0
**Maturity Target:** Reliable Local Beta
**Primary Goal:** 把现有功能链路改造成可恢复、可迁移、可集成、可发布的稳定本地核心。
**Depends On:** v1.4.1 baseline verified
**Blocks:** v1.6、v1.8、v1.9

---

## 1. 版本结论

v1.5 不应增加大量“智能功能”。它必须优先关闭四个基础债务：

1. 与 Deck Master 的原生 Contract；
2. 路径和 row id 之外的稳定资产身份；
3. 可恢复、幂等、可取消的索引 Job；
4. 可验证的发布、迁移和跨平台基础。

完成 v1.5 后，PPT Library 才具备继续扩展检索和 UI 的稳定底座。

---

## 2. 目标

### G1 — Contract Closure

PPT Library 可以原生输出 `deck_master_ppt_library_selection.v1`，Deck Master 不再依赖非正式字段推断和二次拼装。

### G2 — Stable Identity

跨数据库重建、文件移动、导入导出和 Server Migration 时，能够稳定引用逻辑资产和具体 Revision。

### G3 — Resumable Ingestion

索引任务具备：

- stage；
- checkpoint；
- idempotency；
- cancel/resume/retry；
- 单写入事务；
- 结构化进度；
- 失败保留诊断。

### G4 — Incremental Governance

索引一个文件不得每次重建全部 duplicate group 和 deck family。

### G5 — Release-Ready Distribution

官方 wheel/sdist、安装 smoke、平台矩阵、迁移 smoke 和安全检查可复跑。

---

## 3. 非目标

- 不在 v1.5 引入完整 ANN 检索；
- 不做 Workbench；
- 不做 Postgres；
- 不重写全部数据库层；
- 不做多用户；
- 不提升复杂页面分类准确率；
- 不把 compose 扩展成完整 Deck 生产链；
- 不承诺 Windows LibreOffice 渲染为 Tier-1，除非真实 smoke 已通过。

---

## 4. 功能范围

## 4.1 Capability Negotiation

新增：

```bash
ppt-lib capabilities --output json
```

实现文件建议：

```text
ppt_lib/contracts/capabilities.py
ppt_lib/services/capability_service.py
tests/test_capabilities_cli.py
```

Capabilities 必须从真实运行环境生成，不能硬编码“可用”：

- CLI version；
- DB schema；
- configured providers；
- provider health；
- supported contracts；
- storage backend；
- optional extras；
- workbench/server availability；
- feature flags；
- degraded/fallback state。

### 验收

- 无模型环境也能返回 capability；
- provider 未配置时是 `available=false`，不是 error；
- schema 与示例一致；
- Deck Master 能根据 capability 判断 Contract 是否支持。

---

## 4.2 Deck Master Native Contract

新增参数：

```bash
ppt-lib select-slides \
  --contract deck-master.v1 \
  --run-id <run-id> \
  --plan <plan.json> \
  --output <selection.json>
```

可选：

```text
--page-task-id
--slot-id
--query-trace-id
--idempotency-key
```

### 输出要求

- 写文件前完成 schema validation；
- 临时文件写入后 atomic rename；
- run_id 不一致时拒绝覆盖；
- `_errors` 非空时不得产生假成功 selection；
- source paths 只在 local policy 允许时输出；
- 每个 candidate 必须包含 canonical identity 或明确的 `identity_status=legacy_unresolved`；
- score breakdown 必须说明 fallback；
- Contract 名称和 producer version 必须写入。

### 跨仓库同步

建议：

```text
contracts/vendor/deck-master/ppt-library-selection.v1.schema.json
contracts/vendor/deck-master/SOURCE.json
```

`SOURCE.json`：

```json
{
  "canonical_repo": "MainQuestAI/Deck-Master",
  "canonical_path": "docs/contracts/ppt-library-selection.v1.schema.json",
  "canonical_sha256": "...",
  "synced_at": "..."
}
```

新增 CI：

```bash
python scripts/check_contract_sync.py
```

离线 CI 仅校验 vendored hash 和 fixture；有网络的 release job 可对 canonical repo 再校验。

---

## 4.3 Stable Asset Identity v1

### 4.3.1 身份分层

| 字段 | 属性 | 生成方式 |
|---|---|---|
| `source_id` | 来源逻辑身份 | 注册时 UUIDv7/ULID |
| `deck_revision_id` | 某一 Deck 内容版本 | `drev_` + package fingerprint |
| `slide_revision_id` | 某一页确定内容版本 | `srev_` + canonical content fingerprint |
| `canonical_asset_id` | 逻辑可复用页面 | 首次创建时生成并持久化 |
| `deck_asset_id` | 逻辑 Deck | 首次归族时生成并持久化 |
| `source_locator_id` | 来源定位 | provider + opaque locator hash |

### 4.3.2 Fingerprint

`slide_revision_id` 的 fingerprint 输入至少包括：

- canonicalized slide XML；
- resolved relationship targets；
- embedded media hashes；
- visible text normalized hash；
- chart/workbook relationship hashes；
- optional rendered perceptual hash；
- fingerprint algorithm version。

必须排除：

- 文件路径；
- 数据库 id；
- OOXML volatile modified time；
- zip entry order；
-无业务意义的 relationship id 差异。

### 4.3.3 Canonical ID 行为

- canonical id 是持久身份，不要求完全由内容推导；
- exact revision 命中时复用；
- source locator continuity 强且内容近似时进入 lineage matcher；
- 不确定时创建新 canonical id 并标记待审查；
- 禁止仅因 embedding 相似就自动合并；
- 资产 registry 可导出/导入，保证跨库迁移。

### 4.3.4 Legacy Mapping

新增表：

```sql
asset_identity_map(
  canonical_asset_id TEXT NOT NULL,
  slide_revision_id TEXT NOT NULL,
  legacy_slide_id INTEGER,
  identity_status TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

现有 slide row 先建立 legacy mapping，不强制第一次迁移完成所有 lineage。

---

## 4.4 Job Engine v1

### 4.4.1 Job Tables

建议新增：

```sql
jobs
job_stages
job_events
job_checkpoints
staged_assets
```

最少字段：

```text
job_id
job_type
idempotency_key
source_id
source_locator
source_content_hash
pipeline_config_hash
status
current_stage
total_units
completed_units
failed_units
attempt
cancel_requested
created_at
started_at
finished_at
error_json
warning_json
```

### 4.4.2 Pipeline

```text
discover
→ extract
→ render
→ recognize
→ embed
→ stage
→ commit
→ govern
→ finalize
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

### 4.4.3 幂等规则

Idempotency key：

```text
source_locator_id
+ source_content_hash
+ pipeline_config_hash
+ fingerprint_algorithm_version
```

同一 key：

- 已 completed：返回已有结果；
- running：返回现有 job；
- failed：由 `--retry` 决定；
- config 变化：创建新 job；
- `--full`：强制新 pipeline config hash。

### 4.4.4 Writer 模型

v1.5 Local Mode 默认：

- extract/render/OCR/embed 可并行；
- metadata commit 由单 writer 串行执行；
- SQLite transaction 以文件或 staging batch 为单位；
- governance 在 commit 后增量执行；
- worker 不直接全局删除 duplicate/version 表。

### 4.4.5 CLI

```bash
ppt-lib index --from-sources --detach
ppt-lib jobs list --status running
ppt-lib jobs inspect <job-id>
ppt-lib jobs cancel <job-id>
ppt-lib jobs resume <job-id>
ppt-lib jobs retry <job-id>
```

兼容模式下，未加 `--detach` 可以同步等待，但内部仍使用 Job Engine。

### 4.4.6 崩溃恢复

必须覆盖：

- OCR 进程失败；
- embedding endpoint timeout；
- LibreOffice 卡死；
- SQLite busy；
- 用户 Ctrl+C；
- 主进程被 kill；
- 磁盘空间不足；
- source 文件在运行期间变化。

文件发生变化时，不得把不同版本阶段结果混为同一 revision。

---

## 4.5 Incremental Duplicate / Version Governance

当前全局重建逻辑需拆为：

```text
affected slide revisions
→ exact duplicate lookup
→ affected duplicate component update
→ affected deck family candidates
→ representative recalculation
```

要求：

- 只修改受影响 group/family；
- manual override 不被自动重算覆盖；
- 每次重算产生 change summary；
- 支持 `--dry-run`；
- 旧全量重算命令保留用于修复；
- 增加 consistency validator。

CLI：

```bash
ppt-lib governance validate
ppt-lib governance recompute --scope affected --dry-run
ppt-lib governance recompute --scope all --apply
```

---

## 4.6 Database Migration

建议 DB Schema：`4 → 5`，最终编号以 Codex 核验为准。

迁移流程：

1. 检查数据库完整性；
2. 创建 timestamped backup；
3. 写 migration journal；
4. 新建表和索引；
5. backfill identity；
6. 校验 row count、foreign key、hash uniqueness；
7. 标记 migration completed；
8. 失败回滚事务；
9. destructive backfill 失败时从 backup 恢复。

CLI：

```bash
ppt-lib migrate plan
ppt-lib migrate apply
ppt-lib migrate verify
ppt-lib migrate restore <backup>
```

启动时只允许：

- schema 当前：正常；
- schema 旧且可迁移：提示迁移；
- schema 新于程序：拒绝写入；
- migration incomplete：进入 recovery mode。

---

## 4.7 文件与解析安全

新增：

- ZIP entry 数量和展开大小上限；
- 单 XML/媒体大小上限；
- OOXML path traversal 防护；
- external relationship inventory；
- embedded object inventory；
- renderer timeout；
- temp directory isolation；
- 子进程 stdout/stderr 大小限制；
- archive bomb error code；
- source 文件变化检测；
- render artifact content hash。

错误码示例：

```text
PPTX_ARCHIVE_LIMIT_EXCEEDED
PPTX_PATH_TRAVERSAL_DETECTED
PPTX_EXTERNAL_RELATIONSHIP_BLOCKED
RENDER_TIMEOUT
SOURCE_CHANGED_DURING_INDEX
DISK_SPACE_INSUFFICIENT
```

默认不执行宏和嵌入程序。

---

## 4.8 Release Engineering

### 4.8.1 构建

- sdist；
- wheel；
- clean venv install；
- `ppt-lib --version`；
- `ppt-lib schema --output json`；
- temp home smoke；
- no private paths；
- SBOM；
- dependency vulnerability report。

### 4.8.2 平台

Tier-1：

- macOS current supported versions，arm64/x64；
- Ubuntu LTS x64。

Tier-2：

- Windows 11 x64；
- 无 LibreOffice 的 text-only mode。

### 4.8.3 Package Registry

目标为官方 Python package registry 发布。实施前必须核验：

- package name availability；
- trusted publishing；
- signing/attestation；
- release token policy。

若公开 Registry 暂不满足，先发布 GitHub Release wheel，但 release gate 不降低。

---

## 4.9 Diagnostics v2

`doctor` 增加：

- DB schema；
- migration state；
- asset identity coverage；
- stuck jobs；
- staging disk usage；
- renderer health；
- provider egress summary；
- contract availability；
- file permission；
- disk space；
- index consistency。

输出明确区分：

```text
healthy
degraded
blocked
```

---

## 5. 建议数据库新增对象

```text
jobs
job_stages
job_events
job_checkpoints
staged_assets
asset_identity_map
deck_asset_identity
identity_overrides
contract_registry
migration_journal
```

索引：

```text
jobs(idempotency_key)
jobs(status, updated_at)
asset_identity_map(slide_revision_id)
asset_identity_map(canonical_asset_id)
job_events(job_id, occurred_at)
migration_journal(status)
```

---

## 6. 配置项

```yaml
jobs:
  worker_count: 2
  writer_batch_size: 1
  checkpoint_interval_seconds: 10
  staging_ttl_days: 7

identity:
  fingerprint_version: slide-fingerprint-v1
  auto_merge_threshold: disabled
  review_threshold: 0.85

security:
  max_archive_entries: 20000
  max_uncompressed_mb: 2048
  max_single_entry_mb: 512

contracts:
  default: legacy
  strict_validation: true
```

配置变更必须进入 `pipeline_config_hash`。

---

## 7. 测试要求

### 7.1 Unit

- fingerprint deterministic；
- volatile OOXML 差异不改变 revision id；
- meaningful content 变化改变 revision id；
- identity registry import/export；
- job state machine；
- idempotency；
- cancel/resume；
- migration plan；
- archive safety；
- contract validation。

### 7.2 Integration

- synthetic deck 完整索引；
- 中途 kill 后 resume；
- OCR fail 后 retry；
- file change during run；
- concurrent worker + single writer；
- migration 4→5；
- legacy CLI；
- Deck Master contract subprocess。

### 7.3 Failure Injection

- SQLite locked；
- disk full；
- provider 429/500；
- renderer timeout；
- corrupt checkpoint；
- invalid vendored schema；
- duplicate idempotency request。

### 7.4 Platform Smoke

- install wheel；
- text extraction；
- no-model search；
- optional renderer；
- path with Chinese/spaces；
- temp home cleanup。

---

## 8. 发布硬门禁

v1.5 不得发布，除非：

1. 全量 automated tests 通过；
2. current CLI regression suite 通过；
3. Deck Master Contract UAT 100%；
4. migration fixture 全部通过；
5. crash-resume fixture 通过；
6. 10k synthetic slides 索引报告存在；
7. 无 P0/P1 数据损坏风险；
8. wheel clean install 通过；
9. release_check 不含仓库私有路径假设；
10. release notes 列出兼容与已知限制。

---

## 9. 验收场景

### AC-01 文件移动

同一已索引 PPTX 从目录 A 移到 B：

- source locator 更新；
- exact revision identity 不变；
- canonical asset 不变；
-搜索不产生重复候选；
- provenance 保留移动历史。

### AC-02 崩溃恢复

索引 100 个 Deck，在第 53 个中断：

- job 状态可诊断；
- resume 不重复前 52 个；
- 第 53 个从安全 checkpoint 继续或干净重跑；
- 最终数据库一致。

### AC-03 Contract

Deck Master 发起 selection：

- PPT Library 原生输出 canonical schema；
- run_id 绑定；
- invalid candidate 阻止写文件；
- Deck Master 无需二次字段猜测。

### AC-04 Migration

使用 v1.4.1 fixture 数据库升级：

- backup 存在；
- row count 一致；
- search 结果基线不显著回归；
- identity coverage 报告存在；
- v1.5 重开数据库成功。

---

## 10. 交付物

```text
contracts schemas + examples
job engine
identity registry
migration
incremental governance
diagnostics v2
release matrix
Deck Master UAT
release notes
benchmark artifact
operator troubleshooting guide
```

---

## 11. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 1.5-A | Baseline & ADR | 无 |
| 1.5-B | Contract Registry & Capabilities | A |
| 1.5-C | Deck Master Native Contract | B |
| 1.5-D | Stable Identity & Migration | A |
| 1.5-E | Job Engine & Checkpoints | D |
| 1.5-F | Incremental Governance | D、E |
| 1.5-G | Parser/Renderer Safety | E |
| 1.5-H | Distribution & Release Gate | B～G |


---

<!-- SOURCE: 04-v1.6-search-quality-and-benchmark.md -->

# 04 — v1.6 Search Quality & Benchmark Spec

**Version:** 1.6.0
**Maturity Target:** Measurable Retrieval Product
**Primary Goal:** 从“能搜到”升级为“检索质量、性能和降级行为均可证明”。
**Depends On:** v1.5 identity/job/contracts
**Blocks:** v1.7 ranking、v1.8 Workbench、v2.0 SLA

---

## 1. 版本结论

v1.6 的重点不是更换 embedding 模型，而是建立完整 Retrieval System：

```text
Query Understanding
→ Lexical Recall
→ Vector Recall
→ Candidate Fusion
→ Metadata Filtering
→ Optional Rerank
→ Business/Context Adjustment
→ Health Penalty
→ Explainability
→ Benchmark
```

所有默认权重、阈值和 fallback 都必须通过 benchmark 证明。

---

## 2. 目标

### G1 — Hybrid Retrieval v2

引入 FTS5/BM25 与 Vector ANN 双路召回。

### G2 — Search Profile

不同使用场景使用版本化 Search Profile，不在代码里散落固定权重。

### G3 — Explainability

每个候选可解释来源、分数、过滤、降级和模型版本。

### G4 — Benchmark as Release Gate

Recall、MRR、nDCG、延迟、重复率和人工可用率成为发布门禁。

### G5 — Scale

Local Mode 在 10k/50k/100k slide 三档有可复跑报告。

---

## 3. 非目标

- 不在 v1.6 实现团队 Server；
- 不把用户行为直接训练成在线模型；
- 不承诺通用跨行业最佳权重；
- 不把 reranker 设为硬依赖；
- 不允许云端 reranker 静默接收私有内容；
- 不在无标注数据时宣称“AI 搜索质量提升”。

---

## 4. Retrieval Architecture

```text
                         query
                           │
                ┌──────────▼──────────┐
                │ Query Normalization  │
                │ language/terms/hints │
                └───────┬───────┬─────┘
                        │       │
             ┌──────────▼─┐   ┌─▼────────────┐
             │ FTS5/BM25   │   │ Vector Recall│
             │ lexical topN│   │ ANN topN     │
             └──────────┬──┘   └──┬───────────┘
                        └────┬─────┘
                             ▼
                       RRF / Fusion
                             │
                       Hard Filters
                             │
                     Optional Rerank
                             │
             Business / Context / Health
                             │
                       Final Candidates
```

---

## 5. Search Document

每个 Slide Revision 建立 Search Document：

```text
search_document_id
canonical_asset_id
slide_revision_id
title
body_text
ocr_markdown
ai_summary
visual_summary
deck_summary
industry
scenario
narrative_role
page_role
page_archetype
client_type
review_state
confidentiality
freshness
source_id
deck_family_id
representative_version
business_signals
document_version
```

Search Document 必须可重建，不作为唯一事实来源。

---

## 6. Lexical Recall

### 6.1 FTS5

建立 SQLite FTS5：

- title 高权重；
- page role/archetype；
- body；
- OCR；
- AI/visual summary；
- source/deck display name。

中文：

- v1.6 首版允许采用 Unicode token + n-gram 辅助；
- tokenizer 策略必须版本化；
- 不得继续仅靠 Python 全量字符串扫描作为默认路径；
- 若 FTS5 不可用，报告 fallback。

### 6.2 BM25 Profile

配置：

```yaml
lexical:
  title_weight: 3.0
  role_weight: 2.0
  summary_weight: 1.5
  body_weight: 1.0
  source_weight: 0.5
```

权重来自 benchmark，而非主观固定。

---

## 7. Vector Recall

### 7.1 Backend

```text
sqlite_scan    # 小库与兼容
local_hnsw     # Local Large 默认
remote_vector  # 接口预留，v1.9
```

### 7.2 Index Metadata

```text
vector_index_id
backend
embedding_provider
embedding_model
dimensions
normalization
document_count
index_version
build_job_id
config_hash
created_at
status
```

### 7.3 Rebuild

模型或 dimensions 变化时：

```bash
ppt-lib vector-index plan
ppt-lib vector-index build --background
ppt-lib vector-index status
ppt-lib vector-index activate <id>
ppt-lib vector-index rollback <id>
```

激活采用双索引切换，构建失败不影响当前可用索引。

---

## 8. Fusion

默认采用 RRF，避免不同分数域直接线性相加：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

Search Profile 控制：

```yaml
fusion:
  method: rrf
  rrf_k: 60
  lexical_top_n: 100
  vector_top_n: 100
  fusion_top_n: 50
```

保留线性融合用于实验，不作为默认。

---

## 9. Filtering

Hard Filter 在 rerank 前完成：

- workspace/source；
- industry/scenario；
- narrative/page role；
- page archetype；
- review state；
- confidentiality；
- source availability；
- representative version；
- duplicate policy；
- time range；
- health severity。

必须明确区分：

```text
hard_filter
soft_boost
soft_penalty
```

禁止把保密或 source missing 仅作为轻微降权。

---

## 10. Reranker

### 10.1 Provider

```text
none
local_cross_encoder
openai_compatible
custom_http
```

### 10.2 Egress

启用云端 reranker 前必须：

- policy 允许；
- provider capability 声明；
- UI/CLI 说明内容外发；
- 支持只发送摘要而非完整正文；
- 记录 provider/model；
- 超时后 fallback，不中断整个搜索。

### 10.3 Candidate Size

默认只 rerank fusion Top-30，最终输出 Top-K。

---

## 11. Search Profile

建议内置：

```text
fast
balanced
high_recall
business
visual
deck_master
```

Profile 是版本化 YAML/JSON：

```yaml
profile: balanced
version: 1
lexical: ...
vector: ...
fusion: ...
rerank: ...
business: ...
health: ...
```

CLI：

```bash
ppt-lib search "..." --profile balanced
ppt-lib search explain "..." --profile deck_master
ppt-lib search-profile list
ppt-lib search-profile show balanced
```

用户自定义 Profile 必须有 schema validation。

---

## 12. Query Understanding

v1.6 首版采用确定性解析：

- 中文/英文 normalization；
- exact phrase；
- quoted terms；
- industry aliases；
- scenario aliases；
- role/archetype hints；
- negative terms；
- filter expression；
- typo normalization（可选）。

不要求 LLM Query Planner 为默认。可选 LLM expansion 必须：

- 明确启用；
- 保存 expanded terms；
- 可 benchmark；
- 失败可回退。

---

## 13. Explainability

每次搜索可生成 Query Trace：

```json
{
  "query_trace_id": "qry_...",
  "normalized_query": "...",
  "profile": "balanced@1",
  "filters": {},
  "backends": [],
  "fallbacks": [],
  "candidate_counts": {
    "lexical": 100,
    "vector": 100,
    "fused": 47,
    "reranked": 30,
    "returned": 10
  },
  "timings_ms": {},
  "model_versions": {}
}
```

Candidate：

```text
lexical rank/score
vector rank/score
RRF score
rerank score
business boost
context boost
health penalty
final rank
matched fields
filter reasons
```

---

## 14. Evaluation v2

### 14.1 Dataset Tiers

| Suite | 内容 | 是否公开 |
|---|---|---|
| `synthetic-public` | 合成 PPT 和可提交标签 | 是 |
| `anonymized-release` | 脱敏真实分布 | 可选 |
| `private-golden` | 用户真实资产和 query | 否 |
| `regression-smoke` | 小型快速 CI | 是 |

### 14.2 Query Types

- exact fact；
- semantic concept；
- page role；
- industry/scenario；
- visual-heavy page；
- title mismatch；
- acronym；
- Chinese/English mixed；
- version-heavy；
- duplicate-heavy；
- no-result；
- confidentiality filtered。

### 14.3 Metrics

- Recall@5/10；
- Precision@5；
- MRR；
- nDCG@10；
- no-result rate；
- duplicate result rate；
- representative version rate；
- latency P50/P95/P99；
- peak memory；
- index build time；
-人工 Top-5 useful rate。

### 14.4 Benchmark Manifest

记录：

```text
dataset_hash
query_set_hash
commit_sha
package_version
db_schema
search_profile_hash
embedding provider/model
reranker provider/model
hardware
OS
started_at
result artifact hashes
```

---

## 15. Performance Targets

### Tier S — 10k slides

- P95 ≤ 0.8s；
- P99 ≤ 1.5s；
- peak process memory ≤ 1.0GB。

### Tier M — 50k slides

- P95 ≤ 1.5s；
- P99 ≤ 3.0s；
- peak process memory ≤ 1.5GB。

### Tier L — 100k slides

- P95 ≤ 3.0s；
- P99 ≤ 5.0s；
- peak process memory ≤ 2.5GB。

指标以本地 ANN、无云 rerank 为基准。硬件必须记录，不允许跨硬件直接比较。

---

## 16. Quality Targets

Release Golden Set：

```text
Recall@10 >= 0.85
MRR >= 0.65
nDCG@10 >= 0.75
Top-5 useful rate >= 0.70
duplicate candidate rate <= 0.10
```

回归门：

- 任一核心指标绝对下降 > 0.03：阻断；
- P95 延迟恶化 > 20% 且无接受 ADR：阻断；
- fallback 比例增加 > 5 个百分点：阻断；
- protected query 失败：阻断。

---

## 17. Database Changes

建议 Schema `5 → 6`：

```text
search_documents
search_profiles
vector_indexes
query_traces
query_candidates
benchmark_runs
benchmark_metrics
fts virtual tables
```

Query trace 默认可配置保留期，避免长期存储私有查询。

---

## 18. CLI

```bash
ppt-lib search "..." --profile balanced --explain
ppt-lib search explain "..."
ppt-lib search-profile list
ppt-lib search-profile validate <file>
ppt-lib vector-index plan
ppt-lib vector-index build
ppt-lib vector-index activate
ppt-lib benchmark run --suite regression-smoke
ppt-lib benchmark run --suite release
ppt-lib benchmark compare <baseline> <candidate>
ppt-lib benchmark report <run-id> --html
```

---

## 19. Failure Handling

| 场景 | 行为 |
|---|---|
| FTS 不可用 | 使用 vector-only，warning |
| ANN 不可用 | 使用 sqlite_scan，warning |
| Query embedding 失败 | lexical-only；若 profile 禁止则 error |
| Reranker timeout | 返回 pre-rerank 排名，warning |
| Profile 非法 | 拒绝执行 |
| Index 与 model 不匹配 | 拒绝使用该 vector index |
| Filter 导致空结果 | 返回 empty reason，不自动取消 hard filter |
| DB busy | bounded retry；失败返回 retryable error |

所有 fallback 都进入 query trace。

---

## 20. 测试

### Unit

- FTS query；
- Chinese normalization；
- RRF；
- filters；
- profile validation；
- backend selection；
- explainability；
- metric calculation。

### Integration

- dual recall；
- ANN build/activate/rollback；
- model dimension mismatch；
- reranker timeout；
- representative/duplicate filtering；
- Deck Master profile；
- benchmark reproducibility。

### Property / Invariant

- hard filtered item 永不返回；
- same profile+same index+deterministic providers 结果稳定；
- Top-K 不含重复 canonical asset，除非显式允许；
- explanation 的 final rank 与实际一致；
- query trace 不包含密钥。

---

## 21. 发布门禁

1. Release benchmark 达标；
2. current v1.5 contract 不回归；
3. 10k/50k/100k 性能报告；
4. fallback test 全覆盖；
5. search profile version 固定；
6. benchmark artifact 可复跑；
7. API/CLI explanation 一致；
8. no-model lexical-only mode 可用；
9. model dimension migration 文档完整；
10. 公开 benchmark 不含客户数据。

---

## 22. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 1.6-A | Search Document & FTS5 | v1.5 |
| 1.6-B | Vector Backend & ANN Lifecycle | A |
| 1.6-C | Fusion / Filters / Profiles | A、B |
| 1.6-D | Reranker & Egress Policy | C |
| 1.6-E | Explainability & Query Trace | C |
| 1.6-F | Evaluation v2 & Public Dataset | C |
| 1.6-G | Performance Harness | B、F |
| 1.6-H | Release Quality Gate | D～G |


---

<!-- SOURCE: 05-v1.7-asset-intelligence-and-lineage.md -->

# 05 — v1.7 Asset Intelligence & Lineage Spec

**Version:** 1.7.0
**Maturity Target:** Governed Asset Intelligence
**Primary Goal:** 把“搜索结果”升级为有身份、关系、健康状态和反馈学习的资产。
**Depends On:** v1.5 stable identity；v1.6 retrieval/benchmark
**Blocks:** v1.8 review workflows；v1.9 team governance

---

## 1. 版本结论

v1.7 是 PPT Library 的核心护城河版本。

普通向量库可以找到文本相似页面，但难以回答：

- 这几页是否是同一逻辑资产的不同版本？
- 哪一页是代表版本？
- 哪些页面只是换了客户名？
- 哪一页已经过期或来源文件丢失？
- 哪些候选被人多次拒绝？
- 同一页面在哪些行业和场景下真正被保留？
- 页面是原始资产、复制页还是被修改的衍生页？

v1.7 必须建立 Asset Intelligence 领域，而不是继续把字段堆进 `slides` 表。

---

## 2. 目标

### G1 — Near Duplicate

从 exact hash 去重升级为多信号近重复识别。

### G2 — Slide/Deck Lineage

支持版本、复制、修改、派生和 supersede 关系。

### G3 — Rich Asset Metadata

页面具备 page archetype、role、industry、scenario、evidence type、confidentiality、freshness 等可治理属性。

### G4 — Feedback Lifecycle

记录 surfaced、reviewed、selected、rejected、assembled、retained、modified、replaced、delivered 和 outcome-linked。

### G5 — Asset Health

可生成资产健康报告、修复建议和 review queue。

### G6 — Ranking v2

业务反馈以保守统计和场景条件影响排序，不被少量赢单样本污染。

---

## 3. 非目标

- 不自动删除资产；
- 不自动把高相似页面强行合并；
- 不把赢单结果当作单页因果证据；
- 不构建完整知识图谱平台；
- 不在 v1.7 建设 UI；
- 不让 LLM 输出直接覆盖人工标签；
- 不把 Deck Master 的 Claim/Evidence 逻辑全部搬入 PPT Library。

---

## 4. Asset Intelligence Model

```text
DeckAsset
 ├── DeckRevision
 │    ├── SlideRevision
 │    └── SlideRevision
 └── DeckRevision

SlideAsset
 ├── preferred SlideRevision
 ├── LineageEdges
 ├── Classifications
 ├── Review Decisions
 ├── Feedback Events
 └── Health Findings
```

---

## 5. Near Duplicate v2

### 5.1 信号

| 信号 | 说明 |
|---|---|
| exact package/slide fingerprint | 完全相同 Revision |
| text hash | 文本完全相同 |
| normalized text similarity | 文案微调 |
| visual pHash/dHash | 渲染近似 |
| layout fingerprint | shape 类型、位置、层级、占比 |
| media hash overlap | 共享图片/图标 |
| embedding similarity | 语义近似 |
| source/deck continuity | 同一文件版本或相邻版本 |
| page position | 同一 family 中页码关系 |
| title/role compatibility | 限制错误合并 |

### 5.2 分类

```text
exact_duplicate
near_duplicate
template_variant
client_variant
content_revision
unrelated_similar
needs_review
```

### 5.3 判定流程

```text
Exact Gates
→ Candidate Blocking
→ Multi-signal Scoring
→ Safety Rules
→ Auto Classification or Review Queue
```

Candidate Blocking 采用：

- same deck family；
- shared visual hash bucket；
- high text MinHash；
- high embedding ANN；
- same source lineage。

禁止全量 O(N²)。

### 5.4 自动动作阈值

- exact duplicate：可自动归组；
- near duplicate 高置信：可自动建议，不自动删除；
- client variant：默认独立 canonical asset，建立 relation；
- identity 冲突：必须人工 review；
- manual split/merge 永远优先于自动重算。

### 5.5 评测

人工标注 pair set：

```text
positive exact
positive near
positive client variant
negative same topic
negative same template
negative unrelated
```

目标：

```text
duplicate precision >= 0.95
duplicate recall >= 0.85
client-variant false merge <= 0.02
manual override preservation = 100%
```

---

## 6. Layout Fingerprint

建议提取：

- slide size；
- shape count by type；
- normalized bounding boxes；
- text/image/chart/table proportions；
- grouping hierarchy；
- dominant alignment/grid；
- color palette sketch；
- font family set；
- master/layout reference；
- chart/table presence；
- image hash set。

Fingerprint 必须版本化：

```text
layout-fingerprint-v1
```

不能把具体客户文本直接写入公开日志。

---

## 7. Lineage Graph

### 7.1 Edge

```text
copied
modified
derived
supersedes
same_visual
same_text
same_template
client_variant
```

字段：

```text
edge_id
from_revision_id
to_revision_id
relation
confidence
evidence_json
algorithm_version
review_status
reviewed_by
created_at
```

### 7.2 自动推断

优先信号：

1. same source deck family 的版本顺序；
2. stable slide position；
3. near duplicate；
4. source file history；
5. assembly lineage；
6. imported metadata。

### 7.3 人工修正

支持：

```bash
ppt-lib lineage link <from> <to> --relation modified
ppt-lib lineage unlink <edge-id>
ppt-lib lineage confirm <edge-id>
ppt-lib lineage reject <edge-id>
ppt-lib lineage inspect <asset-id>
```

### 7.4 Representative Revision

代表 Revision 选择必须综合：

- manual preferred；
- review approved；
- latest valid；
- source available；
- health severity；
- version role；
- fidelity；
- business usage；
- confidentiality policy。

不得只按文件名中的 `final` 判断。

---

## 8. Asset Classification

### 8.1 分类维度

```text
industry
scenario
narrative_role
page_role
page_archetype
evidence_type
audience
content_density
visual_complexity
editability
brand_family
language
confidentiality
freshness_class
```

### 8.2 Page Archetype

最少：

```text
cover
agenda
section_divider
problem
insight
framework
process
architecture
capability_map
comparison
roadmap
case_study
data_chart
roi
team
timeline
pricing
cta
appendix
other
```

### 8.3 来源优先级

```text
manual approved
> imported trusted metadata
> deterministic rule
> model suggestion
> unknown
```

每个标签必须有：

- value；
- source；
- confidence；
- model/rule version；
- reviewed state；
- timestamps。

### 8.4 Model Output

LLM/vision 输出先进入 suggestion，不直接改 authoritative value。

---

## 9. Evidence Metadata

PPT Library 只记录资产级证据属性，不承担 Deck Master 的论证正确性：

```text
evidence_type:
  client_fact
  external_fact
  case_evidence
  product_capability
  methodology
  estimate
  opinion
  unknown

evidence_provenance:
  source_uri
  source_title
  source_date
  extracted_at
  citation_text_hash
```

如果页面包含明显事实但无来源，可产生 health finding：

```text
EVIDENCE_PROVENANCE_MISSING
```

---

## 10. Confidentiality

分类：

```text
public
internal
client_confidential
restricted
unknown
```

规则：

- 新索引默认 `unknown` 或继承 source policy；
- client name/entity detection 只作为 suggestion；
- restricted 资产不得由 policy 不允许的云 provider 处理；
- Deck Master selection 默认过滤不兼容 confidentiality；
- Workbench v1.8 提供人工修订；
- Team Mode v1.9/2.0 强制 RBAC。

---

## 11. Feedback Event Model

### 11.1 Event Types

```text
candidate.surfaced
candidate.opened
candidate.reviewed
candidate.selected
candidate.rejected
candidate.rejection_reasoned
asset.assembled
asset.retained
asset.modified
asset.replaced
asset.delivered
deal.outcome_linked
asset.rated
asset.tag_corrected
```

### 11.2 Context

```text
workspace
run/deal/opportunity
industry
scenario
audience
page role
query trace
position
source system
actor
```

### 11.3 Rejection Reasons

```text
irrelevant
wrong_industry
wrong_role
outdated
confidentiality
poor_visual
too_dense
duplicate
source_missing
brand_mismatch
fact_risk
other
```

### 11.4 Idempotency

上层系统必须传：

```text
event_id or idempotency_key
```

重复导入不得重复计数。

---

## 12. Business Ranking v2

### 12.1 原则

- feedback 是弱监督，不是绝对真值；
- 低样本需要 shrinkage；
- 场景条件优先于全局汇总；
- negative feedback 必须进入；
- health/confidentiality 可阻断或惩罚；
- score breakdown 必须解释。

### 12.2 建议统计

使用 Beta-Binomial 平滑或等价保守估计：

```text
posterior_acceptance
posterior_retention
posterior_success
confidence
```

Example：

```text
accept_rate = (selected + α) / (surfaced + α + β)
```

不同事件权重不得硬编码散落，进入 `ranking_profile`.

### 12.3 Context Segments

```text
global
industry
scenario
industry+scenario
page_role
```

只有样本达到最小门槛才使用细分 segment，否则回退。

### 12.4 防污染

- synthetic/demo event 默认不进入 production score；
- fixture source 独立；
- imported outcome 必须标记 source；
- manual admin 可重算；
- 训练/评估数据隔离。

---

## 13. Asset Health

### 13.1 Finding Categories

```text
SOURCE_MISSING
SOURCE_CHANGED_UNINDEXED
SCREENSHOT_MISSING
LOW_RESOLUTION
FONT_RISK
BROKEN_EXTERNAL_LINK
EMBEDDED_OBJECT_RISK
CONFIDENTIALITY_UNKNOWN
STALE_FACT_RISK
BRAND_MISMATCH
DUPLICATE_UNREVIEWED
VERSION_AMBIGUOUS
EVIDENCE_PROVENANCE_MISSING
MODEL_METADATA_STALE
IDENTITY_NEEDS_REVIEW
```

### 13.2 Finding

```text
finding_id
asset/revision id
code
severity
status
evidence
suggested_action
detector_version
created_at
resolved_at
resolution
```

### 13.3 CLI

```bash
ppt-lib health scan --scope all
ppt-lib health report --severity high
ppt-lib health inspect <asset-id>
ppt-lib health resolve <finding-id> --resolution ...
ppt-lib health export --output report.json
```

自动修复必须 dry-run，v1.7 不自动删除。

---

## 14. Asset Pack

为了迁移和共享，新增 portable asset pack：

```text
asset-pack/
├── manifest.json
├── identities.jsonl
├── revisions.jsonl
├── lineage.jsonl
├── classifications.jsonl
├── feedback.jsonl
├── health.jsonl
└── blobs/
```

要求：

- 内容 hash；
- schema version；
- source path redaction policy；
- optional blob inclusion；
- encryption option预留；
- import dry-run；
- conflict report；
- canonical id preservation；
- idempotent import。

CLI：

```bash
ppt-lib asset-pack export --filter approved --output pack.zip
ppt-lib asset-pack inspect pack.zip
ppt-lib asset-pack import pack.zip --dry-run
ppt-lib asset-pack import pack.zip --apply
```

---

## 15. Database Changes

建议 Schema `6 → 7`：

```text
slide_assets_v2
slide_revisions
deck_assets_v2
deck_revisions
lineage_edges
asset_classifications
classification_suggestions
feedback_events
feedback_aggregates
health_findings
manual_identity_overrides
asset_pack_imports
```

现有 `slides` 表继续兼容读取，逐步映射到 Revision。

---

## 16. CLI

```bash
ppt-lib duplicates scan
ppt-lib duplicates review-list
ppt-lib duplicates confirm <group>
ppt-lib duplicates split <group>
ppt-lib lineage inspect <asset>
ppt-lib lineage link ...
ppt-lib classify run --pending
ppt-lib classify suggestions
ppt-lib feedback record --event ...
ppt-lib feedback import ...
ppt-lib ranking recompute
ppt-lib health scan
ppt-lib health report
ppt-lib asset-pack export/import
```

---

## 17. Testing

### 17.1 Labeled Datasets

- near duplicate pair set；
- deck family set；
- lineage sequence set；
- archetype set；
- confidentiality synthetic set；
- health fixture set；
- feedback aggregation set。

### 17.2 Invariants

- manual split 不被自动 merge；
- exact same revision 只有一个 revision id；
- canonical id 导入后保持；
- feedback 重放幂等；
- restricted asset 不被不允许 provider 处理；
- representative revision 必须存在且可访问或明确 degraded；
- demo feedback 不进入 production aggregate。

### 17.3 Human Review

至少两位 reviewer 对 duplicate/version/archetype 子集标注；记录一致性和争议。

---

## 18. 发布门禁

1. Near duplicate precision/recall 达标；
2. Client variant false merge 达标；
3. Manual override preservation 100%；
4. Feedback idempotency 100%；
5. Asset pack round-trip 无身份丢失；
6. Health scan 在 50k 资产内完成性能门；
7. Ranking v2 不使 retrieval golden set 下降超过阈值；
8. v1.6 search contract 不破坏；
9. 所有分类保留 source/confidence；
10. 无自动 destructive action。

---

## 19. 验收场景

### AC-01 客户变体

同一架构页换客户名和 Logo：

- 不被标为 exact duplicate；
- 建立 `client_variant`；
- canonical asset 默认独立；
- Workbench 可比较；
- search 默认避免同时返回多个近似变体。

### AC-02 修改继承

同一 Deck v1→v2：

- Deck revisions 归属同一 deck asset；
- 相近页面建立 modified/supersedes edge；
- 代表版本选择可解释；
- old version 可审计。

### AC-03 反馈

Deck Master 多次 surfaced/selected/rejected：

- event 幂等；
- 按行业/场景聚合；
- 低样本不产生过大 boost；
- rejection reason 可查询；
- score breakdown 可解释。

---

## 20. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 1.7-A | Asset/Revision/Lineage Schema | v1.6 |
| 1.7-B | Layout & Visual Fingerprints | A |
| 1.7-C | Near Duplicate Classifier | A、B |
| 1.7-D | Deck/Slide Lineage | A、C |
| 1.7-E | Classification & Suggestions | A |
| 1.7-F | Feedback & Ranking v2 | A、v1.6 |
| 1.7-G | Asset Health | C～F |
| 1.7-H | Asset Pack & Release Gate | A～G |


---

<!-- SOURCE: 06-v1.8-local-review-workbench.md -->

# 06 — v1.8 Local Review Workbench Spec

**Version:** 1.8.0
**Maturity Target:** Human-Governed Local Product
**Primary Goal:** 为非开发者提供本地、可视化、可审计的资产审查与治理工作台。
**Depends On:** v1.7 asset/lineage/feedback/health
**Blocks:** v1.9 team server reuse

---

## 1. 版本结论

Workbench 不是独立重写一个产品，也不是给 SQLite 套一个 CRUD 页面。它必须复用 v1.5～v1.7 的 Application Service 和 Contract，让人类可以完成 Agent 无法安全自动化的判断：

- 哪些页面应当合并或拆分？
- 哪个版本应作为代表？
- 页面标签是否正确？
- 哪些资产可以被 Agent 复用？
- 哪些资产过期、保密或来源缺失？
- 为什么某个候选经常被拒绝？

---

## 2. 目标

### G1 — Search & Review

通过大图预览、筛选和解释快速确认候选。

### G2 — Duplicate / Version Governance

支持视觉比较、merge/split、代表版本选择和 lineage 修订。

### G3 — Metadata & Health

支持批量标签、保密状态、review state 和 health finding 处理。

### G4 — Job Operations

可查看索引任务、失败、重试、取消和 provider 状态。

### G5 — Local Security

默认只允许本机访问，所有写操作有 revision token 和本地 audit event。

---

## 3. 非目标

- 不在 v1.8 实现多人协同；
- 不提供公网访问；
- 不做复杂 PPT 编辑；
- 不替代 Deck Master Preview；
- 不允许 UI 直接写 SQL；
- 不做拖拽生成完整 Deck 的主流程；
- 不因 UI 需求改变现有核心 Contract 语义。

---

## 4. 技术方案

### 4.1 Stack

推荐：

```text
FastAPI / Starlette
Jinja2
HTMX
少量 Alpine.js 或原生 JS
Bundled static assets
```

原因：

- Python 项目一致；
- wheel 可携带；
- 无 Node runtime；
- 本地部署简单；
- 可在 v1.9 复用 API。

如实现团队已具备成熟 React/Vite 基础，可形成 ADR 变更，但必须满足：

- 构建产物随 wheel；
- 最终用户不安装 Node；
- API/Service 边界不变；
- UI 测试和可访问性不降低。

### 4.2 启动

```bash
ppt-lib workbench start
ppt-lib workbench start --port 8765 --open
ppt-lib workbench status
ppt-lib workbench stop
```

默认：

- bind `127.0.0.1`；
- 随机可用端口或配置端口；
- 生成短期 session token；
- 浏览器 URL 带一次性 bootstrap token；
- token 换取 HttpOnly session cookie；
- 不写入命令历史中的长期 token。

远程绑定必须：

```bash
--allow-remote --auth-token-env PPT_LIB_WORKBENCH_TOKEN
```

且输出高风险警告。

---

## 5. API

基础路径：

```text
/api/v1
```

资源：

```text
GET  /status
GET  /assets
GET  /assets/{id}
PATCH /assets/{id}
GET  /assets/{id}/revisions
GET  /assets/{id}/lineage
GET  /search
POST /reviews
GET  /duplicate-groups
POST /duplicate-groups/{id}/confirm
POST /duplicate-groups/{id}/split
GET  /families
POST /families/{id}/representative
GET  /health/findings
POST /health/findings/{id}/resolve
GET  /jobs
POST /jobs/{id}/retry
POST /jobs/{id}/cancel
GET  /providers
POST /metadata/batch
```

所有 PATCH/POST 必须：

- CSRF/session 验证；
- `revision_token`；
- service layer；
- structured error；
- audit event；
- transaction；
- 更新后返回新 revision token。

---

## 6. 页面设计

## 6.1 Dashboard

展示：

- presentations/slides/assets；
- identity coverage；
- pending jobs；
- failed jobs；
- provider health；
- search quality latest gate；
- duplicate review count；
- health severity；
- metadata review coverage；
- source availability；
- storage usage。

禁止只展示“总页数”而无行动入口。

---

## 6.2 Search

能力：

- query；
- Search Profile；
- filters；
- grid/list；
- large preview；
- score explanation；
- duplicate collapse；
- version expand；
- keyboard navigation；
- multi-select；
- export review pack；
- open source file；
- copy candidate contract。

每个卡片至少显示：

- preview；
- title；
- source/deck；
- page；
- score；
- representative/version；
- role/archetype；
- review state；
- health/confidentiality warning。

---

## 6.3 Asset Detail

区域：

```text
Preview
Identity
Source Provenance
Metadata
Classifications
Revision History
Lineage
Usage/Feedback
Health Findings
Search Explanation Sample
Review Actions
```

支持：

- set approved/rejected/needs_review；
- set preferred revision；
- tag；
- confidentiality；
- comments；
- open original；
- export metadata；
- compare revisions。

---

## 6.4 Duplicate Review

双页或多页对比：

- synchronized zoom；
- overlay/diff 可选；
- text diff；
- layout signal；
- visual similarity；
- source history；
- current canonical assignment；
- recommended relation；
- confirm merge；
- client variant；
- split；
- defer。

任何 destructive merge 必须展示影响资产数和 downstream references。

---

## 6.5 Version Family

展示：

- deck revisions timeline；
- representative；
- version role；
- page count；
- source availability；
- health；
- changes summary；
- manual override；
- re-run family inference。

---

## 6.6 Key Page Review

基于 v1.4+ insights 发展：

- importance score；
- page role；
- reuse count；
- selection rate；
- rejection reasons；
- visual review；
- approve as reusable；
- mark low priority；
- request metadata enrichment。

---

## 6.7 Health Review

按 severity/code/filter：

- finding；
- evidence；
- affected assets；
- suggested action；
- bulk resolve；
- rescan；
- export report。

自动修复必须先生成 preview。

---

## 6.8 Job Monitor

展示：

- job status；
- stage；
- progress；
- current source；
- time；
- retry；
- cancel；
- error details；
- checkpoint；
- provider；
- disk usage。

实时更新可用 SSE，不要求 WebSocket。

---

## 7. Review Model

```text
review_state:
  unreviewed
  needs_review
  approved
  rejected
  archived

action_intent:
  keep
  merge
  split
  replace
  reindex
  retag
  restrict
```

Review Decision：

```text
review_id
asset/revision/group id
review_state
action_intent
reason_code
comment
actor
revision_token
created_at
supersedes_review_id
```

历史不可覆盖，只能新增 superseding decision。

---

## 8. Batch Operations

允许：

- set tags；
- set review state；
- set confidentiality；
- request enrichment；
- add to review pack；
- export metadata；
- mark source group；
- resolve homogeneous findings。

不允许批量：

- delete source assets；
- merge ambiguous assets；
- change canonical ids；
- remove lineage；
- downgrade confidentiality without explicit elevated confirmation。

---

## 9. Local Audit

记录：

```text
workbench.session.started
asset.reviewed
asset.metadata.updated
duplicate.confirmed
duplicate.split
family.representative.changed
health.resolved
job.retry.requested
job.cancel.requested
```

Local audit 默认保留 90 天，可配置。不得记录完整页面正文。

---

## 10. 性能与可用性

目标：

- 50k slide Dashboard 首屏 ≤ 2s；
- Search UI 首批结果 ≤ backend P95 + 300ms；
- Asset Detail ≤ 1s（已存在 preview）；
- 1000 items filter 不阻塞浏览器；
- 长列表虚拟化或分页；
- preview lazy load；
- API response 有 pagination；
- 不把 embedding 传给浏览器。

---

## 11. Accessibility

最低：

- 键盘导航；
- 可见 focus；
- 图片 alt/标题；
- 对比度；
- 非颜色唯一编码；
- 表单 label；
- 错误提示可读；
- 缩放 200% 可用。

---

## 12. Packaging

新增 optional extra：

```toml
workbench = [
  "fastapi>=...",
  "uvicorn>=...",
  "jinja2>=..."
]
```

安装：

```bash
uv tool install "ppt-library[workbench]"
```

未安装 extra 时：

```bash
ppt-lib workbench start
```

返回明确错误和安装命令，不出现 import traceback。

---

## 13. API Contract

API 使用 Envelope v2，OpenAPI 自动生成但不能替代手写领域 Contract。

版本策略：

- `/api/v1` 在 v1.8～v1.9 稳定；
- v2.0 可继续保留；
- breaking change 新增 `/api/v2`；
- UI 通过公开 API，不调用内部 Python 对象。

---

## 14. 安全

- bind localhost；
- one-time bootstrap；
- HttpOnly、SameSite session；
- CSRF；
- no directory listing；
- CSP；
- path traversal protection；
- source file open 需 allowlist；
- HTML preview escape；
- OCR/metadata 按不可信内容处理；
- remote bind 风险提示；
- no secret display；
- session expiry；
- request size limit。

---

## 15. Testing

### Unit

- API validation；
- revision token conflict；
- review append-only；
- session/CSRF；
- pagination；
- batch safety；
- path allowlist。

### Integration

- start/stop；
- Dashboard；
- search；
- asset update；
- duplicate confirm/split；
- health resolution；
- job retry/cancel；
- provider status；
- wheel packaged assets。

### Browser E2E

建议 Playwright：

- first launch；
- search and open；
- approve asset；
- compare duplicate；
- resolve finding；
- retry job；
- session expiration；
- keyboard critical flow。

### Visual Regression

只对 UI shell/critical page，不把客户截图提交仓库，使用合成 preview。

---

## 16. 发布门禁

1. 所有核心操作不直接 SQL；
2. API 与 CLI 领域结果一致；
3. Browser E2E 通过；
4. localhost security tests 通过；
5. 50k performance gate；
6. asset write concurrency conflict 正确；
7. package clean install；
8. Workbench 未安装时 CLI 其余功能不受影响；
9. no customer data in screenshots；
10. UI 不能绕过 confidentiality 和 hard policy。

---

## 17. 验收场景

### AC-01 审批资产

用户搜索页面，打开大图，查看 source/score/health，设置 approved：

- 写入 append-only review；
- feedback event 记录；
- revision token 更新；
- 后续 search 可过滤 approved；
- CLI 查询结果一致。

### AC-02 重复拆分

系统建议两页 near duplicate，但实际为不同客户变体：

- 用户 compare；
- 选择 split/client_variant；
- manual override 保存；
- 后续自动 scan 不重新 merge；
- search 默认不会折叠为一个 exact duplicate。

### AC-03 Job 恢复

用户在 Workbench 看到 failed OCR job：

- 查看结构化错误；
- retry；
- job 从合适 stage 恢复；
- 无重复资产；
- audit event 存在。

---

## 18. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 1.8-A | Service Layer Completion | v1.7 |
| 1.8-B | API & Session Security | A |
| 1.8-C | Workbench Shell & Dashboard | B |
| 1.8-D | Search / Asset Detail | B、C |
| 1.8-E | Duplicate / Version Review | B、C |
| 1.8-F | Health / Job Monitor | B、C |
| 1.8-G | Batch / Audit / Accessibility | D～F |
| 1.8-H | Packaging / E2E / Release Gate | A～G |


---

<!-- SOURCE: 07-v1.9-team-preview-and-operations.md -->

# 07 — v1.9 Team Preview & Operational Hardening Spec

**Version:** 1.9.0
**Maturity Target:** Single-Tenant Team Preview
**Primary Goal:** 在不破坏 Local Mode 的前提下，提供可部署、可运维、可迁移的团队服务预览。
**Depends On:** v1.8 API/service layer；v1.7 governance；v1.6 retrieval
**Blocks:** v2.0 Enterprise GA

---

## 1. 版本结论

v1.9 不是多租户 SaaS。它是团队模式的架构验证版本：

- 单 Organization；
- 单或少量 Workspace；
- 5～20 名用户；
- Postgres + Object Store；
- API/Worker 分离；
- RBAC/Audit 基础；
- Local → Server 迁移；
- Docker Compose 部署；
- 有备份、恢复、监控和容量报告。

v1.9 必须先证明“同一业务核心可以稳定运行在服务器模式”，再进入 v2.0 多 Workspace 和企业治理。

---

## 2. 目标

### G1 — Repository Abstraction

Local SQLite 与 Server Postgres 通过同一 Repository Contract。

### G2 — Server Runtime

API、Worker、Scheduler、Storage 可独立运行和重启。

### G3 — Team Identity & RBAC Preview

支持用户、角色、API token 和基础权限。

### G4 — Audit & Operations

关键操作有审计，系统具备 health、metrics、backup、restore。

### G5 — Local-to-Server Migration

可将本地资产库、身份、lineage、feedback 和 blobs 安全迁移到 Server。

### G6 — Connector SDK Preview

定义 Source Connector Contract，并实现最小参考连接器。

---

## 3. 非目标

- 不提供公网 SaaS；
- 不做多租户计费；
- 不承诺复杂组织层级；
- 不在 v1.9 强制 SSO；
- 不做跨区域高可用；
- 不支持未经验证的 100+ 并发；
- 不允许 Server Mode 成为 Local Mode 的硬依赖；
- 不在 Preview 阶段承诺长期 API LTS。

---

## 4. 部署拓扑

```text
                        Browser / Agent / CLI
                                 │
                           Reverse Proxy
                                 │
                        ┌────────▼────────┐
                        │   API Service    │
                        │ Workbench + REST │
                        └───────┬─────────┘
                                │
               ┌────────────────┼────────────────┐
               │                │                │
        ┌──────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
        │ PostgreSQL   │  │ Object Store │  │ Vector     │
        │ metadata     │  │ screenshots  │  │ Backend    │
        └──────▲──────┘  └──────▲──────┘  └─────▲──────┘
               │                │                │
               └──────────┬─────┴────────────────┘
                          │
                    ┌─────▼─────┐
                    │ Worker(s)  │
                    │ jobs/index │
                    └─────┬─────┘
                          │
                    Connector Sources
```

最小 Docker Compose：

```text
api
worker
postgres
minio or compatible
vector backend (optional; pgvector/local service)
reverse proxy (optional local)
```

---

## 5. Storage Strategy

### 5.1 Metadata

Postgres 保存：

- workspace/source；
- assets/revisions；
- jobs/events；
- search documents；
- classifications；
- feedback；
- health；
- users/roles；
- audit；
- migrations。

### 5.2 Object Store

保存：

- screenshots；
- OCR markdown；
- preview；
- review packs；
- staging artifacts；
- asset packs；
- benchmark artifacts。

对象 key 不包含客户名称明文，使用 opaque identity：

```text
workspaces/<workspace_id>/assets/<revision_id>/<artifact_type>/<hash>
```

### 5.3 Vector Backend

Preview 支持两个选项：

```text
pgvector
external compatible backend
```

具体默认需 ADR。要求：

- backend abstraction；
- index version；
- rebuild/activate；
- workspace filter；
- backup/rebuild strategy；
- query explain metadata。

---

## 6. Repository Contract Tests

同一行为测试必须对：

- SQLite Local；
- Postgres Server。

覆盖：

```text
transaction
idempotency
identity uniqueness
feedback replay
manual override
search filter
pagination
job locking
optimistic concurrency
migration
```

不得出现“Server 模式另写一套业务逻辑”。

---

## 7. Job Runtime

### 7.1 Queue

Preview 可采用数据库队列，避免过早引入复杂消息系统。要求：

- `FOR UPDATE SKIP LOCKED` 或等价；
- lease；
- heartbeat；
- stale job reclaim；
- retry/backoff；
- cancellation；
- worker capability；
- per-provider concurrency；
- workspace quotas。

### 7.2 Worker

Worker 声明 capability：

```text
renderer
paddleocr
embedding
reranker
connector
```

Job 调度只发送到满足 capability 的 worker。

### 7.3 Isolation

- 每个 Job 独立 temp/staging；
- resource limit；
- renderer timeout；
- source secret 仅在执行时注入；
- result 先 staging 后 transaction commit；
- worker 崩溃由 lease 恢复。

---

## 8. Identity & RBAC Preview

### 8.1 Users

```text
user_id
email/login
display_name
status
created_at
last_login_at
```

认证 Preview：

- local admin bootstrap；
- password hash 或 external reverse proxy identity；
- API token；
- v2.0 引入 OIDC。

### 8.2 Roles

```text
admin
asset_manager
contributor
reviewer
viewer
service_account
```

### 8.3 Permissions

```text
source.read/write
asset.read/write/review
feedback.write
job.read/manage
settings.read/write
user.manage
audit.read
export.create
```

所有 API write endpoint 有 permission test。

---

## 9. Audit

Audit 事件与运行 event 分离：

```text
audit_id
actor
action
resource_type
resource_id
workspace_id
request_id
before_hash
after_hash
metadata
occurred_at
source_ip
```

必须审计：

- 登录和 token；
- user/role；
- source；
- confidentiality；
- review；
- duplicate merge/split；
- representative change；
- export；
- migration；
- backup/restore；
- settings/provider；
- connector secret change。

Audit 不保存密钥和完整页面正文。

---

## 10. Secrets

Server secrets：

- env/secret file；
- Docker secret；
- external secret manager adapter 预留。

不得：

- 写入数据库明文；
- 返回 API；
- 写入 audit；
- 打进 support bundle。

Connector credentials 使用 encrypted reference，具体 encryption key 由部署方提供。

---

## 11. Local-to-Server Migration

### 11.1 Export

Local：

```bash
ppt-lib migrate-to-server export \
  --output library-transfer.plpack \
  --include-blobs \
  --encrypt
```

包含：

- schema manifest；
- identities；
- source metadata；
- assets/revisions；
- lineage；
- classifications；
- feedback；
- health；
- blobs；
- checksums；
- redaction policy。

### 11.2 Import

Server：

```bash
ppt-lib-server import \
  --workspace <id> \
  --input library-transfer.plpack \
  --dry-run
```

Dry-run 报告：

- counts；
- id conflicts；
- missing blobs；
- unsupported schema；
- policy conflicts；
- estimated storage；
- remapping；
- duplicate candidates。

Apply：

- transaction + staged blobs；
- import journal；
- resumable；
- idempotent；
- rollback before finalization。

---

## 12. Connector SDK Preview

### 12.1 Contract

```python
class SourceConnector(Protocol):
    def capabilities(self) -> ConnectorCapabilities: ...
    def list_changes(self, cursor: str | None) -> ChangePage: ...
    def fetch_file(self, item_id: str, revision: str) -> BinaryAsset: ...
    def resolve_locator(self, item_id: str) -> SourceLocator: ...
    def test_connection(self) -> HealthResult: ...
```

### 12.2 Change Model

```text
created
updated
deleted
moved
permission_changed
```

### 12.3 Reference Connectors

至少：

1. local/NAS filesystem；
2. generic HTTP manifest 或 S3-compatible bucket。

SharePoint/Google Drive/飞书放到 v2.0 reference connector，除非已有可靠实现。

### 12.4 Cursor

- opaque cursor；
- idempotent page；
- restart safe；
- permission errors explicit；
- deletions tombstone；
- source revision preserved。

---

## 13. Backup & Restore

### 13.1 Backup

包含：

- Postgres logical/physical strategy；
- object manifest；
- config sans secrets；
- schema version；
- vector rebuild metadata；
- audit checkpoint。

### 13.2 Restore

必须有：

- documented RPO/RTO target；
- isolated restore validation；
- checksum；
- database + object consistency；
- vector index rebuild；
- restore report。

Preview 目标：

```text
RPO <= 24h
RTO <= 4h（参考环境）
```

这不是生产 SLA，但必须实测。

---

## 14. Observability

### 14.1 Health

```text
/health/live
/health/ready
/health/dependencies
```

### 14.2 Metrics

- API latency/status；
- search latency；
- job queue depth；
- stage duration；
- job failures；
- provider errors；
- DB pool；
- object storage；
- vector latency；
- worker heartbeat；
- connector lag；
- storage usage。

### 14.3 Logs

JSON logs：

```text
timestamp
level
service
request_id
job_id
workspace_id
event
code
duration
```

不记录 query/full text，除非 debug + redaction。

---

## 15. Capacity Target

Reference Preview：

```text
250k slides
20 concurrent users
4 concurrent index jobs
P95 search <= 2s
P95 asset API <= 1s
job recovery <= 2 lease periods
```

容量报告需记录硬件和 backend。

---

## 16. Security Preview

- TLS behind reverse proxy；
- password/token hashing；
- rate limits；
- request body limits；
- CORS default deny；
- CSRF for browser；
- SSRF protection for connectors；
- source allowlists；
- signed blob URL；
- permission tests；
- audit；
- dependency scan；
- container non-root；
- image vulnerability scan；
- backup encryption option。

---

## 17. CLI / Server Commands

```bash
ppt-lib server-config validate
ppt-lib server doctor
ppt-lib server users bootstrap-admin
ppt-lib server tokens create
ppt-lib server backup create
ppt-lib server backup verify
ppt-lib server restore plan
ppt-lib server connectors list
ppt-lib server connectors test <id>
ppt-lib migrate-to-server export
```

具体命令名实施时可调整，但必须有单一运维入口。

---

## 18. Database Changes

建议 Server Schema `9` 或独立 migration lineage，编号由实现核验。

新增：

```text
organizations_preview
workspaces
users
roles
permissions
user_roles
api_tokens
audit_events
connector_instances
connector_cursors
worker_instances
job_leases
backup_catalog
import_journals
```

Local DB 不需要用户表成为硬依赖。

---

## 19. Testing

### Repository Contract

SQLite/Postgres 同套行为测试。

### Deployment Integration

- clean compose up；
- bootstrap admin；
- index synthetic assets；
- search；
- workbench；
- worker restart；
- DB restart；
- object store restart；
- backup/restore；
- local import；
- upgrade RC1→RC2。

### Security

- permission matrix；
- token revoke；
- CSRF/CORS；
- connector SSRF；
- signed URL；
- audit coverage；
- secret redaction；
- non-root containers。

### Load

- 250k search；
- 20 users；
- 4 jobs；
- worker loss；
- long OCR；
- queue fairness。

---

## 20. 发布门禁

1. Local Mode 全量回归；
2. Repository contract 100%；
3. Docker Compose clean deploy；
4. migration/import round-trip；
5. backup/restore drill；
6. RBAC matrix；
7. audit coverage；
8. 250k capacity report；
9. worker failure recovery；
10. P0 security findings 关闭；
11. Preview 标签和已知限制明确；
12. 不宣称多租户 Enterprise GA。

---

## 21. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 1.9-A | Repository Interfaces & Postgres | v1.8 |
| 1.9-B | Object/Vector Storage Adapters | A |
| 1.9-C | Queue / Worker / Leases | A、B |
| 1.9-D | Users / RBAC / Tokens | A |
| 1.9-E | Audit / Secrets / Security | D |
| 1.9-F | Local-to-Server Migration | A、B |
| 1.9-G | Connector SDK & References | C、E |
| 1.9-H | Deploy / Backup / Observability / Load | A～G |


---

<!-- SOURCE: 08-v2.0-team-enterprise-ga.md -->

# 08 — v2.0 Team / Enterprise GA Spec

**Version:** 2.0.0
**Maturity Target:** Dual-Mode General Availability
**Primary Goal:** 发布可长期维护的 Local + Team/Enterprise 双模 PPT Asset Intelligence 产品。
**Depends On:** v1.9 Team Preview evidence
**Contract Impact:** Envelope v2 / stable API & SDK policy

---

## 1. v2.0 发布定义

v2.0 不是“功能更多”的版本，而是以下承诺同时成立：

1. Local Mode 仍然简单、私密、无需服务器；
2. Team Mode 具备多 Workspace、SSO、权限、审计、备份和升级；
3. 搜索、资产身份、lineage 和 feedback 有稳定质量门；
4. API、CLI、Contract 和 Schema 进入明确支持政策；
5. 企业部署有可验证的安全和运维边界；
6. 上层 Agent 可以稳定集成；
7. 从 v1.4.1～v1.9 有迁移路径。

---

## 2. 目标

### G1 — Multi-Workspace

一个部署支持多个隔离 Workspace。

### G2 — Enterprise Identity

OIDC/SSO、用户生命周期、Service Account、细粒度 RBAC。

### G3 — Governance Policy

保密、外发、保留、导出、审批和连接器策略。

### G4 — Approval & Asset Promotion

资产从个人/项目空间进入团队 Approved Library 的可审计流程。

### G5 — Enterprise Connectors

提供稳定 Connector SDK 和参考实现。

### G6 — Stable API/SDK

API v1、Contract、CLI 和 Python SDK 有版本政策和兼容测试。

### G7 — Operations

升级、回滚、备份、恢复、观测和容量分级。

### G8 — Analytics

检索、复用、资产健康和反馈有团队级指标，但不泄露内容。

---

## 3. 非目标

- 不承诺完全托管 SaaS；
- 不实现 PPT 在线编辑器；
- 不承担 Deck Master 的完整方案工作流；
- 不自动跨 Workspace 分享 confidential 资产；
- 不在默认安装中启用遥测；
- 不把客户正文用于公共模型训练；
- 不提供不可解释的自动资产淘汰；
- 不支持没有隔离测试的“超级管理员任意绕过”。

---

## 4. Workspace 与 Organization

```text
Organization
 ├── Workspace A
 ├── Workspace B
 └── Shared Approved Library
```

Workspace 包含：

- sources；
- assets；
- jobs；
- search profiles；
- policies；
- users/roles；
- connectors；
- audit scope；
- retention；
- encryption reference；
- usage metrics。

隔离要求：

- metadata query 必须带 workspace scope；
- vector query 必须有 workspace filter；
- blob key/URL 必须隔离；
- cache 必须隔离；
- audit 必须隔离；
- backup/restore 可按 workspace；
- automated cross-workspace tests。

---

## 5. Enterprise Identity

### 5.1 OIDC

支持：

- Authorization Code + PKCE；
- issuer discovery；
- JWKS rotation；
- group/claim mapping；
- session timeout；
- logout；
- disabled user；
- clock skew；
- service account token。

### 5.2 Provisioning

v2.0 至少支持：

- JIT provisioning；
- admin disable；
- role mapping；
- invite/local break-glass admin。

SCIM 可列为后续，除非实施资源充足。

### 5.3 Roles

内置：

```text
org_admin
workspace_admin
asset_manager
reviewer
contributor
viewer
auditor
service_account
```

支持自定义 role 由权限集合组成。

---

## 6. Policy Engine

### 6.1 Policy Types

```text
provider_egress
confidentiality
retention
export
connector
review
asset_promotion
search_visibility
audit_retention
job_quota
```

### 6.2 Example

```yaml
policy: provider_egress
workspace: ws_client_a
rules:
  - when:
      confidentiality: [restricted, client_confidential]
    allow_providers: [local]
  - when:
      confidentiality: [internal]
    allow_providers: [local, approved_cloud]
```

### 6.3 Enforcement

Policy 必须在：

- index provider call；
- rerank；
- export；
- search；
- cross-workspace promotion；
- connector fetch；
- support bundle；

执行。UI 提示不能替代后端 enforcement。

---

## 7. Approval & Promotion

资产状态：

```text
draft
review_requested
approved
rejected
deprecated
archived
```

Promotion：

```text
workspace asset
→ review request
→ metadata/health/confidentiality validation
→ reviewer approval
→ shared approved library
```

要求：

- source provenance；
- review evidence；
- no unresolved high-severity finding；
- policy compatible；
- canonical/revision identity preserved；
- promotion creates lineage/reference，不复制失去关系；
- approval can expire；
- revoke/rollback；
- audit。

---

## 8. Shared Approved Library

共享库不等于所有 Workspace 可读：

- 可按 organization/workspace/group 授权；
- confidential asset 默认不可 promotion；
- client-specific variants 默认不进入通用库；
- search 可选择 local/shared/both；
- shared candidate 显示来源和使用限制；
- local feedback 和 shared feedback 分层聚合。

---

## 9. Connector Framework GA

### 9.1 Stable SDK

定义：

```text
ConnectorCapabilities
ConnectorItem
ConnectorRevision
ChangePage
BinaryAsset
PermissionSnapshot
HealthResult
ConnectorError
```

### 9.2 Reference Connectors

v2.0 至少交付两种企业常见来源的参考实现，候选：

- SharePoint/OneDrive；
- Google Drive；
- Feishu Drive；
- S3/NAS。

最终选择需根据真实用户优先级和 API 稳定性形成 ADR。

### 9.3 Connector Requirements

- incremental cursor；
- revision identity；
- deletion；
- move/rename；
- permission change；
- retry/backoff；
- rate limit；
- secret reference；
- test connection；
- least privilege；
- audit；
- source policy mapping。

### 9.4 Unsupported Files

连接器可发现非 PPTX 文件，但 PPT Library v2.0 只摄取支持格式；必须报告 skipped reason，不得无提示忽略。

---

## 10. Search & Intelligence GA

### 10.1 Search

- profile stable；
- workspace/shared scope；
- policy filter；
- explain；
- query trace；
- backend health；
- reranker egress；
- protected query tests；
- no cross-workspace leak。

### 10.2 Intelligence

- near duplicate；
- lineage；
- review；
- feedback；
- health；
- representative；
- classification provenance；
- manual override。

### 10.3 Quality Gate

v2.0 发布基准：

```text
Recall@10 >= 0.88
MRR >= 0.70
nDCG@10 >= 0.80
Top-5 useful rate >= 0.75
duplicate candidate rate <= 0.05
cross-workspace leakage = 0
```

---

## 11. Team Analytics

只提供聚合，不默认展示客户正文：

- search volume；
- no-result；
- useful/selected rate；
- top rejected reasons；
- approved asset reuse；
- health backlog；
- source freshness；
- index failures；
- connector lag；
- policy blocks；
- feedback coverage；
- asset promotion throughput。

Analytics 必须可按角色限制。

---

## 12. Enterprise Export

导出类型：

```text
candidate selection
review pack
asset pack
audit export
health report
benchmark report
support bundle
```

每次导出：

- policy check；
- actor；
- scope；
- content inventory；
- checksum；
- expiry；
- audit；
- optional encryption；
- path redaction。

Support bundle 默认不含：

- slide body；
- screenshots；
- tokens；
- customer paths；
- query text。

---

## 13. Deployment

### 13.1 Reference

- Docker Compose：小团队；
- Helm/Kubernetes：企业参考；
- external Postgres/Object Store 支持；
- ingress/TLS；
- secret manager；
- worker autoscaling guide；
- storage sizing；
- upgrade job；
- readiness/liveness；
- Pod disruption guidance。

### 13.2 Capacity Tiers

| Tier | Slides | Concurrent Users | Notes |
|---|---:|---:|---|
| Team | 250k | 20 | Compose |
| Enterprise | 500k | 50 | K8s reference |
| Extended | 1M | 100 | Remote vector backend and tuned infra |

这些是参考容量，不是无限扩展承诺。必须附硬件和配置。

---

## 14. SLO

建议 GA 目标：

| 服务 | 指标 |
|---|---|
| API availability | 99.5% monthly reference |
| Search P95 | ≤2s at Enterprise tier |
| Asset read P95 | ≤1s |
| Job claim delay P95 | ≤30s |
| RPO | ≤24h default，支持更低配置 |
| RTO | ≤4h reference |
| Audit write loss | 0 accepted operations |
| Cross-workspace leak | 0 |

若项目不提供托管服务，SLO 表述为参考部署可验证目标，不对所有用户环境作法律承诺。

---

## 15. Upgrade & Rollback

### 15.1 Upgrade

```text
preflight
backup
schema plan
maintenance/degraded mode
migrate
verify
rebuild derived indexes if needed
activate
post-upgrade smoke
```

### 15.2 Rollback

- application image rollback；
- schema backward compatibility window；
- destructive migration 仅在 backup + explicit confirmation；
- vector index independently switchable；
- object migrations additive；
- rollback guide。

### 15.3 Supported Paths

至少：

```text
1.8 local → 2.0 local
1.9 server → 2.0 server
1.4.1 → 1.5 → ... → 2.0
```

可提供直接 upgrade tool，但内部仍执行线性 migrations。

---

## 16. API/SDK Stability

### 16.1 REST

- `/api/v1` supported through 2.x；
- breaking change 使用 `/api/v2`；
- OpenAPI diff gate；
- pagination/filter semantics stable；
- structured error codes stable；
- idempotency for write APIs。

### 16.2 CLI

- 1.x commands compatibility；
- 2.0 Envelope v2 default for new/contract commands；
- legacy contract available；
- exit code policy documented。

### 16.3 Python SDK

发布：

```python
PPTLibraryClient
SearchRequest
SearchResponse
SelectionRequest
JobClient
AssetClient
```

SDK 与 Server/Local Adapter 可共用 Contract model。

---

## 17. Security GA

### Required

- OIDC；
- RBAC；
- workspace isolation；
- encrypted transport；
- secret handling；
- signed blob access；
- audit；
- rate limit；
- connector SSRF；
- dependency/container scan；
- SBOM；
- provenance/attestation；
- backup encryption；
- security advisory process；
- threat model；
- penetration testing or equivalent independent review；
- P0/P1 closure。

### Data Governance

- retention；
- deletion；
- export；
- audit retention；
- data residency deployment guidance；
- provider egress；
- confidentiality；
- workspace backup；
- legal hold 可作为后续，除非目标客户要求。

---

## 18. Documentation GA

必须交付：

```text
Quick Start Local
Quick Start Team
Upgrade Guide
Migration Guide
Operator Guide
Backup/Restore
Security Guide
Policy Guide
Connector SDK
REST API
Python SDK
Deck Master Integration
Troubleshooting
Capacity Planning
Release/Support Policy
```

---

## 19. Support Policy

建议：

- v2.0 GA；
- 当前 minor 支持；
- 安全修复策略；
- migration support；
- deprecation window；
- schema compatibility；
- connector compatibility；
- provider support tier；
- known limitations。

公开项目不应暗示提供付费 SLA，除非实际存在。

---

## 20. Testing

### Isolation

- workspace metadata；
- vector；
- blob；
- cache；
- audit；
- export；
- connector；
- analytics。

### Identity

- OIDC claims；
- role mapping；
- disabled user；
- service account；
- break-glass admin；
- token rotation。

### Governance

- egress block；
- confidentiality；
- approval；
- promotion；
- revoke；
- retention；
- export。

### Operations

- rolling upgrade；
- worker scale；
- DB fail/restart；
- object store failure；
- backup/restore；
- schema failure；
- vector rebuild；
- connector rate limit。

### Load

- tiered datasets；
- mixed search/read/write；
- index jobs；
- audit；
- analytics；
- failure injection。

---

## 21. v2.0 发布硬门

v2.0 只有以下全部满足才可 GA：

1. v1.9 Preview P0/P1 关闭；
2. Local Mode 无回归；
3. Multi-workspace isolation 全通过；
4. OIDC/RBAC/Audit 全通过；
5. Search quality 达标；
6. 500k/50-user reference capacity 达标；
7. Backup/restore drill；
8. Upgrade/rollback drill；
9. Connector reference tests；
10. Contract/API/SDK diff gate；
11. SBOM、安全扫描和独立安全评审；
12. 文档完整；
13. 无真实客户数据进入公开 fixture；
14. Release Candidate 在真实非生产环境完成验证；
15. Owner 签署 GA checklist。

---

## 22. v2.0 交付物

```text
Local distribution
Team server distribution
Docker Compose
Helm reference
API/SDK
OIDC/RBAC
Policy engine
Approval/promotion
Reference connectors
Analytics
Backup/restore
Upgrade/rollback
Benchmark reports
Security package
GA docs
```

---

## 23. Agent 任务拆分摘要

| ID | 任务 | 依赖 |
|---|---|---|
| 2.0-A | Organization / Workspace Isolation | v1.9 |
| 2.0-B | OIDC / Identity Lifecycle | A |
| 2.0-C | Policy Engine | A、B |
| 2.0-D | Approval / Promotion / Shared Library | A、C |
| 2.0-E | Connector SDK GA + References | A、C |
| 2.0-F | Analytics / Audit Export | A、D |
| 2.0-G | Deployment / Upgrade / DR | A～F |
| 2.0-H | API/SDK Freeze / Security / GA Gate | A～G |


---

<!-- SOURCE: 09-data-schema-migrations-and-identity.md -->

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


---

<!-- SOURCE: 10-benchmark-quality-gates-and-test-matrix.md -->

# 10 — Benchmark、质量门与测试矩阵

---

## 1. 原则

自动化测试回答“代码是否按预期运行”，Benchmark 回答“产品效果是否足够好”。

两者必须同时存在：

```text
Correctness Tests
+ Contract Tests
+ Failure Tests
+ Retrieval/Intelligence Benchmark
+ Performance Tests
+ Human Review
= Release Evidence
```

测试数量不得作为成熟度唯一证据。

---

## 2. Benchmark Artifact

每次 benchmark 输出目录：

```text
benchmarks/runs/<run_id>/
├── manifest.json
├── environment.json
├── config.json
├── metrics.json
├── query-results.jsonl
├── failures.jsonl
├── timings.json
├── comparison.json
└── report.html
```

Manifest：

```text
run_id
suite
commit_sha
package_version
db_schema
dataset_hash
query_hash
search_profile_hash
provider/model versions
hardware/OS
started/finished
status
artifact hashes
```

---

## 3. 数据集

### 3.1 Synthetic Public

用途：

- CI；
- Contract；
- failure；
- known patterns；
- open-source reproducibility。

内容：

- 多版本 Deck；
- exact/near duplicates；
- client variants；
- visual-heavy pages；
- Chinese/English；
- tables/charts；
- source missing；
- confidentiality labels；
- corrupted PPTX；
- large archive safety。

### 3.2 Private Golden

用途：

- 真实质量；
- 发布决策；
- 行业覆盖。

要求：

- 不入仓库；
- manifest 仅记录 hash；
- query 与 label 由 Owner 管理；
- 结果只发布聚合；
- reviewer guideline；
- sample drift 监控。

### 3.3 Anonymized Release

可选，用于在不泄露客户内容的情况下保留真实分布。

---

## 4. Retrieval Benchmark

### 4.1 Query Labels

每条 query：

```text
query_id
query
context
hard_filters
relevant canonical assets
graded relevance 0/1/2/3
protected
notes
```

### 4.2 指标

```text
Recall@5/10
Precision@5
MRR
nDCG@10
Hit Rate
No-result Rate
Duplicate Candidate Rate
Representative Version Rate
Protected Query Pass
```

### 4.3 Human Useful Rate

Reviewer 查看 Top-5，判断：

```text
usable as-is
usable with adaptation
reference only
not useful
unsafe
```

`usable as-is` + `usable with adaptation` 计入 useful。

---

## 5. Duplicate / Lineage Benchmark

### Pair Metrics

- precision；
- recall；
- F1；
- false merge；
- false split；
- client variant confusion。

### Family Metrics

- family purity；
- family completeness；
- representative accuracy；
- manual override preservation。

### Lineage Metrics

- relation accuracy；
- direction accuracy；
- supersede accuracy；
- edge confidence calibration。

---

## 6. Classification Benchmark

每维度独立：

```text
page archetype
narrative role
industry
scenario
confidentiality suggestion
evidence type
health finding
```

指标：

- macro/micro F1；
- coverage；
- abstention rate；
- calibration；
- manual correction rate。

模型可选择 abstain，不要求错误地填满所有标签。

---

## 7. Index Reliability Benchmark

场景：

- 10/100/1000 Deck；
- text-only；
- renderer；
- OCR；
- mixed providers；
- worker restart；
- endpoint rate limit；
- source changes；
- duplicate files；
- file moves；
- disk pressure；
- corrupt archives。

指标：

```text
success rate
slides/minute
resume success
duplicate writes
failed job diagnosis coverage
peak disk
peak memory
provider calls
```

---

## 8. Scale Benchmark

### Dataset Tiers

```text
10k
50k
100k
250k server
500k server
1M extended
```

### Workload

- warm/cold search；
- filter search；
- explain；
- asset detail；
- duplicate review list；
- concurrent jobs；
- connector sync；
- export；
- feedback write。

### Metrics

```text
P50/P95/P99 latency
throughput
error rate
CPU
memory
disk IO
DB query time
vector time
queue lag
```

---

## 9. Release Gate by Version

### v1.5

- Contract UAT 100%；
- index success ≥99%；
- crash resume 100% fixtures；
- migration pass；
- duplicate writes 0；
- 10k index report。

### v1.6

- Recall@10 ≥0.85；
- MRR ≥0.65；
- nDCG@10 ≥0.75；
- useful rate ≥0.70；
- duplicate candidate ≤0.10；
- 100k performance target。

### v1.7

- duplicate precision ≥0.95；
- recall ≥0.85；
- client variant false merge ≤0.02；
- feedback idempotency 100%；
- manual override 100%。

### v1.8

- browser critical E2E 100%；
- 50k UI target；
- write conflict tests；
- security tests；
- accessibility critical issues 0。

### v1.9

- SQLite/Postgres repository contract 100%；
- 250k/20-user；
- backup/restore；
- worker recovery；
- RBAC/Audit coverage；
- Local Mode regression。

### v2.0

- Retrieval enhanced targets；
- 500k/50-user；
- workspace leakage 0；
- OIDC/RBAC/Policy；
- upgrade/rollback；
- security review；
- GA checklist。

---

## 10. Test Pyramid

```text
Unit
  deterministic functions / state machines / metrics

Component
  DB repositories / providers / contracts

Integration
  CLI / API / jobs / migrations / storage

End-to-End
  index → search → review → selection → feedback

Benchmark
  relevance / intelligence / scale

Operational
  deploy / upgrade / backup / restore / failure

Security
  auth / isolation / parsing / secrets / supply chain
```

---

## 11. CI 分层

### PR Fast

- unit；
- lint/type；
- contract；
- small migration；
- synthetic smoke；
- benchmark regression-smoke。

### Main

- full tests；
- wheel build；
- platform smoke；
- medium benchmark；
- Workbench E2E；
- security scan。

### Release Candidate

- private golden；
- 10k/50k/100k；
- migration matrix；
- package install matrix；
- external provider smoke；
- Server load（v1.9+）；
- backup/restore；
- security review。

---

## 12. Provider Tests

Provider 测试分：

```text
mock contract
local fake deterministic
optional real smoke
```

Real smoke：

- 由 secret-enabled job 运行；
- 不使用客户数据；
- 只验证 capability/response；
- 不作为普通 fork PR 必须条件；
- release 前必须有至少推荐 Provider 的真实 smoke。

---

## 13. Platform Matrix

| 能力 | macOS | Ubuntu | Windows |
|---|---|---|---|
| install/CLI | Tier-1 | Tier-1 | v1.5 Tier-2，v2.0 Tier-1 |
| text extraction | 必须 | 必须 | 必须 |
| SQLite/FTS | 必须 | 必须 | 必须 |
| local ANN | 必须 | 必须 | 必须 |
| LibreOffice render | 必须验证 | 必须验证 | 可分级 |
| Workbench | 必须 | 必须 | 必须 |
| Server | Docker/K8s client | Tier-1 host | client |

---

## 14. Regression Baseline

Benchmark 比较：

```text
baseline run
candidate run
absolute delta
relative delta
confidence
protected failures
accepted regressions ADR
```

禁止只比较总体平均而隐藏关键 query 失败。

---

## 15. Protected Queries

标记为 protected 的 query：

- 关键业务页面；
- 安全/保密过滤；
- Deck Master 核心角色；
- exact source；
- known regression。

任何 protected query 失败默认阻断，即使总体指标达标。

---

## 16. Flakiness

- deterministic fake providers；
- random seed；
- hardware-sensitive test 单独标记；
- retry 不能掩盖 deterministic failure；
- flaky test 有 owner、issue 和 deadline；
- release gate 不允许未知 flaky。

---

## 17. Benchmark CLI

```bash
ppt-lib benchmark list
ppt-lib benchmark validate <suite>
ppt-lib benchmark run --suite regression-smoke
ppt-lib benchmark run --suite release
ppt-lib benchmark compare <baseline> <candidate>
ppt-lib benchmark report <run-id> --html
ppt-lib benchmark promote-baseline <run-id>
```

Promote baseline 需要人工确认和 change note。

---

## 18. QA 报告

每个版本发布包必须包含：

```text
test summary
contract summary
migration summary
benchmark summary
performance summary
platform matrix
security summary
known limitations
waivers/ADRs
```

不得只写“全部测试通过”。

---

## 19. Review Calibration

人工评审指南需定义：

- useful；
- duplicate；
- client variant；
- representative；
- health severity；
- confidentiality。

计算 reviewer agreement；争议样本进入 adjudication，不把不一致标签直接当真值。

---

## 20. Benchmark 数据安全

- public suite 仅合成数据；
- private suite 不复制进 artifact；
- report 默认隐藏正文和路径；
- query 可 hash 或 redact；
- screenshot 不公开；
- model request/response 不落公开日志；
- benchmark bundle release 前执行 privacy scan。


---

<!-- SOURCE: 11-security-privacy-and-governance.md -->

# 11 — Security、Privacy 与 Governance Spec

---

## 1. 安全目标

PPT Library 处理的通常是客户方案、投标材料、商业数据和内部方法论。安全目标不是“仓库里没有 API key”这么简单，而是：

1. 不越权扫描；
2. 不无提示外发；
3. 不执行 PPT 中的恶意内容；
4. 不泄露路径、正文、截图和查询；
5. 不因自动去重、迁移或清理造成数据损坏；
6. Team Mode 不跨 Workspace 泄漏；
7. 所有高风险行为可审计。

---

## 2. Trust Boundaries

```text
Untrusted PPTX / Source
        ↓
Parser / Renderer Sandbox Boundary
        ↓
Local Staging
        ↓
Metadata / Blob Store

Local App Boundary
        ↔ Optional Model Providers

Browser Boundary
        ↔ Workbench API

Team Network Boundary
        ↔ API / Worker / Connector / Storage
```

每个 Boundary 必须有输入验证和结构化错误。

---

## 3. Source Consent

- 首次 sources 必须 manifest；
- scan dry-run；
- risky source explicit confirmation；
- connector scope 显示；
- folder/file allowlist；
- excludes；
- source policy；
- 不得默认扫描 Home、Downloads、聊天缓存、回收站、依赖目录；
- Agent 必须把扫描范围汇报给用户。

Team Mode connector 需要 least privilege。

---

## 4. PPTX Threats

### 威胁

- zip bomb；
- path traversal；
- oversized XML/media；
- malformed relationships；
- external links；
- embedded OLE；
- macros/active content；
- renderer exploit；
- formula/external workbook；
- metadata leakage。

### 要求

- archive limits；
- safe XML parser；
- relationship validation；
- no executable launch；
- renderer timeout；
- temp isolation；
- non-root server worker；
- external relationship inventory；
- embedded object warning；
- size limits；
- content hash；
- corrupt file quarantine。

---

## 5. Model Egress

### Provider Classification

```text
local
approved_private
approved_cloud
unapproved
```

每个 provider：

- egress flag；
- endpoint；
- retention note；
- model；
- data sent；
- secret source；
- policy compatibility。

### Enforcement

restricted/client_confidential：

- 默认 local only；
- policy 可放宽；
- UI 提示不代替后端阻断；
- rerank/vision/embedding 分别检查；
- query expansion 也属于外发。

### Data Minimization

- 优先发送必要页面/摘要；
- 可配置不发送截图；
- cloud provider request 不记录完整 payload；
- support bundle 不含 model payload。

---

## 6. Secrets

Local：

- env；
- OS keyring 可选；
- `.env` 不提交；
- config 仅写 secret reference。

Server：

- secret file/Docker/K8s/external manager；
- rotation；
- no API exposure；
- no audit/log；
- encrypted connector credential reference；
- break-glass procedure。

---

## 7. Logs and Telemetry

默认日志不包含：

- full source path（可配置 local debug）；
-客户名称；
-正文；
- OCR；
- query；
-截图；
- token；
- provider payload。

使用 opaque ids 和 error codes。

遥测：

- 默认关闭；
- 明确 opt-in；
- 只发送聚合运行指标；
- 设置页可查看发送字段；
- enterprise 可完全禁用。

---

## 8. Workbench Security

- localhost default；
- bootstrap token；
- secure session；
- CSRF；
- CSP；
- XSS escape；
- OCR/metadata untrusted；
- path allowlist；
- file open confirmation；
- request limits；
- session timeout；
- remote bind explicit；
- no directory traversal；
- static asset integrity。

---

## 9. Server Security

- TLS；
- OIDC；
- RBAC；
- workspace scope；
- API token hash；
- rate limits；
- audit；
- signed blob URL；
- CORS deny；
- CSRF browser；
- SSRF connector；
- egress allowlist；
- non-root containers；
- network segmentation；
- DB least privilege；
- storage bucket policy；
- backup encryption；
- vulnerability scan。

---

## 10. Confidentiality Governance

```text
public
internal
client_confidential
restricted
unknown
```

Policy 决定：

- who can read；
- provider egress；
- export；
- shared promotion；
- retention；
- screenshot display；
- audit requirement。

Unknown 默认按较保守策略处理。

---

## 11. Deletion and Retention

- archive/tombstone 优先；
- hard delete dry-run；
- blob inventory；
- audit；
- retention policy；
- backup implications；
- canonical id 不复用；
- connector deletion 不立即等于 hard delete；
- source loss 与 user deletion 区分。

---

## 12. Audit Coverage

必须覆盖：

```text
auth/token
user/role
source/connector
policy
confidentiality
review
duplicate merge/split
lineage change
export
migration
backup/restore
provider config
asset promotion
hard delete
```

Audit append-only，应用角色不可修改旧记录。

---

## 13. Supply Chain

- pinned lockfile；
- dependency review；
- SBOM；
- vulnerability scan；
- signed/attested release；
- trusted publishing；
- container scan；
- minimal base images；
- release artifact hashes；
- no bundled font redistribution；
- third-party license inventory。

---

## 14. Security Testing

- malicious PPTX fixtures；
- zip bomb limits；
- traversal；
- XSS via OCR/title；
- SSRF；
- CSRF；
- CORS；
- auth bypass；
- workspace leak；
- signed URL scope；
- token revoke；
- secret redaction；
- audit completeness；
- backup encryption；
- dependency scan。

---

## 15. Threat Model Artifacts

每个 major Wave 更新：

```text
assets
actors
trust boundaries
abuse cases
controls
residual risk
test mapping
```

v2.0 前进行独立安全评审或渗透测试，并记录修复。

---

## 16. Security Incident

文档定义：

- report channel；
- triage；
- severity；
- containment；
- token rotation；
- affected versions；
- advisory；
- patch/backport；
- user notification；
- postmortem。

公开 issue 不得包含 exploit、secret 或客户资产。

---

## 17. Security Gate by Version

### v1.5

- parser limits；
- render timeout；
- source change；
- contract safe write；
- secret scan；
- release SBOM。

### v1.6

- query trace redaction；
- reranker egress；
- backend fallback disclosure。

### v1.7

- confidentiality enforcement；
- feedback integrity；
- no automatic destructive merge。

### v1.8

- localhost/session/CSRF/XSS；
- path allowlist；
- browser E2E security。

### v1.9

- RBAC/Audit；
- connector SSRF；
- secret management；
- non-root deployment；
- backup security。

### v2.0

- OIDC；
- workspace isolation；
- policy engine；
- independent security review；
- signed GA artifacts。

---

## 18. Governance Gate

任何版本不得发布，如果：

- 发现跨 workspace leak；
- restricted 内容可被禁止 provider 处理；
- migration 可造成静默数据丢失；
- invalid contract 被写成成功；
- hard delete 无 dry-run/audit；
- secret 出现在日志/导出；
- release artifact 无来源和 hash；
- P0/P1 安全问题未关闭或未由 Owner 明确接受。


---

<!-- SOURCE: 12-release-rollout-and-backward-compatibility.md -->

# 12 — Release、Rollout 与 Backward Compatibility Spec

---

## 1. 发布原则

1. 每个 minor 版本都是可独立安装、迁移和回滚的产品版本。
2. 默认分支不等于已发布版本。
3. 版本号、VERSION、pyproject、CHANGELOG、release notes、Contract 和 DB Schema 必须一致。
4. Release Candidate 必须由 clean checkout 构建。
5. 不允许从包含私有历史/资产的开发仓直接推送公开 snapshot。
6. 测试通过不等于发布门全部通过。

---

## 2. 分支与 PR

建议：

```text
main
feature/v15-*
feature/v16-*
release/v1.5.0
```

每个 Agent Task 一个 PR 或可审查的逻辑组。

PR 必须包含：

- spec task id；
- scope；
- files changed；
- migration impact；
- contract impact；
- tests；
- benchmark delta；
- security impact；
- rollback；
- known limitations。

禁止把 v1.6 功能提前混入未稳定 v1.5 PR。

---

## 3. Feature Flags

实验能力：

```text
PPT_LIB_EXPERIMENTAL_JOB_ENGINE
PPT_LIB_EXPERIMENTAL_HYBRID_V2
PPT_LIB_EXPERIMENTAL_WORKBENCH
PPT_LIB_EXPERIMENTAL_SERVER
```

最终实现可使用配置而非 env，但要求：

- feature owner；
- default；
- removal version；
- telemetry/metric；
- fallback；
- test both states。

稳定后删除 flag，禁止永久双实现。

---

## 4. 发布阶段

```text
Development
→ Internal Alpha
→ Public/Private Preview
→ Release Candidate
→ GA
```

每阶段有明确 gate，不按日历自动推进。

### Release Candidate

- code freeze；
- schema freeze；
- contract freeze；
- benchmark；
- migration；
- packaging；
- docs；
- known limitations；
- upgrade/rollback；
- security scan。

---

## 5. SemVer

### Patch

- Bug/security；
- 不新增 breaking schema；
- 不改变 stable contract；
- 可增加非破坏 warning。

### Minor

- 新能力；
- additive schema；
-新 contract；
- deprecated path；
- migration。

### Major

- stable contract breaking；
- default envelope breaking；
- dropped compatibility；
- deployment model major change。

v2.0 是 Contract/Support 承诺 major，不应仅因版本规划机械升级。

---

## 6. Cross-Repo Coordination

与 Deck Master：

- vendored canonical schema；
- Contract UAT；
- capability negotiation；
- compatibility matrix；
- release notes；
- no unversioned assumptions。

建议矩阵不绑定具体 Deck Master 版本号，而绑定 capability：

```text
requires contract deck_master_ppt_library_selection.v1
requires feature selection.deck_master_v1
```

---

## 7. 发布 Artifact

每个 release：

```text
sdist
wheel
checksums
SBOM
provenance/attestation
CHANGELOG
release notes
migration guide
benchmark summary
test summary
security summary
known limitations
```

v1.9+：

```text
container images
compose files
DB migration image/job
backup/restore guide
```

v2.0：

```text
Helm reference
OpenAPI
Python SDK
support policy
```

---

## 8. Packaging

clean environment 验证：

```bash
python -m venv /tmp/...
pip install <wheel>
ppt-lib --version
ppt-lib --home-dir /tmp/... setup --quick --non-interactive
ppt-lib --home-dir /tmp/... schema --output json
ppt-lib --home-dir /tmp/... doctor --output json
```

optional extras 分别验证：

```text
test
lint
demo
paddleocr
workbench
server
connectors
```

一个 extra 失败不得影响基础 wheel import。

---

## 9. Rollout

Local：

- RC；
- synthetic migration；
- selected real library canary；
- release；
- observe issues；
- patch。

Server：

- staging；
- backup；
- migration dry-run；
- canary workspace；
- full rollout；
- post-check；
- rollback window。

不得要求用户“直接覆盖数据库试试”。

---

## 10. Compatibility Window

### CLI

1.x stable commands 支持到至少 2.1。

### Contract

Deck Master v1 Contract 在 2.x 持续支持；废弃需要明确替代。

### DB

支持从前一个 minor 线性升级；v2.0 提供从 v1.4.1 开始的已验证路径说明。

### API

`/api/v1` 在 2.x 保持。

---

## 11. Release Check Script

现有 release check 应重构为环境无关：

- 不硬编码开发者私有 remote/path；
- 支持 public release context；
- 验证 current version；
- contract；
- schema；
- tests；
- build；
- privacy；
- fixture；
- benchmark summary；
- SBOM；
- docs。

输出 machine-readable。

---

## 12. Rollback

Local：

- pre-migration backup；
- application version rollback；
- restore；
- verify；
- no partial DB。

Server：

- image rollback；
- migration compatibility；
- vector index switch；
- DB restore；
- object consistency；
- post-rollback smoke。

Rollback 不能依赖未测试的 down migration。

---

## 13. Release Notes

必须回答：

- 有什么变化；
- 为什么变化；
- 谁受影响；
- 如何升级；
- 是否重建索引；
- Contract 变化；
- DB 变化；
- Provider 变化；
- Benchmark 结果；
- 安全变化；
- 已知限制；
- 如何回滚。

---

## 14. Support Bundle

提供：

```bash
ppt-lib support-bundle create
```

只包含：

- versions；
- schema；
- config keys without values/secrets；
- health；
- job error codes；
- dependency/platform；
- redacted logs；
- artifact inventory。

默认不含：

- PPT；
- screenshot；
- DB；
- query；
- full path；
- token；
- customer name。

---

## 15. Release Sign-off

Owner、Engineering、QA/Security（可由独立 Agent 代行初审，但最终 Owner 裁决）：

```text
scope complete
tests
benchmark
migration
contract
security
docs
rollback
known limitations
release artifacts
```

任何 waiver 必须记录 owner、reason、risk 和 expiry。


---

<!-- SOURCE: 13-agent-execution-task-pack.md -->

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


---

<!-- SOURCE: 14-risk-register-and-decision-log.md -->

# 14 — Risk Register 与 Decision Log

---

## 1. 风险分级

```text
P0: 会导致数据损坏、泄漏、跨 Workspace 越权、无法迁移或错误 GA
P1: 会导致核心质量、性能、稳定性或契约不可接受
P2: 会影响体验、维护性或边缘能力
P3: 可延期优化
```

---

## 2. 核心风险

| ID | 风险 | 级别 | 缓解 |
|---|---|---:|---|
| R-01 | Big Bang 重构导致现有 CLI 回归 | P1 | 渐进 service、compat shim、行为测试 |
| R-02 | Canonical ID 算法误合并客户变体 | P0 | revision/canonical 分层、manual review、false merge gate |
| R-03 | 多 worker 并发写 SQLite 数据损坏 | P0 | single writer、staging、transaction、failure tests |
| R-04 | Migration 半完成覆盖原库 | P0 | backup、journal、lock、verify、restore |
| R-05 | Deck Master Contract 漂移 | P1 | vendored schema hash、contract UAT、capability |
| R-06 | ANN 引入但质量下降 | P1 | hybrid benchmark、protected queries、rollback index |
| R-07 | Reranker 私有内容外发 | P0 | provider egress policy、explicit config、audit |
| R-08 | 业务反馈被少量样本污染 | P1 | Bayesian shrinkage、minimum count、demo isolation |
| R-09 | Workbench 直接写 DB 形成第二套逻辑 | P1 | service-only、repository tests |
| R-10 | Workbench 远程暴露 | P0 | localhost default、session、explicit remote |
| R-11 | Server 模式破坏 Local Mode | P1 | optional extras、dual-mode regression |
| R-12 | Postgres/SQLite 行为不一致 | P1 | repository contract suite |
| R-13 | Connector SSRF 或过度权限 | P0 | allowlist、least privilege、SSRF tests |
| R-14 | Workspace vector/blob 泄漏 | P0 | scope filters、opaque keys、isolation suite |
| R-15 | 发布检查硬编码私人环境 | P1 | environment-neutral release script |
| R-16 | 公开 benchmark 泄露客户数据 | P0 | synthetic public、privacy scan、aggregate only |
| R-17 | UI 开发提前掩盖检索不足 | P2 | v1.8 必须依赖 v1.6 gate |
| R-18 | Compose 演进为第二个 Deck Master | P1 | 产品边界、non-goals、API contract |
| R-19 | 第三方模型/配额变化 | P2 | provider abstraction、fallback disclosure |
| R-20 | 1M 容量目标导致过度工程 | P2 | capacity tiers、extended backend optional |
| R-21 | 审计记录正文/密钥 | P0 | schema restriction、redaction tests |
| R-22 | Hard delete 无法恢复 | P0 | archive/tombstone、dry-run、audit、backup |
| R-23 | Classification suggestion 被当作事实 | P1 | provenance/source/confidence/manual precedence |
| R-24 | 依赖和镜像供应链漏洞 | P1 | lock/SBOM/scan/attestation |
| R-25 | Windows 支持承诺超出真实验证 | P2 | Tier 定义、platform smoke、known limitations |

---

## 3. 必须形成 ADR 的决策

### ADR-001 Identity Fingerprint

- canonicalized OOXML 范围；
- media/chart relationship；
- layout hash；
- algorithm version；
- collision handling。

### ADR-002 Local ANN Backend

候选：

- hnswlib；
- usearch；
- sqlite vector extension；
- other local backend。

评价：

- wheels/platform；
- license；
- memory；
- persistence；
- filtering；
- maintenance。

### ADR-003 FTS Tokenization

- Chinese n-gram；
- tokenizer extension；
- portability；
- query behavior。

### ADR-004 Job Staging and Writer

- filesystem staging；
- DB staging；
- batch size；
- atomicity；
- cleanup。

### ADR-005 Workbench Frontend

- Jinja/HTMX；
- React/Vite；
- packaging；
- accessibility；
- build complexity。

### ADR-006 Server Metadata Layer

- raw SQL repository；
- SQLAlchemy Core；
- ORM；
- migration framework。

### ADR-007 Server Vector Backend

- pgvector；
- separate vector DB；
- deployment complexity；
- workspace filter；
- backup。

### ADR-008 Connector Reference Priority

根据真实用户来源选择 SharePoint、Google Drive、Feishu、S3/NAS。

### ADR-009 OIDC/Session Library

安全、维护、PKCE、claims mapping。

### ADR-010 Telemetry

默认关闭、字段、隐私、enterprise disable。

---

## 4. Decision Record Template

```markdown
# ADR-XXX — Title

Status: Proposed / Accepted / Superseded
Date:
Owners:
Related Tasks:

## Context
## Decision
## Alternatives
## Consequences
## Security / Privacy
## Migration
## Rollback
## Validation
```

---

## 5. Scope Control

以下变化必须由 Owner 批准：

- v1.5 增加 UI；
- v1.6 更换默认模型；
- v1.7 自动删除/合并；
- v1.8 增加公网模式；
- v1.9 引入多租户；
- v2.0 承诺 SaaS/SLA；
- 任何版本改变三项目边界；
- 任何版本删除 legacy CLI；
- 任何跨仓库 Contract breaking change。

---

## 6. Waiver

质量门豁免必须包含：

```text
gate
observed value
required value
reason
impact
mitigation
owner
expiry version/date
```

P0 安全、数据损坏、跨 Workspace 泄漏不得豁免。


---

<!-- SOURCE: 15-definition-of-done-and-acceptance-checklists.md -->

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
