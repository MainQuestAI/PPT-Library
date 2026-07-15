# Agent Adapters

本文用于把 `ppt-library` Skill 安装或同步到不同本地 Agent 运行时。

## 目录结构

复制整个 skill 目录，并保留结构：

```text
ppt-library/
  SKILL.md
  references/
    agent-adapters.md
```

展示名称、描述和版本统一写在 `SKILL.md` frontmatter 中。

不要把 `.gstack/`、真实 PPT、样本清单、截图、QA 报告、API key 或本地凭据一起复制。

## Host Matrix

| Host | 推荐本地目录 | 调用方式 | 验证方式 |
|---|---|---|---|
| Codex | `~/.codex/skills/ppt-library` | 提到 `$ppt-library` 或 PPT Library CLI 任务 | 新会话里确认 skill 可被触发 |
| Claude Code | `~/.claude/skills/ppt-library` | 要求 Claude Code 使用 `ppt-library` skill | 新会话里让它概述触发场景 |
| Hermes | `~/.hermes/skills/ppt-library` | 要求 Hermes 使用本地 `ppt-library` skill | 可用时运行 `hermes skills list --source local` |
| OpenCode | 使用其配置的 local skill directory | 任务中明确提到 `ppt-library` | 通过运行时 skill list 或新任务验证 |
| OpenClaw | 使用其配置的 local skill directory | 任务中明确提到 `ppt-library` | 通过运行时 skill list 或新任务验证 |
| 通用 Agent | 将本目录加入技能或上下文目录 | 附加 `SKILL.md` | 询问它第一步会运行哪个 `ppt-lib` 命令 |

如果宿主没有原生 skill 机制，把 `SKILL.md` 作为任务上下文注入，并要求它遵守 CLI 契约。

## 适配契约

所有宿主都必须保留这些规则：

- `ppt-lib` 是唯一操作入口。
- stdout JSON 是真相源，stderr 只用于进度信息。
- 搜索结果要交给另一个 Agent 或程序消费时，使用 `search --contract-v2 --output json`；该命令直接返回 `ppt_library.search_response.v2` envelope。
- 汇报成功前必须同时检查进程退出码与 `_errors[*].severity`；`error` 阻断，`warning` 随结果汇报。
- smoke test 优先使用 `--home-dir /tmp/ppt-lib-smoke`。
- 建库前应先 `sources scan --dry-run`，再由用户确认后执行 `sources scan --apply` 写入 scan-state。未确认前不允许扫描：
  - `~/Library/Caches`
  - `~/Downloads`
  - 微信缓存目录
  - WPS/WXWork 缓存目录
- `index --from-sources --with-ai-summary` 前必须确认 `profile build` 返回 `ready=true`。
- `watch` 只有用户明确要求时才启动。
- 客户文件路径和本地样本数据只留在本机。
- `compose` 默认只生成可审查 run；`--confirm <run-dir>/narrative-plan.json` 执行该 run 已冻结的 selection/manifest；只有明确授权全自动时使用 `--auto`。
- `capabilities --probe` 会真实访问已配置 provider，并设置短超时；普通 capability 检查不加 `--probe`。
- Workbench 默认只绑定 loopback。远程绑定必须同时提供 `--allow-remote --auth-token-env <ENV_NAME>`；绑定通配地址时还要用 `--cors-origin` 明确列出可信浏览器来源。token 只从环境变量读取，并拥有整个本地素材库数据库的管理员权限。
- Workbench 的 `workspace_id` 只是在单个服务进程内防止请求误投的 namespace 标签，不提供多租户数据隔离。远程 HTTP 仅限可信网络，跨网络访问应放在 TLS 反向代理或 SSH 隧道后；多人身份、租户隔离与 OIDC 留到后续企业版迭代。

## 安装后 Smoke Prompt

```text
Use the ppt-library skill. Check whether PPT Library is usable on this machine without indexing any private files. Report CLI availability, JSON schema health, index status, and model diagnostics.
```

预期首批命令：

```bash
ppt-lib --version
ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
ppt-lib --home-dir /tmp/ppt-lib-smoke status
ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test
ppt-lib --home-dir /tmp/ppt-lib-smoke capabilities --output json
```

如果 CLI 只在源码 checkout 内可用：

```bash
uv run --extra test ppt-lib --version
uv run --extra test ppt-lib --home-dir /tmp/ppt-lib-smoke schema --output json
uv run --extra test ppt-lib --home-dir /tmp/ppt-lib-smoke status
uv run --extra test ppt-lib --home-dir /tmp/ppt-lib-smoke vision --test
uv run --extra test ppt-lib --home-dir /tmp/ppt-lib-smoke capabilities --output json
```

## Troubleshooting

- Skill not found：确认目录名是 `ppt-library`，且 `SKILL.md` 在第一层。
- Hermes 不显示：检查本地 skills 目录，避免直接改 Hermes bundled manifest。
- Claude Code 看到旧内容：复制后开启新会话。
- Codex 看到旧内容：确认已安装 skill 是否是旧快照，再从本仓库重新复制。
- OpenCode / OpenClaw 无 skill loader：把 `SKILL.md` 和本文作为上下文交给它。
