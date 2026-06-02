# Spec 12: CLI

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/cli.py`
Tasks: T7, T23, T24

## 职责

CLI 是用户和 Agent 的唯一入口。它负责参数解析、settings 加载、调用模块、输出 JSON、输出人类日志和统一错误协议。

CLI 不实现业务算法，只编排模块。

## 命令

| 命令 | 行为 |
|---|---|
| `ppt-lib setup --mode <mode> --non-interactive` | 创建/更新非敏感配置并运行诊断，交互终端默认文本 |
| `ppt-lib doctor --output json` | 聚合配置、索引库和模型链路健康检查 |
| `ppt-lib config path|get|set` | 查看配置路径、读取生效配置、写入非敏感配置 |
| `ppt-lib qa sample` | 运行本地样本 QA 并返回报告路径 |
| `ppt-lib index <path>` | 索引单个 PPTX |
| `ppt-lib index --batch <dir>` | 批量索引目录 |
| `ppt-lib search "<query>"` | 搜索，交互终端默认文本，机器读取用 `--output json` |
| `ppt-lib search "<query>" --html` | JSON + HTML 路径 |
| `ppt-lib search "<query>" --include-assembled` | 搜索包含 assembled_output 派生页 |
| `ppt-lib search "<query>" --include-assembled --dedupe-lineage` | 搜索包含派生页并按 lineage 去重 |
| `ppt-lib search "<query>" --ranking business` | 使用赢率和复用次数做业务加权排序 |
| `ppt-lib search "<query>" --narrative-role <role>` | 按叙事角色过滤搜索结果 |
| `ppt-lib status` | 库统计，交互终端默认文本 |
| `ppt-lib discover <dir>` | 项目扫描和 symlink view |
| `ppt-lib watch <dir>` | 文件监听 |
| `ppt-lib vision --test` | 诊断 |
| `ppt-lib schema --output json` | 输出 schema |
| `ppt-lib record-deal --name <name> --outcome <outcome>` | 录入 deal 基本信息 |
| `ppt-lib record-usage --deal-id <id> --slide-id <id> --deck-presentation-id <id>` | 记录 slide 使用事实并刷新统计 |
| `ppt-lib recompute-stats [--slide-id <id>]` | 重算 slides 表缓存字段 |
| `ppt-lib import-metadata --jsonl <path>` | 导入脱敏叙事 metadata JSONL |
| `ppt-lib export-metadata --output <path>` | 导出脱敏叙事 metadata JSONL |
| `ppt-lib select-slides --roles <roles> --brief <brief>` | 按叙事角色选择候选页 |
| `ppt-lib build-manifest --selection <path> --output <path>` | 将选页结果转换为 assemble manifest |
| `ppt-lib purge --type assembled_output` | 清理 assembled_output 派生页和 lineage |
| `ppt-lib assemble --manifest <path>` | 生成 assembled PPTX 和 assemble report |
| `ppt-lib assemble --manifest <path> --ingest-output` | 生成后入库并写入 lineage |

`assemble` manifest 支持 `options.on_complex_slide = "skip"`。启用后，runner 会对每一页做单页渲染预检；无法渲染的页会从 output 中跳过，并记录到 report 的 `skipped_slides`。

## 输出规则

- stdout：机器可读 JSON。
- stderr：人类日志、进度、warning。
- 成功 exit code：0。
- 参数错误 exit code：2。
- 可恢复业务错误 exit code：1。

## JSON 包装

```python
def build_envelope(command: str, payload: dict[str, object], errors: list[ErrorRecord]) -> dict[str, object]: ...
```

机器可读模式使用 `--output json`。JSON 包装必须包含：

- `_meta.schema_version`
- `_meta.command`
- `_meta.generated_at`
- `_errors`

## 错误处理

| 场景 | 行为 |
|---|---|
| 参数缺失 | argparse 错误，exit 2 |
| 配置错误 | JSON `_errors`，exit 1 |
| 下游模块返回 warning | stdout `_errors` severity warning，exit 0 或 1 视严重性 |
| 下游模块 fatal | stdout `_errors` severity error，exit 1 |
| unexpected exception | 转 `INTERNAL_ERROR`，stderr 输出简短 traceback 路径提示 |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_cli_setup_lmstudio_writes_non_sensitive_config` | setup 写配置、诊断和下一步命令 |
| `test_cli_doctor_aggregates_diagnostics_and_index_health` | doctor 聚合健康状态 |
| `test_cli_config_path_and_get_outputs_masked_values` | config path/get 遮蔽敏感值 |
| `test_cli_config_set_writes_yaml_typed_value` | config set YAML 类型写入 |
| `test_cli_config_set_rejects_sensitive_key` | config set 拒绝敏感值 |
| `test_cli_qa_sample_forwards_arguments` | qa sample 参数转发 |
| `test_cli_index_single_calls_indexer` | index 编排 |
| `test_cli_index_batch_calls_index_batch` | batch |
| `test_cli_search_outputs_envelope` | search JSON |
| `test_cli_search_html_returns_html_path` | HTML |
| `test_cli_search_forwards_assembled_view_flags` | assembled_output 搜索视图参数 |
| `test_cli_search_forwards_business_ranking_and_narrative_role` | business ranking 和叙事过滤参数 |
| `test_cli_status_outputs_stats` | status |
| `test_cli_discover_outputs_items` | discover |
| `test_cli_watch_validates_root` | watch 参数 |
| `test_cli_vision_test_outputs_report` | diagnostics |
| `test_cli_schema_outputs_json_schema` | schema |
| `test_cli_record_deal_creates_deal` | deal 录入 |
| `test_cli_record_usage_records_usage_and_recomputes` | usage 记录和统计刷新 |
| `test_cli_record_usage_error_is_structured` | usage 错误映射 |
| `test_cli_recompute_stats_updates_cache` | 手动重算缓存 |
| `test_cli_import_metadata_updates_slide_columns` | metadata 导入 |
| `test_cli_import_metadata_error_is_structured` | metadata 导入错误 |
| `test_cli_export_metadata_writes_sanitized_jsonl` | 脱敏 metadata 导出 |
| `test_cli_select_slides_outputs_report` | 自动选页报告 |
| `test_cli_build_manifest_writes_manifest` | 选页结果转换 manifest |
| `test_cli_purge_assembled_output_apply` | 派生页清理 |
| `test_cli_assemble_outputs_report` | assemble JSON report |
| `test_cli_assemble_ingest_creates_lineage` | assemble output 入库和 lineage |
| `test_cli_assemble_ingest_index_failure_keeps_pending_run` | 入库失败保留 pending 状态 |
| `test_cli_assemble_manifest_error_is_structured` | assemble manifest 错误 |
| `test_cli_assemble_failed_report_returns_run_error` | assemble failed report 映射错误 |
| `test_cli_errors_enveloped` | 错误协议 |
| `test_cli_stderr_progress_not_stdout` | stdout 稳定 |
| `test_cli_exit_codes` | exit code |

## 验收标准

- Agent 可以只读 stdout JSON。
- 人类可以通过 stderr 看进度。
- 所有命令错误格式一致。
