<!-- /autoplan restore point: ~/.gstack/projects/PPT-Library/codex-agent-install-build-guideline-doc-autoplan-restore-20260604-153440.md -->

# Agent Install and Guided Library Build Design

日期：2026-06-04

## 结论

PPT Library 的首次体验应采用“Agent 安装剧本 + 用户高价值资产问答 + CLI 确定性执行”的模式。

设计目标是让用户只发起一次“安装 PPT-Library”任务，Agent 在安装启动后收集建库信息，调用 CLI 生成资料源 manifest，安装完成后直接进入安全 dry-run 和用户确认流程。`SKILL.md` 保持轻量，只承载已安装后的使用规则。

## 背景问题

当前建库风险来自“尽量多扫到 PPT”的旧口径。真实索引中已经出现 WPS 备份、回收站、Downloads、Python 模板、缓存目录和大量 orphan 记录。这会带来三类问题：

- 搜索噪音变多，重复版本、备份文件和临时产物会干扰候选页排序。
- 建库成本变高，截图、文本抽取和 embedding 都会被低价值文件消耗。
- 隐私和治理风险变大，聊天软件缓存、下载目录、回收站和依赖包目录不应默认进入长期 PPT 库。

因此，首次建库入口必须从“扫描本机 PPT”改为“选择高价值资产入口”。

## 设计边界

本设计定义文档、流程和 CLI v1 安全建库入口。

本轮实现：

- `ppt-lib sources manifest` 资料源清单生成。
- 高风险资料源分类。
- `index --from-sources` 进度状态文件。
- `status` 资料源健康状态。
- README、建库指南和 Skill 边界对齐。

本轮不包含数据库迁移、存量索引清理、搜索排序改动和 noisy source 降权。

## 分工模型

| 层级 | 职责 | 不承担 |
|---|---|---|
| README | 给安装场景下的 Agent 一个入口，说明安装剧本位置 | 不放完整问答和长流程细节 |
| 本指南 | 定义 Agent 安装、问答、manifest、dry-run、建库监控的完整流程 | 不替代 CLI 规格 |
| CLI | 安装、配置、扫描、索引、状态输出，提供 JSON 结果 | 不主导自然语言问答 |
| Skill | 已安装后的搜索、审查、组装、监控、故障解释 | 不承载安装前 Setup 长上下文 |

## 推荐用户体验

用户只需要对 Agent 说：

```text
安装 PPT-Library CLI
```

Agent 应执行以下动作：

1. 读取 README 中的 Agent 安装入口，进入本指南。
2. 启动 CLI 安装。
3. 安装启动后向用户收集高价值资产路径。
4. 校验用户提供的路径是否存在。
5. 生成 `sources-manifest.json` 和用户可读摘要。
6. 安装完成后校验 CLI。
7. 使用 manifest 初始化 sources profile。
8. 执行 dry-run，汇报命中 PPT 数、粗略规模、排除目录和风险来源。
9. 等用户确认后执行 `sources scan --apply`。
10. 执行 `index --from-sources`。
11. 定期查看进度和失败记录，直到完成或阻断。
12. 安装或更新 Agent Skill。
13. 提醒用户重启 Agent 或重新加载 Skill。

## Agent 安装剧本

### 1. 启动安装

Agent 应先判断当前环境可用的安装方式。

源码 checkout 场景：

```bash
uv sync --extra test --extra lint
uv run ppt-lib --version
```

本地工具安装场景：

```bash
uv tool install .
ppt-lib --version
```

editable 安装场景：

```bash
pip install -e .
ppt-lib --version
```

Agent 不应在安装阶段扫描真实资料目录。

### 2. 收集用户路径

安装启动后，Agent 应立即向用户收集以下信息。不同 Agent 宿主对真正并发的支持不一致，所以该步骤不依赖安装命令和问答必须同时完成。问题要用非技术表达，允许用户一次性粘贴多个绝对路径。

必问：

- 你的核心方案库目录在哪里？
- 有没有当前项目资料目录要加入？可以粘贴多个。
- 有没有历史归档目录要加入？可以粘贴多个。
- 有没有 1 到 3 份最能代表你风格和业务方向的基准 PPT？

