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
