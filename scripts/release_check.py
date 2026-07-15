#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

BLOCKED_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".env",
    ".key",
    ".pem",
    ".p12",
}
BLOCKED_PATH_PARTS = {
    "screenshots",
    "html",
    "exports",
    "outputs",
    "__pycache__",
    ".pytest_cache",
}
PRIVATE_PATTERNS = [
    "/Users/" + "dingcheng",
    "Coding" + "-Project",
    "PPT-Library" + "-Dev",
    "zangqing" + "828",
    "SEC" + "RET=",
    "PRIVATE" + "_KEY=",
    "AWS_" + "SECRET_ACCESS_KEY=",
    "-----BEGIN " + "PRIVATE KEY-----",
    "AK" + "IA",
    "gh" + "p_",
    "github_" + "pat_",
    "sk" + "-proj-",
    "sk" + "-ant-",
    "壳" + "牌",
    "长" + "安汽车",
    "云南" + "白药",
    "如" + "新",
    "长" + "隆",
    "爱" + "帛",
    "达" + "能",
]
SECRET_REGEX_PATTERNS = (
    (
        "legacy_openai_api_key",
        re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}(?![A-Za-z0-9])"),
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD)"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9+/=_-]{20,}"
        ),
    ),
)
STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
SDIST_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.en.md",
    "README.md",
    "SECURITY.md",
    "VERSION",
    "pyproject.toml",
}
SDIST_ALLOWED_PREFIXES = ("docs/", "ppt_lib/", "scripts/", "skills/", "tests/")
UV_RUN_LOCKED = ("uv", "run", "--locked")


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    blocking: bool = True
    details: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PPT Library release readiness checks.")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args()

    root = repo_root()
    started = time.time()
    results: list[CheckResult] = []
    results.append(check_worktree(root))
    results.append(check_remotes(root))
    results.append(check_tracked_files(root))
    results.append(check_private_patterns(root))
    results.append(check_release_metadata(root))
    version = parse_version((root / "pyproject.toml").read_text(encoding="utf-8"))
    results.append(check_release_history(root, version))
    results.extend(run_validation_commands(root))
    results.append(check_build_artifacts(root, version))
    results.append(run_demo_smoke(root))

    payload = {
        "status": "pass" if all(item.status == "pass" or not item.blocking for item in results) else "fail",
        "duration_seconds": round(time.time() - started, 2),
        "results": [item.__dict__ for item in results],
    }
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print_text_report(payload)
    return 0 if payload["status"] == "pass" else 1


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(result.stdout.strip())


def check_worktree(root: Path) -> CheckResult:
    result = run(["git", "status", "--porcelain"], root, timeout=30)
    dirty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    allowed = [
        line
        for line in dirty_lines
        if line.endswith("docs/reviews/") or line.endswith("docs/reviews/open-source-maturity-assessment-2026-06-06.md")
    ]
    unexpected = [line for line in dirty_lines if line not in allowed]
    if unexpected:
        return CheckResult(
            "working_tree",
            "fail",
            "Working tree has uncommitted changes.",
            details={"unexpected": unexpected, "allowed": allowed},
        )
    return CheckResult("working_tree", "pass", "Working tree is clean or only has ignored local review notes.")


def check_remotes(root: Path) -> CheckResult:
    origin = run(["git", "remote", "get-url", "origin"], root, timeout=30).stdout.strip()
    public = run(["git", "remote", "get-url", "public"], root, timeout=30).stdout.strip()
    expected_origin = "https://github.com/" + "zangqing" + "828-ux/PPT-Library" + "-Dev.git"
    ok = origin == expected_origin and public == "https://github.com/MainQuestAI/PPT-Library.git"
    if not ok:
        return CheckResult("remotes", "fail", "Unexpected git remotes.", details={"origin": origin, "public": public})
    return CheckResult("remotes", "pass", "origin and public remotes match release policy.")


