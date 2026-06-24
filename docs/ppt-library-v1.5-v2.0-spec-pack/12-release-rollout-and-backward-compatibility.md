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
