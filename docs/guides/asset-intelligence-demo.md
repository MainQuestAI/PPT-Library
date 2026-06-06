# PPT Asset Intelligence Demo

本指南用于公开版演示“PPT 资产经营闭环 v1”：从合成 PPT 建库，到关键页识别、审查导出、战绩录入、复用追踪和业务排序搜索。

边界：

- 只使用仓库脚本生成的合成 PPTX。
- 不需要真实客户 PPT、真实截图、本地数据库或私有路径。
- `business ranking` 是可选增强，只有录入真实 usage 和 won/lost 数据后才会体现业务权重。

## 1. 生成合成 PPT

```bash
uv run --extra demo python scripts/create_demo_decks.py --output /tmp/ppt-lib-demo-decks
```

脚本会生成 3 份合成 PPTX，主题覆盖零售、制造和公共数据平台。文件名、页面正文、deal 名称均为合成内容。

该脚本使用 `python-pptx` 生成标准 PPTX，目的是让 LibreOffice 可以稳定渲染页面缩略图。核心 CLI 不依赖 `python-pptx`。

## 2. 初始化独立 demo home

```bash
rm -rf /tmp/ppt-lib-demo
uv run ppt-lib --home-dir /tmp/ppt-lib-demo setup --quick --non-interactive
```

## 3. 用 sources manifest 收敛入库范围

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources manifest \
  --library /tmp/ppt-lib-demo-decks \
  --manifest-output /tmp/ppt-lib-demo/sources-manifest.json \
  --output json

uv run ppt-lib --home-dir /tmp/ppt-lib-demo init \
  --manifest /tmp/ppt-lib-demo/sources-manifest.json \
  --non-interactive \
  --output json
```

## 4. 扫描并建库

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --dry-run --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo sources scan --apply --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo index --from-sources
```

如果本机没有 LibreOffice，截图会走文本 fallback；demo 仍可完成文本索引和关键页识别。开源发布验收要求本机安装 LibreOffice，并且搜索 HTML 至少能看到一张页面缩略图。

## 5. 生成关键页候选

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo enrich-decks --pending --limit 20 --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo insights key-pages --output json
uv run ppt-lib --home-dir /tmp/ppt-lib-demo insights key-pages --needs-visual --output text
```

`insights key-pages` 会返回每页来源、页码、标题、页面角色、重要性分、候选原因、视觉复核标记、复用次数和赢单统计。

## 6. 导出 Agent 审查包

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo insights review-pack \
  --output /tmp/ppt-lib-demo/review-pack.jsonl
```

审查包是只读 JSONL。人工或 Agent 如需修正标签，应继续通过既有 `import-metadata` 链路回写 `industry`、`scenario`、`narrative_role`、`quality_rating`。

## 7. 录入战绩描述

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo record-deal \
  --name "Synthetic Retail Win" \
  --outcome won \
  --description "Synthetic demo opportunity for retail growth proposal." \
  --industry retail \
  --scenario proposal \
  --tags demo,architecture,key-page
```

输出中的 `deal.id` 会用于下一步记录复用事实。

## 8. 记录页面复用

先从 `insights key-pages --output json` 里取：

- `items[0].slide_id`
- `items[0].presentation.id`

再执行：

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo record-usage \
  --deal-id <deal-id> \
  --slide-id <slide-id> \
  --deck-presentation-id <presentation-id>
```

## 9. 用业务排序搜索

```bash
uv run ppt-lib --home-dir /tmp/ppt-lib-demo search "业务架构 价值" \
  --ranking business \
  --threshold 0.0 \
  --output json

uv run ppt-lib --home-dir /tmp/ppt-lib-demo search "业务架构 价值" \
  --ranking business \
  --threshold 0.0 \
  --html
```

JSON 结果会包含关键页和战绩解释字段：`page_role`、`importance_score`、`importance_reason`、`needs_visual`、`reuse_count`、`won_count`、`lost_count`、`win_rate`。

HTML 结果页会展示关键页标签和战绩摘要，适合人工审查。

## Demo 验收口径

- `insights key-pages` 能看到候选关键页。
- `insights review-pack` 能生成可解析 JSONL。
- `record-deal` 能保存结构化战绩描述，同时兼容旧 notes。
- `record-usage` 后，搜索 JSON 和 HTML 能显示复用与赢单统计。
- 安装 LibreOffice 后，搜索 HTML 至少显示一张页面缩略图，不应全部显示 `No screenshot yet`。
- 合成 demo 目录中不包含真实客户名、真实截图、真实本地路径或私有数据。
