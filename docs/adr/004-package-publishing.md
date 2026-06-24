# ADR-004: Package Publishing Strategy

**Status:** Accepted
**Date:** 2026-06-23
**Deciders:** Project Owner, Architecture Review
**Superseded-By:** None

---

## Context

PPT Library v1.4.1 当前仅支持源码安装（`git clone` + `uv sync` 或 `pip install -e .`）。Spec Pack 03-v1.5 §4.8 要求建立官方 package registry 发布流程，支持 wheel/sdist 安装。

当前状态：
- PyPI 包名 `ppt-library` 未被占用（2026-06-23 检查）
- 仓库有两个 remote：`origin`（私有 dev repo）和 `public`（公开 repo）
- `release_check.py` 脚本存在，但包含仓库私有路径假设
- 无 SBOM、无 dependency vulnerability scan、无 signing/attestation

---

## Decision

采用 **PyPI 官方发布 + GitHub Release 备份 + 严格 release gate** 方案：

### 1. Package Registry

**主发布渠道**：PyPI（`https://pypi.org/project/ppt-library/`）

**备份渠道**：GitHub Release（`https://github.com/MainQuestAI/PPT-Library/releases`）

### 2. Package Metadata

```toml
[project]
name = "ppt-library"
version = "1.5.0"
description = "Local-first PPT asset intelligence CLI"
readme = "README.md"
requires-python = ">=3.12"
license = {text = "Apache-2.0"}
authors = [
  {name = "MainQuestAI", email = "support@mainquest.ai"}
]
classifiers = [
  "Development Status :: 4 - Beta",
  "Environment :: Console",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Operating System :: MacOS",
  "Operating System :: POSIX :: Linux",
  "Programming Language :: Python :: 3.12",
  "Topic :: Office/Business",
  "Topic :: Text Processing :: Indexing",
]
```

### 3. Optional Extras

```toml
[project.optional-dependencies]
test = ["pytest>=8.0"]
lint = ["ruff>=0.4", "mypy>=1.10"]
paddleocr = ["paddleocr-mcp>=0.1"]
workbench = ["fastapi>=0.110", "uvicorn>=0.29"]  # v1.8
```

### 4. Build & Publish

```bash
# Build
uv build

# Publish to PyPI
uv publish

# Create GitHub Release
gh release create v1.5.0 dist/* --title "v1.5.0" --notes-file RELEASE_NOTES.md
```

### 5. Signing & Attestation

- PyPI trusted publishing（OIDC from GitHub Actions）
- GitHub Release attestation（`gh attestation sign`）
- SBOM generation（`cyclonedx-py`）
- Dependency vulnerability scan（`pip-audit`）

### 6. Release Gate

v1.5 不得发布，除非：

1. 全量 automated tests 通过
2. Current CLI regression suite 通过
3. Deck Master Contract UAT 100%
4. Migration fixture 全部通过
5. Crash-resume fixture 通过
6. 10k synthetic slides 索引报告存在
7. 无 P0/P1 数据损坏风险
8. Wheel clean install 通过
9. `release_check.py` 不含仓库私有路径假设
10. Release notes 列出兼容与已知限制

### 7. Platform Matrix

**Tier-1**：
- macOS current supported versions，arm64/x64
- Ubuntu LTS x64

**Tier-2**：
- Windows 11 x64
- 无 LibreOffice 的 text-only mode

### 8. Clean Install Smoke

```bash
# Clean venv
python -m venv /tmp/ppt-lib-smoke
source /tmp/ppt-lib-smoke/bin/activate
pip install ppt-library==1.5.0

# Smoke test
ppt-lib --version
ppt-lib setup --quick --non-interactive
ppt-lib schema --output json
ppt-lib --home-dir /tmp/ppt-lib-home status --output json
```

---

## Consequences

### Positive

- ✅ 用户可通过 `pip install ppt-library` 一键安装
- ✅ PyPI 提供全球 CDN 和版本管理
- ✅ GitHub Release 提供备份和离线安装
- ✅ SBOM 和 vulnerability scan 提高安全性
- ✅ Trusted publishing 和 attestation 提高可信度

### Negative

- ⚠️ PyPI 包名需要持续监控，防止被恶意占用
- ⚠️ Release gate 严格，发布周期可能延长
- ⚠️ Windows Tier-2 支持需要额外 CI 配置
- ⚠️ 需要维护 RELEASE_NOTES.md 和 CHANGELOG.md 同步

### Neutral

- 🔘 PyPI 和 GitHub Release 双渠道发布，增加发布工作量但提高可用性
- 🔘 Optional extras 增加包复杂度，但减少核心依赖

---

## Alternatives Considered

### Option A: GitHub Release only（rejected）

**描述**：只在 GitHub Release 发布 wheel/sdist，不发布到 PyPI。

**拒绝原因**：
- 用户需要手动下载 wheel 或配置 GitHub Release URL
- 无法使用 `pip install ppt-library` 一键安装
- 不符合 Python 生态惯例
- 降低可发现性

### Option B: PyPI only（rejected）

**描述**：只发布到 PyPI，不创建 GitHub Release。

**拒绝原因**：
- 无备份渠道，PyPI 故障时无法安装
- 无法离线安装
- 无法查看 release notes 和 changelog
- 不符合开源项目惯例

### Option C: PyPI + GitHub Release + strict gate（accepted）

**描述**：双渠道发布 + SBOM + attestation + 严格 release gate。

**选择原因**：
- 平衡了可用性和安全性
- 符合 Python 生态和开源项目惯例
- 严格 release gate 保证质量
- 符合 spec pack 要求

---

## Compliance

- ✅ 符合 03-v1.5 §4.8 Release Engineering
- ✅ 符合 12-release-rollout-and-backward-compatibility.md 的发布策略
- ✅ 支持 10-benchmark-quality-gates-and-test-matrix.md 的 release gate 要求

---

## Notes

- `release_check.py` 需要在 v1.5-H 任务中重构，移除仓库私有路径假设
- CI/CD pipeline 需要在 `.github/workflows/` 中配置
- SBOM 和 vulnerability scan 可以集成到 CI pipeline
- Windows Tier-2 支持需要在 GitHub Actions 中配置 Windows runner
