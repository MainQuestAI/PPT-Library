# Spec 13: Local Sample QA

Status: ACTIVE / REQUIRED BEFORE CODING
Module: `ppt_lib/sample_qa.py`

## 职责

本地样本 QA 负责用桌面真实 PPT 验证 `discover -> index -> status -> search -> vision` 链路，并优先使用 LM Studio 本地模型。

它不复制用户 PPT 到仓库，不修改正式索引库，不上传文件。

## 样本策略

- baseline：小型与中型真实材料，验证日常可用性。
- complex：图片密集、页数多、图表/备注密集材料，验证稳定性。
- 压力样本只在显式选择 complex 或 all 时运行。
- 样本清单从 `.gstack/local-sample-manifest.json` 或 `PPT_LIB_SAMPLE_MANIFEST` 读取，仓库源码不保存个人桌面路径。

固定过滤：

- 跳过 Office 临时文件和锁文件，文件名以 `~$` 或 `.~` 开头。
- 跳过 `.venv`、`.pydeps`、`node_modules`、`__pycache__`。
- 不复制源文件，只记录绝对路径、大小、phase 和运行结果。

## 本地模型配置

样本 QA 默认使用：

- `embedding_provider=lmstudio`
- `lmstudio_embedding_model=text-embedding-nomic-embed-text-v1.5`
- `embedding_dimensions=768`
- `vision_provider=lmstudio`
- `lmstudio_vision_model=google/gemma-4-26b-a4b`
- `lmstudio_base_url=http://127.0.0.1:1234/v1`

复杂样本默认设置 `vision_max_slides_per_file=3`，超过上限的页面走文本提取 fallback。

## 输出

- 独立 home 目录：`.gstack/local-sample-qa-home/`
- 源样本清单：`.gstack/local-sample-manifest.json`
- Markdown 报告：`.gstack/qa-reports/local-sample-qa-*.md`
- JSON 摘要：`.gstack/qa-reports/local-sample-qa-latest.json`
- 本轮样本快照：`.gstack/qa-reports/local-sample-manifest.json`

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_load_samples_from_manifest` | 样本清单稳定 |
| `test_select_samples_by_phase_and_limit` | phase 和 max-files 生效 |
| `test_build_local_sample_settings_defaults_to_lmstudio` | 本地模型默认配置 |
| `test_sample_manifest_skips_missing_without_copying` | 缺失样本可记录 |
| `test_discovery_checks_find_sample_and_ignore_locks` | discovery 链路和过滤规则生效 |
| `test_searches_warn_when_query_returns_no_results` | 搜索验收不能空跑 |
| `test_write_markdown_report_contains_failures` | 报告可读 |

## 验收标准

- LM Studio 不可用时，报告明确标记 preflight 失败或 skipped。
- 单个坏文件不终止整轮 QA。
- 搜索验收至少覆盖 `AI 智能体`、`数据治理`、`CMS 部署`、`SCRM`、`微信小店`、`营销自动化`。
- 搜索空结果、旧失败 job、混合 embedding 维度跳过都会进入报告并影响 `overall_status`。
- `--fresh` 会清理样本 QA home 中的生成状态，避免旧索引让报告误判为通过。
- 搜索质量基线会记录期望命中关键词、Top-3 命中、空结果和偏题结果。