默认确认：

- 是否默认排除微信、企业微信、WPS、Downloads、回收站、缓存目录、临时输出目录？

可选：

- 是否有明确永远不扫描的目录？
- 是否先只做小范围试运行？

Agent 的默认推荐应是：

```text
先只收核心方案库、当前项目资料、历史归档和少量基准 PPT。
微信、企业微信、WPS、Downloads、回收站、缓存和临时输出目录默认排除。
```

### 3. 路径分类规则

Agent 应把用户输入分成四类：

| 分类 | manifest 字段 | 用途 |
|---|---|---|
| 基准 PPT | `baseline` | 建立用户画像和业务风格 |
| 高价值资料目录 | `library` | 进入搜索库 |
| 明确排除目录 | `exclude` | 不扫描 |
| 待确认路径 | 不写入 manifest | 不存在、权限异常或高风险 |

默认高风险路径：

- 用户 Home 根目录。
- `~/Downloads`。
- `~/.Trash`。
- `~/Library/Caches`。
- 微信、WeChat、企业微信、WXWork 相关路径。
- WPS、Kingsoft 相关备份或缓存路径。
- `.cache`、`node_modules`、`.venv`、`site-packages`。
- `build`、`dist`、`tmp`、`temp`、`output`、`outputs`、`exports`、`artifacts`。

高风险路径默认不进入 `library`。用户坚持加入时，Agent 必须先展示风险说明和 dry-run 结果。

## 生成文件

Agent 应在 PPT Library home 目录下生成两个文件。

默认路径：

```text
~/.ppt-library/sources/sources-manifest.json
~/.ppt-library/sources/onboarding-summary.md
```

如果用户指定了 `--home-dir`，则写入：

```text
<home-dir>/sources/sources-manifest.json
<home-dir>/sources/onboarding-summary.md
```

### sources-manifest.json

示例：

```json
{
  "sources": {
    "baseline": [
      "/Users/example/Workspace/_resources/solution-library/core-deck.pptx"
    ],
    "library": [
      "/Users/example/Workspace/_resources/solution-library",
      "/Users/example/Workspace/BrandA/AI",
      "/Users/example/Workspace/_archives/ppt"
    ],
    "exclude": [
      "/Users/example/Downloads",
      "/Users/example/.Trash",
      "/Users/example/Library/Containers/com.kingsoft.wpsoffice.mac",
      "/Users/example/Library/Containers/com.tencent.WeWorkMac"
    ]
  }
}
```

规则：

- 必须使用绝对路径。
- 不存在的路径不得写入。
- 重复路径必须去重。
- `baseline` 可以是文件或目录，但推荐 1 到 3 份 PPTX 文件。
- `library` 推荐目录优先，单文件只用于小范围试运行。
- `exclude` 应包含用户明确排除路径和默认高风险路径。

### onboarding-summary.md

摘要应给人看，便于后续排查。建议结构：

```markdown
# PPT Library Onboarding Summary

日期：2026-06-04

## 用户选择

- 核心方案库：...
- 当前项目资料：...
- 历史归档：...
- 基准 PPT：...

## 默认排除

- Downloads
- 回收站
- WPS 备份和缓存
- 微信和企业微信缓存
- 临时输出和依赖包目录

## 待确认

- 路径不存在：...
- 高风险但用户希望加入：...

## 下一步命令

...
```

## CLI 执行流程

### 1. 安装校验

Agent 应执行：

```bash
ppt-lib --version
ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive --output json
ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
```

如果源码目录内尚未安装 CLI，则使用：

```bash
uv run ppt-lib --version
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke setup --quick --non-interactive --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-smoke status --output json
```

### 2. 生成 manifest

```bash
ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --baseline /absolute/path/to/baseline.pptx \
  --exclude /absolute/path/to/exclude-folder \
  --manifest-output ~/.ppt-library/sources/sources-manifest.json \
  --summary-output ~/.ppt-library/sources/onboarding-summary.md \
  --output json
```

