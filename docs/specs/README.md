# PPT Library 模块 Spec 索引

Status: ACTIVE / REQUIRED BEFORE CODING
Canonical contract: current `ppt_lib` implementation, CLI schema output, and module specs in this folder.

本目录是开发前的模块级设计入口。任何模块开始编码前，必须先确认对应 spec 已覆盖职责、接口、数据、错误处理、测试和验收标准。

## Spec 清单

| 顺序 | Spec | 覆盖模块 | 主要任务 |
|---|---|---|---|
| 01 | [config-settings.md](config-settings.md) | `ppt_lib/config.py`, `ppt_lib/settings.py` | T1, T15 |
| 02 | [db.md](db.md) | `ppt_lib/db.py` | T2, T9, T21, T22 |
| 03 | [embedding.md](embedding.md) | `ppt_lib/embedding.py` | T3 |
| 04 | [screenshot.md](screenshot.md) | `ppt_lib/screenshot.py` | T4, T11 |
| 05 | [vision.md](vision.md) | `ppt_lib/vision.py` | T10 |
| 06 | [diagnostics.md](diagnostics.md) | `ppt_lib/diagnostics.py` | T19 |
| 07 | [discovery.md](discovery.md) | `ppt_lib/discovery.py` | T16 |
| 08 | [watch.md](watch.md) | `ppt_lib/watch.py` | T17 |
| 09 | [indexer.md](indexer.md) | `ppt_lib/indexer.py` | T5, T12 |
| 10 | [searcher-clustering.md](searcher-clustering.md) | `ppt_lib/searcher.py`, `ppt_lib/clustering.py` | T6, T8, T13, T20 |
| 11 | [html-renderer.md](html-renderer.md) | `ppt_lib/html_renderer.py` | T18 |
| 12 | [cli.md](cli.md) | `ppt_lib/cli.py` | T7, T23, T24 |
| 13 | [local-sample-qa.md](local-sample-qa.md) | `ppt_lib/sample_qa.py` | 本地样本 QA |
| 14 | [search-evaluation.md](search-evaluation.md) | `ppt_lib/evaluation.py` | v0.2 搜索质量评估 |
| 15 | [prune.md](prune.md) | `ppt_lib/prune.py` | v0.2 安全清理 |

## 开发顺序

1. 基础层：config/settings、db。
2. 能力层：embedding、screenshot、vision、diagnostics。
3. 数据入口：discovery、indexer。
4. 搜索和呈现：searcher/clustering、html_renderer。
5. 用户入口：watch、cli。

## 全局约束

- 所有模块必须使用结构化错误对象，格式以当前 CLI JSON envelope 和 module specs 为准。
- 所有路径在 JSON 输出中使用绝对路径。
- 机器可读 stdout 必须稳定，日志走 stderr。
- 任何测试涉及外部 API、LibreOffice、watchdog、Ollama 或 LM Studio 时，默认 mock；只保留最小真实 smoke test。
- 实现必须保持 local-first：本地文件、本地 SQLite、本地截图目录，模型能力通过可替换 provider 调用。
