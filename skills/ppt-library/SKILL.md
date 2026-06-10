# ppt-library

## 能力摘要

| 能力 | 对应命令 |
|------|---------|
| 配置引导 | `ppt-lib setup --quick` 或 `ppt-lib setup --mode lmstudio\|paddleocr-mcp\|openai\|text-extraction` |
| 扫描 PPT，去重，创建统一管理视图 | `ppt-lib discover <dir>` |
| 监听目录增量索引 | `ppt-lib watch <dir>` |
| 搜索 slide | `ppt-lib search "<query>" [-k N] [--threshold F]` |
| 生成 HTML 审查页 | `ppt-lib search "<query>" --html` |
| 索引单个文件 | `ppt-lib index <path>` |
| 批量索引 | `ppt-lib index --batch <dir> [--full]` |
| 资料库建库 | `ppt-lib sources manifest` → `init --manifest` → `sources scan --dry-run` → `sources scan --apply` → `index --from-sources` |
| AI 摘要补充 | `ppt-lib profile build` → `ppt-lib enrich` |
| Deck 理解与关键页 | `ppt-lib enrich-decks --pending` → `ppt-lib insights key-pages` |
| 标签审查包导出 | `ppt-lib insights review-pack --output <jsonl>` |
| 视觉模型链路检查 | `ppt-lib models test` |
| 模型能力检测 | `ppt-lib models test` |
| 配置查看／修改 | `ppt-lib config path\|get\|set` |
| 健康检查 | `ppt-lib doctor [--output json]` |
| 样本 QA | `ppt-lib qa sample` |
| 搜索质量评估 | `ppt-lib eval-search --manifest <path> [--calibrate]` |
| 孤立记录清理 | `ppt-lib prune --dry-run` → `--apply` |
| 聚合诊断 | `ppt-lib doctor --output json` |
| 生成用户画像 | `ppt-lib profile build --output json` |
| 战绩数据录入 | `ppt-lib record-deal --description ...` / `record-usage` |
| 叙事批量标注 | `ppt-lib annotate [--batch]` |
| 自动选页 | `ppt-lib select-slides --roles <roles> --brief "..."` |
| 自动组装 | `ppt-lib compose --brief "..." [--auto]` |

## 通用指引

1. 所有路径要写绝对路径，不要写 `~` 相对路径。
2. 调用时携带 `--output json`，不要用默认 text 输出。
3. JSON 响应体各命令结构不同，先跑一次获取结构，再引用具体字段。
4. 返回 payload 中的 `_errors` 用于判断是否有阻塞性错误。有错误时输出到 stderr，正常输出到 stdout。
5. `_meta.schema_version` 字段目前为 `1.0`。后续升级时可能增加字段，但不会破坏向后兼容。
6. 画像就绪：使用 AI summary 前必须先执行 `profile build`，并确认 `ready=true`。
7. 建库前先用 `sources manifest` 生成资料源清单，再通过 `sources scan --dry-run` 确认扫描范围，避免误扫 Home、Downloads、回收站、缓存目录和依赖包目录。
8. 需要判断“哪些页值得先看”时，先执行 `enrich-decks --pending --limit 20`，再执行 `insights key-pages --output json`。
9. 需要批量审查标签时，使用 `insights review-pack --output <jsonl>` 导出只读包；标签回写继续使用 `import-metadata`。
10. 推荐识别链路是本地 embedding + PaddleOCR MCP：先 `setup --mode lmstudio`，再 `setup --mode paddleocr-mcp`；token 只走环境变量，不写入 `config.yml`。

### 建库前安全确认

1. 资料范围通过 `sources manifest` 生成 manifest，再由 `init --manifest` 写入生效 profile。角色分为 `baseline`（用户画像基准）、`library`（入库资料）、`exclude`（排除路径）。
2. 基准 PPT：至少准备 1~3 个样例 PPT（`sources scan --dry-run` 时可先确认它们是否能正常识别）。
3. 资料库目录：在 manifest 中写明 `baseline`、`library`（与 excludes）。
4. 高风险目录：Home、Downloads、回收站、缓存、微信、WPS、`site-packages`、`node_modules`、outputs、exports、artifacts 默认不得进入 `library`。
5. 确认扫描：dry-run 后必须执行 `sources scan --apply`，让 CLI 写入 scan-state。
6. 画像就绪：使用 AI summary 前必须先执行 `profile build`，并确认 `ready=true`。

详细说明见仓库文档 `docs/guides/library-build-guideline.md`。CLI 会强制检查 scan-state、高风险路径和 profile readiness；Skill 只负责按流程引导。