源码目录内：

```bash
uv run ppt-lib sources manifest \
  --library /absolute/path/to/ppt-folder \
  --baseline /absolute/path/to/baseline.pptx \
  --exclude /absolute/path/to/exclude-folder \
  --manifest-output ~/.ppt-library/sources/sources-manifest.json \
  --summary-output ~/.ppt-library/sources/onboarding-summary.md \
  --output json
```

`sources-manifest.json` 是 Agent 收集到的用户输入记录；sources profile 是 CLI 真正生效的配置。

### 3. 初始化 sources profile

```bash
ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
```

源码目录内：

```bash
uv run ppt-lib init --manifest ~/.ppt-library/sources/sources-manifest.json --non-interactive --output json
```

### 4. dry-run 扫描

```bash
ppt-lib sources scan --role library --dry-run --output json
```

Agent 汇报时必须包含：

- 命中 PPTX 数量。
- 粗略规模。
- 扫描根目录。
- 排除目录。
- 风险提示。
- 是否建议继续。

### 5. 用户确认后 apply

```bash
ppt-lib sources scan --role library --apply --output json
```

如果 CLI 返回高风险错误，Agent 不应自动追加 `--force-risky-sources`。必须先让用户确认。

### 6. 建库

基础建库：

```bash
ppt-lib index --from-sources
```

如果用户已经配置 embedding，Agent 可汇报会使用对应 embedding 配置。AI summary 不在首次默认链路里启动。

### 7. 完成校验

```bash
ppt-lib status --output json
ppt-lib doctor --output json
ppt-lib search "客户成功案例" --top-k 5 --output json
```

Agent 汇报时必须说明：

- 入库 PPT 数。
- 入库 slide 数。
- failed jobs 数。
- orphan 数。
- smoke search 是否有结果。
- 下一步是否需要补 embedding、profile 或清理失败任务。

## 时间估算

Agent 应给用户一个保守估算，避免用户以为命令卡住。

估算口径：

| 任务 | 主要影响因素 | 汇报口径 |
|---|---|---|
| dry-run | 文件数量和目录深度 | 通常是秒级到数分钟 |
| 文本抽取 | PPT 数和页数 | 每百页约数分钟，视机器性能变化 |
| 截图 | LibreOffice 启动和页面复杂度 | 比文本抽取慢，复杂 PPT 更慢 |
| embedding | 模型服务速度和页数 | 云端或本地模型不同，差异很大 |

Agent 不应给精确承诺。建议用区间：

```text
这次 dry-run 命中 120 份 PPT，粗略规模约 4200 个文件项。首次建库可能需要几十分钟到数小时。具体取决于截图和 embedding 是否开启。我会每 2 到 5 分钟回来查看一次进度。
```

## 进度监控

建库期间，Agent 应持续监控，不应把长任务丢给用户自己判断。

建议节奏：

- 小于 500 页：每 60 秒查看一次。
- 500 到 5000 页：每 2 分钟查看一次。
- 超过 5000 页：每 5 分钟查看一次。

监控命令：

```bash
ppt-lib status --output json
```

当前 v1 已通过 `<home-dir>/sources/index-progress.json` 和 `status --output json` 暴露建库进度。Agent 应优先查看：

- 当前处理文件。
- 已完成 PPT 数。
- failed jobs 增量。
- 预计剩余时间，仅在进度状态足够稳定时汇报。

## Agent 汇报模板

### 安装完成

```text
PPT-Library CLI 已安装并通过基础检查。

我接下来会根据你给的高价值目录生成资料源清单，不会扫描 Home、Downloads、微信、WPS、回收站或缓存目录。
```

### dry-run 完成

```text
扫描预览完成。

- 资料目录：3 个
- 命中 PPT：120 份
- 粗略规模：4200 个文件
- 已排除：Downloads、WPS 缓存、微信缓存、outputs
- 风险来源：无

如果你确认，我会写入扫描确认状态并开始建库。
```

### 建库完成

