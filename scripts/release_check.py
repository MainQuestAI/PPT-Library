#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    "SEC" + "RET",
    "PRIVATE" + "_KEY",
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
EXPECTED_TEST_BASELINE = "1083"


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
    results.extend(run_validation_commands(root))
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
        for pattern in PRIVATE_PATTERNS:
            if pattern in text:
                matches.append({"file": relative, "pattern": pattern})
    if matches:
        return CheckResult(
            "private_patterns",
            "fail",
            "Potential private patterns found in tracked text.",
            details={"matches": matches[:50]},
        )
    return CheckResult("private_patterns", "pass", "No configured private patterns found in tracked text.")


def check_release_metadata(root: Path) -> CheckResult:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = parse_version(pyproject)
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_en = (root / "README.en.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    license_text = (root / "LICENSE").read_text(encoding="utf-8") if (root / "LICENSE").exists() else ""
    missing: list[str] = []
    if version != "2.0.0":
        missing.append("pyproject version must be 2.0.0")
    if version_file != version:
        missing.append("VERSION must match pyproject version")
    if EXPECTED_TEST_BASELINE not in readme:
        missing.append(f"README.md test baseline must include {EXPECTED_TEST_BASELINE}")
    if EXPECTED_TEST_BASELINE not in readme_en:
        missing.append(f"README.en.md test baseline must include {EXPECTED_TEST_BASELINE}")
    if 'license = "Apache-2.0"' not in pyproject:
        missing.append("pyproject license must be Apache-2.0")
    if "Apache License 2.0" not in readme or "Apache License 2.0" not in readme_en:
        missing.append("README license sections must mention Apache License 2.0")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        missing.append("LICENSE must contain Apache License 2.0 text")
    if f"[{version}]" not in changelog:
        missing.append("CHANGELOG.md must include current version")
    if f"docs/releases/v{version}.md" not in "\n".join(git_ls_files(root)):
        missing.append(f"docs/releases/v{version}.md must exist")
    if missing:
        return CheckResult("release_metadata", "fail", "Release metadata is incomplete.", details={"missing": missing})
    return CheckResult("release_metadata", "pass", "Release metadata is consistent.", details={"version": version})


def run_validation_commands(root: Path) -> list[CheckResult]:
    commands = [
        ("pytest", ["uv", "run", "--extra", "test", "pytest"], 300),
        ("ruff", ["uv", "run", "--extra", "lint", "ruff", "check", "."], 120),
        ("mypy", ["uv", "run", "--extra", "lint", "mypy"], 300),
        ("build", ["uv", "build"], 180),
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


def run_demo_smoke(root: Path) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="ppt-lib-release-check-") as temp:
        temp_path = Path(temp)
        decks_dir = temp_path / "decks"
        home_dir = temp_path / "home"
        manifest_path = home_dir / "sources-manifest.json"
        review_pack_path = home_dir / "review-pack.jsonl"
        env = os.environ | {"PPT_LIB_EMBEDDING_PROVIDER": "fake", "PPT_LIB_VISION_PROVIDER": "text_extraction"}
        commands = [
            ["uv", "run", "--extra", "demo", "python", "scripts/create_demo_decks.py", "--output", str(decks_dir)],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "setup", "--quick", "--non-interactive"],
            [
                "uv",
                "run",
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
                "uv",
                "run",
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
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "sources", "scan", "--dry-run", "--output", "json"],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "sources", "scan", "--apply", "--output", "json"],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "index", "--from-sources"],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "enrich-decks", "--pending", "--limit", "20", "--output", "json"],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "insights", "key-pages", "--output", "json"],
            ["uv", "run", "ppt-lib", "--home-dir", str(home_dir), "insights", "review-pack", "--output", str(review_pack_path)],
            [
                "uv",
                "run",
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
                    "uv",
                    "run",
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
                    "uv",
                    "run",
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
