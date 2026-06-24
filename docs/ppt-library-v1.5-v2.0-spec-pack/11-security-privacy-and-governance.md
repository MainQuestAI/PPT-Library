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
