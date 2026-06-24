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