def check_tracked_files(root: Path) -> CheckResult:
    files = git_ls_files(root)
    blocked: list[str] = []
    for item in files:
        path = Path(item)
        if path.suffix.lower() in BLOCKED_EXTENSIONS:
            blocked.append(item)
            continue
        if any(part in BLOCKED_PATH_PARTS for part in path.parts):
            blocked.append(item)
    if blocked:
        return CheckResult("tracked_files", "fail", "Tracked files include generated or sensitive file types.", details={"files": blocked})
    return CheckResult("tracked_files", "pass", "Tracked files do not include blocked generated or sensitive file types.")


def check_private_patterns(root: Path) -> CheckResult:
    files = [
        item
        for item in git_ls_files(root)
        if Path(item).suffix.lower() in {".md", ".py", ".toml", ".yml", ".yaml", ".json", ".txt", ""}
    ]
    matches: list[dict[str, object]] = []
    for relative in files:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _private_content_matches(text):
            matches.append({"file": relative, "pattern": pattern})
    if matches:
        return CheckResult(
            "private_patterns",
            "fail",
            "Potential private patterns found in tracked text.",
            details={"matches": matches[:50]},
        )
    return CheckResult("private_patterns", "pass", "No configured private patterns found in tracked text.")


def _private_content_matches(text: str) -> list[str]:
    matches = [pattern for pattern in PRIVATE_PATTERNS if pattern in text]
    matches.extend(
        label
        for label, pattern in SECRET_REGEX_PATTERNS
        if pattern.search(text)
    )
    return sorted(set(matches))


def check_release_metadata(root: Path) -> CheckResult:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = parse_version(pyproject)
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_en = (root / "README.en.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    license_text = (root / "LICENSE").read_text(encoding="utf-8") if (root / "LICENSE").exists() else ""
    missing: list[str] = []
    if not version:
        missing.append("pyproject version must be present")
    if version_file != version:
        missing.append("VERSION must match pyproject version")
    if 'license = "Apache-2.0"' not in pyproject:
        missing.append("pyproject license must be Apache-2.0")
    if "Apache License 2.0" not in readme or "Apache License 2.0" not in readme_en:
        missing.append("README license sections must mention Apache License 2.0")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        missing.append("LICENSE must contain Apache License 2.0 text")
    if f"[{version}]" not in changelog:
        missing.append("CHANGELOG.md must include current version")
    if is_stable_version(version) and f"docs/releases/v{version}.md" not in git_ls_files(root):
        missing.append(f"docs/releases/v{version}.md must exist")
    if missing:
        return CheckResult("release_metadata", "fail", "Release metadata is incomplete.", details={"missing": missing})
    return CheckResult("release_metadata", "pass", "Release metadata is consistent.", details={"version": version})


def is_stable_version(version: str) -> bool:
    return bool(STABLE_VERSION_PATTERN.fullmatch(version))


def check_release_history(root: Path, version: str) -> CheckResult:
    if not is_stable_version(version):
        return CheckResult(
            "release_history",
            "pass",
            "Development and prerelease versions do not require public/main ancestry.",
            details={"version": version, "version_kind": "development"},
        )

    public_ref = run(["git", "rev-parse", "--verify", "public/main"], root, timeout=30, check=False)
    if public_ref.returncode != 0:
        return CheckResult(
            "release_history",
            "fail",
            "Stable release cannot verify public/main.",
            details={"code": "RELEASE_PUBLIC_REF_MISSING", "version": version},
        )
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"],
        root,
        timeout=30,
        check=False,
    )
    if ancestry.returncode != 0:
        return CheckResult(
            "release_history",
            "fail",
            "Stable release must be built from history based on public/main.",
            details={"code": "RELEASE_WRONG_HISTORY", "version": version},
        )
    commit_count_result = run(
        ["git", "rev-list", "--count", "public/main..HEAD"],
        root,
        timeout=30,
        check=False,
    )
    commit_count = -1
    if commit_count_result.returncode == 0:
        try:
            commit_count = int(commit_count_result.stdout.strip())
        except ValueError:
            pass
    if commit_count not in {0, 1}:
        return CheckResult(
            "release_history",
            "fail",
            "Stable release must be a clean single-commit snapshot of public/main.",
            details={
                "code": "RELEASE_PRIVATE_HISTORY",
                "version": version,
                "commits_after_public_main": commit_count,
            },
        )
    merges = run(
        ["git", "rev-list", "--merges", "public/main..HEAD"],
        root,
        timeout=30,
        check=False,
    )
    if merges.returncode != 0 or merges.stdout.strip():
        return CheckResult(
            "release_history",
            "fail",
            "Stable release snapshot must not contain merge commits.",
            details={"code": "RELEASE_MERGE_HISTORY", "version": version},
        )
    if commit_count == 1:
        parent = run(["git", "rev-parse", "HEAD^"], root, timeout=30, check=False)
        if (
            parent.returncode != 0
            or public_ref.returncode != 0
            or parent.stdout.strip() != public_ref.stdout.strip()
        ):
            return CheckResult(
                "release_history",
                "fail",
                "Stable release snapshot must be a direct child of public/main.",
                details={"code": "RELEASE_PRIVATE_HISTORY", "version": version},
            )
    return CheckResult(
        "release_history",
        "pass",
        "Stable release is public/main or a clean single-commit snapshot.",
        details={
            "version": version,
            "version_kind": "stable",
            "commits_after_public_main": commit_count,
        },
    )


