# Library Build Guideline

日期：2026-05-26

本指南定义 PPT Library 的建库安全流程。Skill 负责引导，CLI 负责硬门禁；Agent 或脚本必须按这里的顺序执行。

如果用户让 Agent 从安装 CLI 开始，并希望安装后直接进入建库引导，Agent 应先阅读 [Agent Install and Guided Library Build Design](agent-install-and-build-guideline.md)。该文档定义安装阶段的用户问答、`sources-manifest.json` 生成、dry-run 汇报和建库监控流程。

## 目标

- 建库前明确资料范围、基准 PPT 和排除目录。
- 建库前先预览扫描结果，再用 `--apply` 写入确认状态。
- 生成 AI 摘要前必须先完成 workspace profile。
- 避免把 Home、Downloads、微信/WPS/WXWork 缓存等大目录误扫进库。
- 让重复页、预览图、AI 摘要和资产治理有可追踪的入口。

## 推荐流程

```bash
ppt-lib setup --quick --non-interactive
ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output /path/to/sources-manifest.json
ppt-lib init --manifest /path/to/sources-manifest.json --non-interactive
ppt-lib sources scan --dry-run
ppt-lib sources scan --apply
ppt-lib index --from-sources
ppt-lib status --output json
ppt-lib search "内容中心 技术架构" --top-k 8
```

`sources scan --dry-run` 只做预览，不授权建库。`sources scan --apply` 表示用户已经确认扫描范围，并会写入 `<home_dir>/sources/scan-state.json`。

AI summary 属于增强链路。先确认基础建库和搜索可用，再执行：

```bash
ppt-lib profile build
ppt-lib enrich --pending --limit 50
```

## Manifest 模板

```json
{
  "sources": {
    "baseline": [
      "/absolute/path/to/baseline-deck.pptx"
    ],
    "library": [
      "/absolute/path/to/ppt-library-folder"
    ],
    "exclude": [
      "/absolute/path/to/ppt-library-folder/.stversions",
      "/absolute/path/to/ppt-library-folder/.gstack",
      "/absolute/path/to/cache"
    ]
  }
}
```

`baseline` 用来建立用户画像。它应该是最能代表用户业务、行业、产品、方案风格和 PPT 类型的 1 到 3 份材料。若 baseline 也要进入搜索库，需要同时放入 `library`。

`library` 是正式入库范围。优先选择整理过的项目目录，避免直接指向 Home、Downloads、微信或 WPS 缓存。

`exclude` 用来排除缓存、历史版本、生成物和临时目录。

## 硬门禁

CLI 会在下列场景直接停止：

| 场景 | 错误码 |
|---|---|
| 未执行 `sources scan --apply` 就运行 `index --from-sources` | `LIBRARY_BUILD_SCAN_REQUIRED` |
| sources profile 在 apply 后发生变化 | `LIBRARY_BUILD_SCAN_STALE` |
| apply 状态里有未确认高风险来源 | `LIBRARY_BUILD_RISK_NOT_CONFIRMED` |
| `--apply` 命中高风险目录且未追加 `--force-risky-sources` | `SOURCE_RISK_CONFIRMATION_REQUIRED` |
| `--with-ai-summary` 但 active profile 未 ready | `LIBRARY_PROFILE_NOT_READY` |

单文件调试命令 `ppt-lib index /absolute/path/to/file.pptx` 不受上述 gate 限制。

## 高风险来源

以下路径需要用户明确确认，才允许 `sources scan --apply --force-risky-sources`：

- 用户 Home 根目录。
- `~/Downloads` 及其子目录。
- `~/.Trash` 及其子目录。
- `~/Library/Caches` 及其子目录。
- 微信、企业微信、WPS、WXWork 等缓存目录。
- Python、Node.js 等依赖包目录，例如 `site-packages` 和 `node_modules`。
- `output`、`outputs`、`exports`、`artifacts` 等临时产物目录。

Agent 不应主动建议扫描这些目录。用户确实要这么做时，先展示 dry-run 结果和风险说明，再追加 `--force-risky-sources`。

## Profile Readiness

`ppt-lib profile build` 会基于 baseline PPT 生成 workspace profile。只有 profile `ready=true` 时，`index --from-sources --with-ai-summary` 才能执行。

如果没有 baseline，profile 会给出 warning，并保持未 ready。此时可以先只做文本入库：

```bash
ppt-lib index --from-sources
```

等 baseline 补齐后，再运行：

```bash
ppt-lib profile build
ppt-lib enrich --pending --limit 50
```

## 重复页与资产治理

搜索默认应优先展示 canonical 页面，并隐藏强重复页；需要排查重复来源时再使用：

```bash
ppt-lib search "query" --include-duplicates
```

预览图、缩略图和重复资产应通过资产命令检查。清理动作默认 dry-run：

```bash
ppt-lib assets status
ppt-lib assets prune --dry-run
```

## Agent 汇报口径

Agent 汇报建库进展时至少包含：

- manifest 是否已写入。
- dry-run 命中的 PPTX 数量、粗略规模和排除目录。
- `sources scan --apply` 是否写入 scan-state。
- profile 是否 ready。
- index 是否执行、失败数量、是否走 AI summary。
- `status --output json` 中的 `sources_health.index_progress`。
- 是否出现高风险来源或缓存目录。