```text
建库完成。

- 入库 PPT：118 份
- 入库页面：4130 页
- 失败任务：2 个
- orphan 记录：0
- 搜索验证：有结果

失败文件我已经列出，下一步可以单独处理。
```

## Skill 边界调整

`skills/ppt-library/SKILL.md` 应保持为已安装后的使用说明，重点包括：

- 搜索。
- HTML 审查。
- 组装。
- 使用 JSON 输出。
- 检查 `_errors`。
- 监控长任务。
- 处理 failed jobs。

安装前问答、CLI 安装剧本和 manifest 生成规则应放在 README 指向的文档中。这样正常使用时，Agent 不需要加载安装阶段的长上下文。

## 已实现能力和后续任务

当前 v1 已覆盖 P0、P1 和基础进度状态。后续仍可按 P2 扩展质量治理。

### P0：文档和入口

- README 增加 Agent 安装入口。
- docs 增加本指南。
- `library-build-guideline.md` 补充“高价值资产入口优先”原则。

验收：

- Agent 能从 README 找到安装剧本。
- Skill 不增加安装长流程。

### P1：Manifest 生成辅助

新增 CLI 命令用于校验用户路径并生成 manifest。

命令：

```bash
ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output ~/.ppt-library/sources/sources-manifest.json
```

验收：

- 不存在路径不写入。
- 高风险路径进入待确认区。
- 默认 exclude 能覆盖 WPS、微信、企业微信、Downloads、回收站、缓存和临时输出。

### P2：进度和质量治理

- `index --from-sources` 输出更明确的进度。
- status 增加 sources health。
- 搜索默认过滤 noisy source。
- 增加存量库 audit dry-run。

验收：

- Agent 能按页数估算监控间隔。
- 建库完成后能输出质量摘要。
- 默认搜索不展示 WPS、Trash、cache、site-packages 来源。

## 成功标准

这套设计落地后，应满足：

- 用户只发一次安装请求，Agent 能完成安装、问答、manifest、dry-run 和建库。
- 用户明确知道哪些目录会入库，哪些目录被排除。
- 首次建库不默认扫描全盘。
- WPS、微信、企业微信、Downloads、回收站和缓存目录默认不入库。
- `SKILL.md` 只承担已安装后的操作指导。
- 后续搜索结果重复率和噪音来源明显下降。

## GSTACK REVIEW REPORT

Status: DONE_WITH_CONCERNS

Reviewed: 2026-06-04

Branch: `codex/agent-install-build-guideline-doc`

Plan file: `docs/guides/agent-install-and-build-guideline.md`

Review mode: autoplan single-reviewer fallback. 当前宿主没有 AskUserQuestion 和子 Agent 工具，所以本轮按 autoplan 自动决策原则完成 CEO、工程和 DX 审查。UI scope: no，Design review skipped。DX scope: yes，原因是本方案涉及 CLI、README、Skill、Agent 安装体验和首次建库体验。

### Plan Summary

本设计方向成立，应保留“README 安装入口 + 独立安装剧本 + sources manifest + CLI 确定性执行 + 轻量 Skill”的分层。

核心价值判断：

- 安装阶段先让用户指定高价值 PPT 入口，可以显著降低全盘扫描的隐私风险、重复率和低价值索引成本。
- 将 Setup 长流程移出 `SKILL.md`，可以降低日常搜索和组装任务的上下文成本。
- 让 Agent 收集路径、生成 manifest、再交给 CLI dry-run 和 apply，符合 Runtime-first 的基本方向：状态进入文件和 CLI profile，执行结果可以被验证。

本轮主要结论：设计可以作为下一轮开发输入，但要先修正若干实现对齐问题，尤其是页数估算、manifest/profile 关系、高风险路径分类、进度监控能力和 Skill 边界迁移。

### CEO Review

Verdict: proceed with a narrowed first implementation.

用户价值：

- 从“尽量扫全”改为“只收高价值入口”，直接改善搜索精准性和建库效率。
- 用户对扫描范围有明确知情和确认，降低误扫聊天缓存、回收站、下载目录、依赖包目录的风险。
- Agent 安装体验更顺：用户只发安装请求，后续由 Agent 按文档问问题、生成配置、执行 dry-run。

