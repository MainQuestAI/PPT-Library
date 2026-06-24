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
