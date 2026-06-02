# Search Evaluation Spec

Status: ACTIVE

## Goal

衡量语义搜索是否能把真实业务缺口匹配到预期历史 slide，并为默认阈值提供可复跑证据。

## Manifest

真实评估清单放在 `.gstack/search-evaluation-manifest.json`，不得提交到仓库。

仓库只保留脱敏示例：`docs/search-evaluation-manifest.example.json`。

每条 query 必须包含：

- `id`
- `query`
- 至少一种期望匹配条件：
  - `expected_slide_ids`
  - `expected_source_keywords`
  - `expected_title_keywords`
  - `expected_file_keywords`

可选字段：

- `notes`
- 顶层 `thresholds`

## Metrics

- `recall_at_5`
- `recall_at_10`
- `mrr`
- `target_met`
- `quality_status`
- 单 query 的 `failure_reason`

默认目标：`recall_at_10 >= 0.8`。

## CLI

```bash
ppt-lib eval-search --manifest .gstack/search-evaluation-manifest.json --top-k 10
ppt-lib eval-search --manifest .gstack/search-evaluation-manifest.json --calibrate
```

## Failure Rules

- 空查询清单直接报 `EVAL_MANIFEST_ERROR`。
- 缺少期望匹配条件直接报 `EVAL_MANIFEST_ERROR`。
- 空搜索结果记录为 `failure_reason=empty_results`。
- 搜索有结果但不命中预期记录为 `failure_reason=expected_result_not_in_top_k`。
- embedding provider 失败必须保留原始错误码。