def run_validation_commands(root: Path) -> list[CheckResult]:
    commands = [
        (
            "pytest",
            ["uv", "run", "--locked", "--extra", "test", "--extra", "workbench", "pytest"],
            300,
        ),
        ("ruff", ["uv", "run", "--locked", "--extra", "lint", "ruff", "check", "."], 120),
        ("mypy", ["uv", "run", "--locked", "--extra", "lint", "mypy"], 300),
    ]
    results: list[CheckResult] = []
    for name, command, timeout in commands:
        result = run(command, root, timeout=timeout, check=False)
        if result.returncode == 0:
            results.append(CheckResult(name, "pass", f"{name} passed."))
        else:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    f"{name} failed or timed out.",
                    details={
                        "returncode": result.returncode,
                        "stdout_tail": result.stdout[-4000:],
                        "stderr_tail": result.stderr[-4000:],
                    },
                )
            )
    return results


def check_build_artifacts(root: Path, version: str) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="ppt-lib-build-") as temp:
        dist_dir = Path(temp)
        build = run(
            ["uv", "build", "--out-dir", str(dist_dir)],
            root,
            timeout=180,
            check=False,
        )
        if build.returncode != 0:
            return CheckResult(
                "build_artifacts",
                "fail",
                "Package build failed.",
                details={"stdout_tail": build.stdout[-4000:], "stderr_tail": build.stderr[-4000:]},
            )
        return check_built_artifacts(root, dist_dir, version)


