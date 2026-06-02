# Prune Spec

Status: ACTIVE

## Goal

安全清理源 PPTX 已不存在的孤立索引记录，避免索引库长期积累无效 slide、失败 job 和无引用截图。

同时提供 assembled_output 派生页清理入口，避免组装结果反复入库后污染搜索库。

## CLI

```bash
ppt-lib prune --dry-run
ppt-lib prune --apply
ppt-lib purge --type assembled_output --dry-run
ppt-lib purge --type assembled_output --apply
```

默认等同 dry-run。只有显式 `--apply` 才执行删除。

## Behavior

`prune` 会处理：

- 源文件缺失的 `presentations`。
- 这些 presentation 下属的 `slides`。
- 源文件缺失的 `index_jobs`。
- 清理后不再被任何 slide 引用的 `screenshots` 记录。

`purge --type assembled_output` 会处理：

- `origin_type = assembled_output` 的派生 slides。
- 这些 slide 所属的 output presentation。
- 关联的 `slide_lineage` 和 `assemble_runs`。
- output presentation 对应的 `index_jobs`。
- 清理后不再被引用的 `screenshots` 记录。

## Safety Rules

- dry-run 和 apply 输出同一组 count 字段。
- apply 前必须调用 SQLite backup，返回 `backup_path`。
- 删除 presentation、slide、job、screenshot 记录时必须支持超过 SQLite 单次参数上限的批量场景。
- 只删除 `settings.screenshots_dir` 内的截图文件；其他路径只删除 DB 记录。
- 输出必须列出 `removed_presentations`，方便人工审计。
- `purge --type assembled_output` 不删除原始 source slide。