范围建议：

- 第一版只做“安全建库引导”，不要同时做搜索排序和存量库清洗。
- 第一版必须让 manifest、profile、scan-state 三者关系清楚，否则后续 Agent 会把“记录用户输入”和“CLI 生效配置”混在一起。
- 第一版可以把进度监控降级成命令完成后的结果汇报，前提是在文档里写清限制；如果要做“定期回来查看进度”，CLI 需要新增进度状态。

Strategic risk:

- 如果文档承诺了尚未存在的 CLI 命令，Agent 会按 README 执行失败，首次体验会被破坏。
- 如果风险路径分类只停留在文档层，实际 CLI 仍可能接受 `.Trash`、`site-packages`、输出产物等低价值路径。
- 如果页数估算没有真实来源，时间预估会让用户产生错误预期。

### Existing Implementation Fit

| Need | Existing support | Gap |
|---|---|---|
| sources profile roles | `baseline`、`library`、`exclude` 已存在 | 还缺 manifest 生成辅助命令 |
| risky source warning | 已覆盖 Home、Downloads、Library/Caches 和微信/WPS 等 token | 还缺 `.Trash`、`site-packages`、项目输出目录等更完整分类 |
| dry-run/apply gate | `sources scan --apply` 已有风险阻断和 scan-state | 人类可读输出没有充分展示风险明细 |
| stale state protection | `index --from-sources` 已校验 scan-state | manifest/profile 的关系需要文档和 CLI 输出解释 |
| tests | `tests/test_sources_cli.py` 已覆盖风险阻断、dry-run、apply、stale profile | 需要补高风险路径、manifest helper、进度或降级行为测试 |
| progress monitoring | 有 `status` 和 index 结果输出 | 缺少 index 中间进度、job id 或可轮询状态 |

### Architecture And Data Flow

```text
User request
  |
  v
README Agent install entry
  |
  v
Agent install playbook
  |
  +--> install CLI and verify version
  |
  +--> ask high-value source questions
          |
          v
     sources-manifest.json
          |
          v
     ppt-lib init --manifest ...
          |
          v
     sources profile
          |
          v
     ppt-lib sources scan --dry-run
          |
          v
     user confirmation
          |
          v
     ppt-lib sources scan --apply
          |
          v
     scan-state
          |
          v
     ppt-lib index --from-sources
          |
          v
     status / doctor / search verification
```

运行时状态建议：

- `sources-manifest.json`: Agent 收集到的用户意图和路径输入，适合保留为安装证据。
- sources profile: CLI 真正采用的资料源配置，负责 roles、exclude 和校验后的路径。
- scan-state: 最近一次 scan 的授权状态，负责阻断过期配置直接 index。
- index/status output: 建库结果和失败记录，负责让 Agent 汇报进度与质量。

### Engineering Findings

P1: legacy `estimated_pages` 需要和真实页数能力对齐。

当前 v1 已把人类可读输出改为“粗略规模”，JSON 保留 legacy `estimated_pages` 兼容字段，并新增 `estimated_file_count` 和 `scale_estimate`。后续如果需要真实页数，再单独补轻量页数统计。

P1: manifest 与 profile 的关系需要写成硬规则。

`~/.ppt-library/sources/sources-manifest.json` 是 Agent 生成的输入记录；CLI 生效配置是 sources profile。当前 v1 已通过 `ppt-lib init --manifest <path>` 将 manifest 转成 profile，并在转换失败时返回结构化 `_errors`。

P1: 高风险路径分类需要进入 CLI。

当前 v1 已新增统一分类函数 `classify_source_path()`，把路径分成 `trusted`、`candidate`、`noisy`、`blocked`，并覆盖 `.Trash`、Downloads、微信、企业微信、WPS、缓存、`site-packages`、`node_modules`、输出目录和归档产物目录。

P1: 文档中的 manifest 命令必须和 CLI 能力一致。

当前 v1 已实现 `ppt-lib sources manifest`，文档和 README 应使用 `--manifest-output` 指定 manifest 文件，`--output` 仅用于 text/json 输出。

