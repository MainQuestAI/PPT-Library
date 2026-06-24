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