def check_built_artifacts(root: Path, dist_dir: Path, version: str) -> CheckResult:
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        return CheckResult(
            "build_artifacts",
            "fail",
            "Expected exactly one sdist and one wheel.",
            details={"sdists": [item.name for item in sdists], "wheels": [item.name for item in wheels]},
        )

    tracked = set(git_ls_files(root))
    unexpected_members: set[str] = set()
    blocked_members: set[str] = set()
    private_content_matches: list[dict[str, str]] = []
    sdist_prefix = f"ppt_library-{version}/"

    with tarfile.open(sdists[0], "r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            name = member.name
            if not _safe_archive_member(name) or not name.startswith(sdist_prefix):
                blocked_members.add(name)
                continue
            if not member.isfile():
                blocked_members.add(name)
                continue
            relative = name[len(sdist_prefix) :]
            extracted = archive.extractfile(member)
            if extracted is not None:
                private_content_matches.extend(
                    {
                        "archive": "sdist",
                        "member": relative,
                        "pattern": pattern,
                    }
                    for pattern in _private_content_matches_bytes(extracted.read())
                )
            if relative == "PKG-INFO":
                continue
            if not _allowed_sdist_member(relative):
                blocked_members.add(relative)
            elif relative not in tracked:
                unexpected_members.add(relative)

    wheel_dist_info_prefix = f"ppt_library-{version}.dist-info/"
    with zipfile.ZipFile(wheels[0]) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            if not _safe_archive_member(name):
                blocked_members.add(name)
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                blocked_members.add(name)
                continue
            private_content_matches.extend(
                {
                    "archive": "wheel",
                    "member": name,
                    "pattern": pattern,
                }
                for pattern in _private_content_matches_bytes(archive.read(info))
            )
            if name.startswith(wheel_dist_info_prefix):
                continue
            if not name.startswith("ppt_lib/"):
                blocked_members.add(name)
            elif name not in tracked:
                unexpected_members.add(name)

    if unexpected_members or blocked_members or private_content_matches:
        return CheckResult(
            "build_artifacts",
            "fail",
            "Built artifacts contain untracked, disallowed, or sensitive content.",
            details={
                "unexpected_members": sorted(unexpected_members),
                "blocked_members": sorted(blocked_members),
                "private_content_matches": private_content_matches[:50],
                "sdist": sdists[0].name,
                "wheel": wheels[0].name,
            },
        )
    return CheckResult(
        "build_artifacts",
        "pass",
        "Built sdist and wheel contain only tracked allowlisted files, generated metadata, and no configured sensitive content.",
        details={"sdist": sdists[0].name, "wheel": wheels[0].name},
    )


def check_coverage_report(
    report_path: Path,
    *,
    minimum_statement_percent: float = 80.0,
    minimum_branch_percent: float = 65.0,
) -> CheckResult:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        totals = payload["totals"]
        covered_statements = int(totals["covered_lines"])
        statement_count = int(totals["num_statements"])
        covered_branches = int(totals["covered_branches"])
        branch_count = int(totals["num_branches"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return CheckResult(
            "coverage",
            "fail",
            "Coverage JSON is missing or invalid.",
            details={"code": "COVERAGE_REPORT_INVALID", "error": str(exc)},
        )

    statement_percent = 100.0 if statement_count == 0 else covered_statements / statement_count * 100
    branch_percent = 100.0 if branch_count == 0 else covered_branches / branch_count * 100
    details = {
        "statement_percent": round(statement_percent, 2),
        "minimum_statement_percent": minimum_statement_percent,
        "branch_percent": round(branch_percent, 2),
        "minimum_branch_percent": minimum_branch_percent,
    }
    if statement_percent < minimum_statement_percent or branch_percent < minimum_branch_percent:
        return CheckResult(
            "coverage",
            "fail",
            "Coverage is below the required statement or branch threshold.",
            details={"code": "COVERAGE_GATE_FAILED", **details},
        )
    return CheckResult("coverage", "pass", "Statement and branch coverage thresholds passed.", details=details)


def _safe_archive_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _allowed_sdist_member(relative: str) -> bool:
    return relative in SDIST_ROOT_FILES or relative.startswith(SDIST_ALLOWED_PREFIXES)


def _private_content_matches_bytes(payload: bytes) -> list[str]:
    return _private_content_matches(payload.decode("utf-8", errors="ignore"))


def run_demo_smoke(root: Path) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="ppt-lib-release-check-") as temp:
        temp_path = Path(temp)
        decks_dir = temp_path / "decks"
        home_dir = temp_path / "home"
        manifest_path = home_dir / "sources-manifest.json"
        review_pack_path = home_dir / "review-pack.jsonl"
        env = os.environ | {"PPT_LIB_EMBEDDING_PROVIDER": "fake", "PPT_LIB_VISION_PROVIDER": "text_extraction"}
        commands = [
            [*UV_RUN_LOCKED, "--extra", "demo", "python", "scripts/create_demo_decks.py", "--output", str(decks_dir)],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "setup", "--quick", "--non-interactive"],
            [
                *UV_RUN_LOCKED,
                "ppt-lib",
                "--home-dir",
                str(home_dir),
                "sources",
                "manifest",
                "--library",
                str(decks_dir),
                "--manifest-output",
                str(manifest_path),
                "--output",
                "json",
            ],
            [
                *UV_RUN_LOCKED,
                "ppt-lib",
                "--home-dir",
                str(home_dir),
                "init",
                "--manifest",
                str(manifest_path),
                "--non-interactive",
                "--output",
                "json",
            ],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "sources", "scan", "--dry-run", "--output", "json"],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "sources", "scan", "--apply", "--output", "json"],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "index", "--from-sources"],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "enrich-decks", "--pending", "--limit", "20", "--output", "json"],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "insights", "key-pages", "--output", "json"],
            [*UV_RUN_LOCKED, "ppt-lib", "--home-dir", str(home_dir), "insights", "review-pack", "--output", str(review_pack_path)],
            [
                *UV_RUN_LOCKED,
                "ppt-lib",
                "--home-dir",
                str(home_dir),
                "record-deal",
                "--name",
                "Synthetic Retail Win",
                "--outcome",
                "won",
                "--description",
                "Synthetic demo opportunity for retail growth proposal.",
                "--industry",
                "retail",
                "--scenario",
                "proposal",
                "--tags",
                "demo,architecture,key-page",
            ],
        ]
        outputs: list[dict[str, Any]] = []
        try:
            for command in commands:
                completed = run(command, root, timeout=300, env=env)
                if "ppt-lib" not in command:
                    continue
                maybe_payload = parse_json(completed.stdout)
                if maybe_payload:
                    assert_no_errors(command, maybe_payload)
                    outputs.append(maybe_payload)
            key_pages = outputs[-3]
            first = key_pages["items"][0]
            usage = run(
                [
                    *UV_RUN_LOCKED,
                    "ppt-lib",
                    "--home-dir",
                    str(home_dir),
                    "record-usage",
                    "--deal-id",
                    "1",
                    "--slide-id",
                    str(first["slide_id"]),
                    "--deck-presentation-id",
                    str(first["presentation"]["id"]),
                ],
                root,
                timeout=120,
                env=env,
            )
            assert_no_errors(["record-usage"], parse_json(usage.stdout))
            search = run(
                [
                    *UV_RUN_LOCKED,
                    "ppt-lib",
                    "--home-dir",
                    str(home_dir),
                    "search",
                    "业务架构 价值",
                    "--ranking",
                    "business",
                    "--threshold",
                    "0.0",
                    "--html",
                ],
                root,
                timeout=120,
                env=env,
            )
            search_payload = parse_json(search.stdout)
            assert_no_errors(["search", "--html"], search_payload)
            html_path = Path(search_payload["html_path"])
            html = html_path.read_text(encoding="utf-8")
            if "<img " not in html:
                raise RuntimeError("Search HTML does not include rendered slide screenshots.")
            if not key_pages["items"]:
                raise RuntimeError("insights key-pages returned no candidates.")
            return CheckResult(
                "demo_smoke",
                "pass",
                "Synthetic demo completed with key pages, review pack, usage tracking, and screenshot HTML.",
                details={
                    "key_pages": len(key_pages["items"]),
                    "review_pack": review_pack_path.exists(),
                    "html_path": str(html_path),
                    "has_screenshot": "<img " in html,
                },
            )
        except Exception as exc:
            return CheckResult("demo_smoke", "fail", str(exc), details={"temp_dir": str(temp_path)})