P2: 进度监控能力需要状态文件支撑。

当前 v1 已新增 `<home-dir>/sources/index-progress.json`，`status --output json` 会通过 `sources_health.index_progress` 暴露最新进度。stdout 仍保持最终 JSON envelope，避免破坏 Agent 解析。

P2: CLI 人类输出应展示风险明细。

当前 v1 已在 `sources scan` 的人类输出中显示风险路径和风险原因，降低误确认概率。

P2: Skill 边界已在仓库内落地，并已同步到已安装目录。

仓库内 `skills/ppt-library/SKILL.md` 已收缩为安装后的使用规则，并已同步到 `~/.codex/skills/ppt-library/`。后续新 Codex 会话会加载新规则。

### Error And Rescue Registry

| Error | Detection | User-facing rescue |
|---|---|---|
| CLI install failed | version command unavailable | 回报安装失败，保留已收集的 manifest 草稿，提示用户可重试安装 |
| manifest invalid | JSON schema 或路径校验失败 | 列出无效路径，不写入 profile |
| path missing | `Path.exists()` false | 让用户重新粘贴路径，或移入 `exclude` 记录 |
| risky source selected | classifier returns `blocked` or `noisy` | 解释风险原因，要求显式确认或自动排除 |
| scan-state stale | profile hash mismatch | 要求重新 dry-run 和 apply |
| index failed partially | failed jobs > 0 | 汇报失败文件列表，允许继续使用成功入库部分 |
| progress unavailable | index-progress file missing or unreadable | 降级为命令完成后汇报，并提示用户检查 `status --output json` |
| Skill reload missing | Agent cannot find installed Skill | 提醒用户重启 Agent 或重新加载 Skill |

### Failure Modes Registry

| Failure mode | Severity | Mitigation |
|---|---:|---|
| 用户把 Home 或 Downloads 当核心库 | P1 | classifier 阻断或要求 `--force-risky-sources` |
| WPS/微信缓存进入索引 | P1 | 默认 noisy/blocked，dry-run 汇报风险 |
| manifest 写入了不存在路径 | P1 | 生成前校验，失败路径进入 rejected list |
| Agent 加载旧 Skill 或旧文档 | P1 | 同步 `skills/ppt-library/` 到本地 Agent Skill 目录 |
| 页数估算误导耗时 | P1 | 改称粗略规模，或新增真实页数统计 |
| 长任务无进度导致用户误以为卡死 | P2 | 读取 `sources_health.index_progress` 并按节奏汇报 |
| Skill 携带 Setup 长上下文 | P2 | 仓库 Skill 保持使用说明，安装剧本留在 README 指向文档 |
| 搜索继续展示 noisy source | P2 | 后续在 search 层加入 source quality 过滤或降权 |

### Test Diagram

```text
Manifest helper tests
  -> valid paths become baseline/library/exclude
  -> missing paths rejected
  -> risky paths flagged

Risk classifier tests
  -> Downloads blocked or noisy
  -> .Trash blocked
  -> WeChat / WeCom / WPS noisy or blocked
  -> site-packages / node_modules blocked
  -> project outputs / exports / artifacts noisy

Scan CLI tests
  -> dry-run never authorizes index
  -> apply writes scan-state
  -> risky apply requires explicit force
  -> human output includes risk details

Index tests
  -> stale profile blocks index
  -> approved profile allows index
  -> progress mode emits parseable state

Docs tests
  -> README points to install playbook
  -> install playbook never asks for full-disk scan
  -> Skill remains usage-only
```

### DX Review

Target user: 非技术用户通过 Agent 安装和维护 PPT Library，同时希望控制资料源范围、降低噪音，并能理解建库结果。

Developer journey:

1. 用户发起“安装 PPT-Library CLI”。
2. Agent 从 README 找到安装剧本。
3. Agent 启动安装并收集路径。
4. Agent 生成 manifest 摘要，让用户确认扫描范围。
5. CLI 执行 dry-run 并输出可解释结果。
6. 用户确认后 CLI apply 和 index。
7. Agent 汇报完成情况、失败记录和下一步。
8. 用户重启或加载 Skill，进入日常搜索使用。

