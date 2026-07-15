from __future__ import annotations

import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

from scripts import release_check


def _completed(command: list[str], returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def test_development_version_does_not_require_public_history(tmp_path: Path, monkeypatch) -> None:
    def fail_run(*args, **kwargs):
        raise AssertionError("development versions must not inspect public/main")

    monkeypatch.setattr(release_check, "run", fail_run)

    result = release_check.check_release_history(tmp_path, "2.0.1.dev0")

    assert result.status == "pass"
    assert result.details["version_kind"] == "development"


def test_stable_version_requires_public_main_ancestry(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        if command == ["git", "rev-parse", "--verify", "public/main"]:
            return _completed(command)
        if command == ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"]:
            return _completed(command, returncode=1)
        raise AssertionError(command)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "fail"
    assert result.details["code"] == "RELEASE_WRONG_HISTORY"


def test_stable_version_requires_public_main_ref(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        return _completed(command, returncode=1)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "fail"
    assert result.details["code"] == "RELEASE_PUBLIC_REF_MISSING"


def test_stable_version_accepts_public_main_exact_head(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        if command == ["git", "rev-parse", "--verify", "public/main"]:
            return _completed(command, stdout="public-sha\n")
        if command == ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"]:
            return _completed(command)
        if command == ["git", "rev-list", "--count", "public/main..HEAD"]:
            return _completed(command, stdout="0\n")
        if command == ["git", "rev-list", "--merges", "public/main..HEAD"]:
            return _completed(command)
        raise AssertionError(command)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "pass"
    assert result.details["version_kind"] == "stable"


def test_stable_version_accepts_one_direct_snapshot_commit(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        if command == ["git", "rev-parse", "--verify", "public/main"]:
            return _completed(command, stdout="public-sha\n")
        if command == ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"]:
            return _completed(command)
        if command == ["git", "rev-list", "--count", "public/main..HEAD"]:
            return _completed(command, stdout="1\n")
        if command == ["git", "rev-list", "--merges", "public/main..HEAD"]:
            return _completed(command)
        if command == ["git", "rev-parse", "HEAD^"]:
            return _completed(command, stdout="public-sha\n")
        raise AssertionError(command)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "pass"
    assert result.details["commits_after_public_main"] == 1


def test_stable_version_rejects_development_history(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        if command == ["git", "rev-parse", "--verify", "public/main"]:
            return _completed(command, stdout="public-sha\n")
        if command == ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"]:
            return _completed(command)
        if command == ["git", "rev-list", "--count", "public/main..HEAD"]:
            return _completed(command, stdout="12\n")
        raise AssertionError(command)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "fail"
    assert result.details["code"] == "RELEASE_PRIVATE_HISTORY"


def test_stable_version_rejects_merge_commit(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, cwd, *, timeout, check=True, env=None):
        if command == ["git", "rev-parse", "--verify", "public/main"]:
            return _completed(command, stdout="public-sha\n")
        if command == ["git", "merge-base", "--is-ancestor", "public/main", "HEAD"]:
            return _completed(command)
        if command == ["git", "rev-list", "--count", "public/main..HEAD"]:
            return _completed(command, stdout="1\n")
        if command == ["git", "rev-list", "--merges", "public/main..HEAD"]:
            return _completed(command, stdout="merge-sha\n")
        raise AssertionError(command)

    monkeypatch.setattr(release_check, "run", fake_run)

    result = release_check.check_release_history(tmp_path, "2.0.1")

    assert result.status == "fail"
    assert result.details["code"] == "RELEASE_MERGE_HISTORY"


def _write_sdist(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _write_wheel(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_artifact_gate_rejects_untracked_sdist_member(tmp_path: Path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _write_sdist(
        dist_dir / "ppt_library-2.0.1.tar.gz",
        {
            "ppt_library-2.0.1/.gitignore": b"dist/\n",
            "ppt_library-2.0.1/pyproject.toml": b"[project]",
            "ppt_library-2.0.1/ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1/docs/local-secret.md": b"secret",
            "ppt_library-2.0.1/PKG-INFO": b"metadata",
        },
    )
    _write_wheel(
        dist_dir / "ppt_library-2.0.1-py3-none-any.whl",
        {
            "ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1.dist-info/METADATA": b"metadata",
        },
    )
    monkeypatch.setattr(
        release_check,
        "git_ls_files",
        lambda root: [".gitignore", "pyproject.toml", "ppt_lib/__init__.py"],
    )

    result = release_check.check_built_artifacts(tmp_path, dist_dir, "2.0.1")

    assert result.status == "fail"
    assert "docs/local-secret.md" in result.details["unexpected_members"]


def test_artifact_gate_accepts_tracked_allowlisted_members(tmp_path: Path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _write_sdist(
        dist_dir / "ppt_library-2.0.1.tar.gz",
        {
            "ppt_library-2.0.1/pyproject.toml": b"[project]",
            "ppt_library-2.0.1/ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1/PKG-INFO": b"metadata",
        },
    )
    _write_wheel(
        dist_dir / "ppt_library-2.0.1-py3-none-any.whl",
        {
            "ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1.dist-info/METADATA": b"metadata",
        },
    )
    monkeypatch.setattr(release_check, "git_ls_files", lambda root: ["pyproject.toml", "ppt_lib/__init__.py"])

    result = release_check.check_built_artifacts(tmp_path, dist_dir, "2.0.1")

    assert result.status == "pass"


def test_artifact_gate_rejects_sensitive_content_without_exposing_value(tmp_path: Path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    secret_value = "sk-" + "A" * 48
    payload = ("OPENAI_API_KEY=" + secret_value + "\n").encode()
    _write_sdist(
        dist_dir / "ppt_library-2.0.1.tar.gz",
        {
            "ppt_library-2.0.1/pyproject.toml": b"[project]",
            "ppt_library-2.0.1/ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1/docs/leak.md": payload,
            "ppt_library-2.0.1/PKG-INFO": b"metadata",
        },
    )
    _write_wheel(
        dist_dir / "ppt_library-2.0.1-py3-none-any.whl",
        {
            "ppt_lib/__init__.py": b"",
            "ppt_library-2.0.1.dist-info/METADATA": b"metadata",
        },
    )
    monkeypatch.setattr(
        release_check,
        "git_ls_files",
        lambda root: ["pyproject.toml", "ppt_lib/__init__.py", "docs/leak.md"],
    )

    result = release_check.check_built_artifacts(tmp_path, dist_dir, "2.0.1")

    assert result.status == "fail"
    assert result.details["private_content_matches"] == [
        {"archive": "sdist", "member": "docs/leak.md", "pattern": "legacy_openai_api_key"},
        {"archive": "sdist", "member": "docs/leak.md", "pattern": "secret_assignment"},
    ]
    assert secret_value not in repr(result.details)


def test_coverage_gate_enforces_statement_and_branch_thresholds(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    report_path.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 85,
                    "num_statements": 100,
                    "covered_branches": 60,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )

    result = release_check.check_coverage_report(report_path)

    assert result.status == "fail"
    assert result.details == {
        "code": "COVERAGE_GATE_FAILED",
        "statement_percent": 85.0,
        "minimum_statement_percent": 80.0,
        "branch_percent": 60.0,
        "minimum_branch_percent": 65.0,
    }


def test_coverage_gate_accepts_both_thresholds(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    report_path.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 80,
                    "num_statements": 100,
                    "covered_branches": 65,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )

    result = release_check.check_coverage_report(report_path)

    assert result.status == "pass"


def test_coverage_gate_rejects_low_statement_coverage(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    report_path.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 79,
                    "num_statements": 100,
                    "covered_branches": 70,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )

    result = release_check.check_coverage_report(report_path)

    assert result.status == "fail"
    assert result.details["statement_percent"] == 79.0
    assert result.details["branch_percent"] == 70.0


def test_private_pattern_gate_uses_high_signal_secret_patterns(tmp_path: Path, monkeypatch) -> None:
    tracked = tmp_path / "config.py"
    tracked.write_text('PLAINTEXT_SECRET_WARNING_CODE = "CONFIG_PLAINTEXT_SECRET_DETECTED"\n', encoding="utf-8")
    monkeypatch.setattr(release_check, "git_ls_files", lambda root: ["config.py"])

    safe_result = release_check.check_private_patterns(tmp_path)

    assert safe_result.status == "pass"

    tracked.write_text("AWS_" + "SECRET_ACCESS_KEY=canary-value\n", encoding="utf-8")
    blocked_result = release_check.check_private_patterns(tmp_path)

    assert blocked_result.status == "fail"
    assert blocked_result.details["matches"] == [
        {"file": "config.py", "pattern": "AWS_" + "SECRET_ACCESS_KEY="}
    ]
    assert "canary-value" not in repr(blocked_result.details)