未 dry-run 且未显式确认时，**不得**扫描 Home、Downloads、回收站、微信缓存、WPS 缓存、依赖包目录和临时产物目录。遇到高风险来源时，先向用户说明风险，再让用户决定是否追加 `--force-risky-sources`。

推荐命令链（确认后执行）：

### 快速建库（推荐，首次使用）

```bash
ppt-lib setup --quick --non-interactive
ppt-lib sources manifest --library /absolute/path/to/ppt-folder --manifest-output /absolute/path/to/sources-manifest.json --output json
ppt-lib init --manifest /path/to/sources-manifest.json --non-interactive
ppt-lib sources scan --role baseline --dry-run
ppt-lib sources scan --role library --dry-run
ppt-lib sources scan --apply
ppt-lib index --from-sources
ppt-lib status --output json
ppt-lib search "你的查询"
```

如果用户已准备 PaddleOCR MCP，并且资料量较大，可以使用保守文件级并行：

```bash
ppt-lib index --from-sources --file-workers 2
```

先从 2 个 worker 开始，确认 AI Studio 或自托管 OCR endpoint 稳定后再提高。

### 资产经营闭环（公开演示）

```bash
ppt-lib enrich-decks --pending --limit 20 --output json
ppt-lib insights key-pages --output json
ppt-lib insights review-pack --output /absolute/path/to/review-pack.jsonl
ppt-lib record-deal --name "Synthetic Retail Win" --outcome won --description "Synthetic demo opportunity" --industry retail --scenario proposal --tags demo,key-page
ppt-lib record-usage --deal-id <deal-id> --slide-id <slide-id> --deck-presentation-id <presentation-id>
ppt-lib search "业务架构 价值" --ranking business --threshold 0.0 --output json
```

`insights key-pages` 返回关键页候选、页面角色、重要性分、视觉复核标记和战绩统计。`business ranking` 只有在真实 usage 和 won/lost 数据积累后才会体现业务权重。

### 完整建库（可选，含 AI 摘要）

```bash
ppt-lib profile build
ppt-lib enrich --pending --limit 50
```

首次使用建议走快速建库，确认搜索可用后再开启 AI 摘要。

单个文件校验：

```bash
ppt-lib index /absolute/path/to/deck.pptx
```

## 返回值示例

### `ppt-lib doctor --output json`

```json
{
  "summary": {
    "status": "warning",
    "config": "ok",
    "scanner": "ok",
    "model_compat": "warning"
  },
  "config": {
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": 1536,
    "vision_provider": "auto"
  },
  "model_compat": {
    "status": "warning",
    "checks": [{"capability": "embedding", "status": "ok", "message": "OpenAI embedding works"}]
  },
  "index_health": {
    "status": "ok",
    "slides_indexed": 746,
    "presentations": 107,
    "failed_jobs": 0
  },
  "scanner": {"status": "ok"}
}
```

### `ppt-lib search "<query>" --top-k 3`

```json
{
  "query": "海外仓售后流程",
  "results": [
    {
      "slide_index": 5,
      "presentation": {"path": "/path/to/deck.pptx", "filename": "solution_overview.pptx"},
      "title": "海外仓退货流程",
      "text_snippet": "退货流程图...",
      "screenshot_url": "file:///.../screenshots/slide-5.png",
      "score": 0.68,
      "duplicate_group_id": null
    }
  ],
  "timing_ms": 316
}
```

### `ppt-lib status --output json`

```json
{
  "presentations": {
    "total": 107,
    "limit": null,
    "disabled": 0
  },
  "slides": {
    "total": 746,
    "canonical": 746,
    "canonical_with_duplicates": 0,
    "duplicates": 0,
    "limit": null
  },
  "inline_details": {}
}
```

## 注意事项

- 路径必须绝对路径。
- 建库流程中的 sources scan 要 **每次** 带 `--dry-run` 预览来确认 safe（home dir、downloads、微信缓存都是高风险来源）。
- JSON 输出的键名可能带 `_errors` 与 `warnings`。`_errors` 非空时视为该操作有阻塞性问题。
- 默认优先 `setup --quick`。OpenAI-compatible 服务通过 `embedding_api_url`、`embedding_model`、`embedding_dimensions` 配置；LM Studio 默认服务地址为 `http://127.0.0.1:1234/v1`。
- 当前 embedding 维度：openai=1536，lmstudio=768；切换 provider 后应 `index --from-sources --full` 重算。