def parse_version(pyproject: str) -> str:
    for line in pyproject.splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def git_ls_files(root: Path) -> list[str]:
    result = run(["git", "ls-files"], root, timeout=30)
    return [line for line in result.stdout.splitlines() if line]


def run(
    command: list[str],
    cwd: Path,
    *,
    timeout: int,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", "replace") if exc.stdout else "")
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", "replace") if exc.stderr else "timed out")
        return subprocess.CompletedProcess(command, 124, out, err)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr[-1000:] or result.stdout[-1000:]}")
    return result


def parse_json(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object output.")
    return data


def assert_no_errors(command: list[str], payload: dict[str, Any]) -> None:
    errors = [item for item in payload.get("_errors", []) if item.get("severity") == "error"]
    if errors:
        raise RuntimeError(f"{' '.join(command)} returned errors: {errors}")


def print_text_report(payload: dict[str, Any]) -> None:
    print(f"PPT Library release check: {payload['status'].upper()} ({payload['duration_seconds']}s)")
    for item in payload["results"]:
        marker = "PASS" if item["status"] == "pass" else "FAIL"
        print(f"- {marker} {item['name']}: {item['message']}")
        if item.get("details") and item["status"] != "pass":
            print(json.dumps(item["details"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if shutil.which("uv") is None:
        print("uv is required to run release checks.", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main())