DX scorecard:

| Area | Current score | Target after next iteration | Reason |
|---|---:|---:|---|
| Getting started | 8 | 8 | README 入口和 CLI quick-start 已对齐 |
| Path intake | 8 | 8 | `sources manifest` 已提供路径收集入口 |
| Safety defaults | 9 | 9 | 风险分类已覆盖主要低价值路径 |
| Error clarity | 8 | 8 | JSON 和人类输出都展示风险信息 |
| Progress confidence | 7 | 7 | `index-progress.json` 已接入 `status` |
| Skill context cost | 8 | 8 | 仓库 Skill 已收缩，并已同步到已安装 Skill |
| Verification loop | 8 | 8 | dry-run/apply/index/status 链路已形成闭环 |

DX recommendation:

- README 只放最短入口和“Agent 请读这里”的链接。
- 指南写完整安装剧本、问答清单和 manifest 格式。
- CLI 输出必须同时服务 Agent 和普通用户：JSON 给 Agent，人类输出给用户理解。
- 不要把首次安装问答放进 `SKILL.md`，否则日常任务会持续背负 Setup 成本。

### Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected alternative |
|---:|---|---|---|---|---|---|
| 1 | CEO | 保留 README + 指南 + CLI + Skill 分层 | Auto | P5 user intent, P3 scope | 符合用户提出的安装引导和 Skill 轻量化方向 | 把 Setup 全写入 Skill |
| 2 | CEO | 第一版聚焦安全建库引导 | Auto | P3 scope | 避免把搜索排序、存量清理和安装体验绑成大任务 | 同时改搜索和清库 |
| 3 | Eng | 把 legacy `estimated_pages` 标为 P1 对齐项 | Auto | P1 evidence | 现有扫描摘要缺可靠页数统计，文案会影响时间预期 | 继续按页数承诺耗时 |
| 4 | Eng | 优先补风险分类和 manifest helper | Auto | P1 evidence, P5 user intent | 这是避免全盘扫描和低价值入库的核心防线 | 先做进度看板 |
| 5 | DX | 保留 Agent 问答式路径收集 | Auto | P5 user intent | 非技术用户更适合粘贴路径和确认摘要 | 让用户直接编辑 JSON |
| 6 | DX | 将真实进度监控列为 P2 | Auto | P2 simplicity | 当前 CLI 是同步批处理，先明确限制再扩展 | 文档先承诺轮询能力 |

### Implementation Status And Remaining Work

P0: 文档对齐（已完成）

- 明确 manifest 是 Agent 输入记录，profile 是 CLI 生效配置。
- 将 dry-run 的人类可读输出改成“粗略规模”，真实页数统计后续单独处理。
- 将“安装期间同步提问”改成“安装启动后立即收集问题，安装完成后继续”，避免依赖不同宿主的真正并发能力。
- 文档使用真实 `ppt-lib sources manifest --manifest-output ...` 命令。

P1: CLI 安全入口（已完成）

- 新增 `classify_source_path()` 或同等能力。
- 扩展风险覆盖：`.Trash`、Downloads、微信、企业微信、WPS、Caches、`site-packages`、`node_modules`、输出目录、exports、artifacts。
- 新增 `ppt-lib sources manifest` CLI 子命令。
- `sources scan` 人类输出展示风险明细。
- 为上述能力补 CLI 测试。

P2: 进度和质量（部分完成）

- 为 `index --from-sources` 增加状态文件进度，并通过 `status` 暴露。
- `status` 增加 sources health 和最近一次 scan 摘要。
- 后续再做 search noisy source 过滤或降权。
- 增加存量库 audit dry-run，用于清理已有噪音来源。

### Final Gate

Autoplan final gate: pass with concerns.

当前 v1 已完成 P0 文档对齐、P1 风险分类和 manifest helper，并用状态文件支撑首版进度监控。后续建议单独排期：真实页数统计、存量库 audit dry-run、search noisy source 降权。
