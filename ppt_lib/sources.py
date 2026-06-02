from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SourceRole = str


ALLOWED_SOURCE_ROLES = ("baseline", "library", "exclude")
PROFILE_FILE_NAME = "sources/profile"
SCAN_STATE_FILE_NAME = "sources/scan-state.json"
HIGH_RISK_CACHE_TOKENS = (
    "wechat",
    "weixin",
    "微信",
    "wxwork",
    "企业微信",
    "wps",
    "kingsoft",
)


class SourceError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class SourceProfile:
    baseline: list[str]
    library: list[str]
    exclude: list[str]

    @classmethod
    def empty(cls) -> SourceProfile:
        return cls(baseline=[], library=[], exclude=[])

    def to_dict(self) -> dict[str, list[str]]:
        return {"baseline": self.baseline, "library": self.library, "exclude": self.exclude}


def profile_path_for_home(home_dir: Path) -> Path:
    return home_dir.expanduser() / PROFILE_FILE_NAME


def scan_state_path_for_home(home_dir: Path) -> Path:
    return home_dir.expanduser() / SCAN_STATE_FILE_NAME


def normalize_role(role: str) -> SourceRole:
    normalized = role.strip().lower()
    if normalized not in ALLOWED_SOURCE_ROLES:
        raise SourceError(f"Invalid source role: {role}", code="SOURCE_ROLE_INVALID")
    return normalized


def normalize_source_path(raw: str) -> str:
    return str(Path(raw).expanduser().resolve(strict=False))


def load_sources_manifest(path: Path) -> SourceProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceError(f"Cannot read manifest: {path}", code="SOURCE_MANIFEST_READ_FAILED") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid JSON manifest: {path}", code="SOURCE_MANIFEST_INVALID") from exc
    return parse_sources_manifest_payload(raw)


def load_sources_profile(home_dir: Path) -> SourceProfile:
    path = profile_path_for_home(home_dir)
    if not path.exists():
        return SourceProfile.empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceError(f"Cannot read sources profile: {path}", code="SOURCE_PROFILE_READ_FAILED") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid JSON in sources profile: {path}", code="SOURCE_PROFILE_INVALID") from exc

    if not isinstance(raw, dict):
        raise SourceError("Invalid sources profile format", code="SOURCE_PROFILE_INVALID")
    baseline = raw.get("baseline", [])
    library = raw.get("library", [])
    exclude = raw.get("exclude", [])
    if not all(isinstance(item, str) for item in baseline + library + exclude):
        raise SourceError("Source profile must only contain string paths", code="SOURCE_PROFILE_INVALID")
    return SourceProfile(
        baseline=[normalize_source_path(item) for item in baseline],
        library=[normalize_source_path(item) for item in library],
        exclude=[normalize_source_path(item) for item in exclude],
    )


def write_sources_profile(home_dir: Path, profile: SourceProfile) -> Path:
    path = profile_path_for_home(home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def source_profile_hash(profile: SourceProfile) -> str:
    payload = json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def risky_source_warnings(
    profile: SourceProfile,
    *,
    roles: list[SourceRole] | None = None,
    user_home: Path | None = None,
) -> list[str]:
    selected_roles: list[str] = roles or ["baseline", "library"]
    for role in selected_roles:
        normalize_role(role)
    home = (user_home or Path.home()).expanduser().resolve(strict=False)
    downloads = home / "Downloads"
    library_caches = home / "Library" / "Caches"
    warnings: list[str] = []
    for role in selected_roles:
        if role == "exclude":
            continue
        for source in getattr(profile, role):
            path = Path(source).expanduser().resolve(strict=False)
            if path == home:
                warnings.append(f"{role}:{path} points to the user home directory")
            elif _is_path_or_child(path, downloads):
                warnings.append(f"{role}:{path} is under Downloads")
            elif _is_path_or_child(path, library_caches):
                warnings.append(f"{role}:{path} is under Library/Caches")
            elif _contains_high_risk_cache_token(path):
                warnings.append(f"{role}:{path} looks like an application cache directory")
    return sorted(dict.fromkeys(warnings))


def write_scan_state(
    home_dir: Path,
    profile: SourceProfile,
    scan_result: dict[str, object],
    *,
    roles: list[SourceRole] | None,
    risk_warnings: list[str],
    force_risky_sources: bool,
) -> Path:
    path = scan_state_path_for_home(home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": "1.0",
        "source_profile_hash": source_profile_hash(profile),
        "roles": roles or ["baseline", "library"],
        "scanned_roots": scan_result.get("scanned_roots", []),
        "file_count": scan_result.get("file_count", 0),
        "pptx_count": scan_result.get("pptx_count", 0),
        "estimated_pages": scan_result.get("estimated_pages", 0),
        "excluded_directories": scan_result.get("excluded_directories", []),
        "risk_warnings": risk_warnings,
        "force_risky_sources": force_risky_sources,
        "confirmed_at": datetime.now(UTC).isoformat(),
        "dry_run": False,
    }
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_scan_state(home_dir: Path) -> dict[str, object] | None:
    path = scan_state_path_for_home(home_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceError(f"Cannot read scan state: {path}", code="SOURCE_SCAN_STATE_READ_FAILED") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid JSON in scan state: {path}", code="SOURCE_SCAN_STATE_INVALID") from exc
    if not isinstance(raw, dict):
        raise SourceError("Invalid scan state format", code="SOURCE_SCAN_STATE_INVALID")
    return raw


def validate_scan_state_for_index(
    home_dir: Path,
    profile: SourceProfile,
    *,
    roles: list[SourceRole] | None = None,
) -> dict[str, object]:
    required_roles = roles or ["library"]
    for role in required_roles:
        normalize_role(role)
    state = load_scan_state(home_dir)
    if state is None:
        raise SourceError(
            "Run `ppt-lib sources scan --apply` before indexing from sources.",
            code="LIBRARY_BUILD_SCAN_REQUIRED",
        )
    if bool(state.get("dry_run")):
        raise SourceError(
            "Dry-run scan state cannot authorize source indexing.",
            code="LIBRARY_BUILD_SCAN_REQUIRED",
        )
    state_roles = state.get("roles", [])
    if not isinstance(state_roles, list) or not all(isinstance(item, str) for item in state_roles):
        raise SourceError("Scan state roles are invalid.", code="SOURCE_SCAN_STATE_INVALID")
    missing_roles = [role for role in required_roles if role not in state_roles]
    if missing_roles:
        raise SourceError(
            "Run `ppt-lib sources scan --apply --role library` before indexing from library sources.",
            code="LIBRARY_BUILD_SCAN_REQUIRED",
        )
    if state.get("source_profile_hash") != source_profile_hash(profile):
        raise SourceError(
            "Sources profile changed after the last applied scan. Re-run `ppt-lib sources scan --apply`.",
            code="LIBRARY_BUILD_SCAN_STALE",
        )
    risk_warnings = state.get("risk_warnings", [])
    if risk_warnings and not state.get("force_risky_sources"):
        raise SourceError(
            "Applied scan contains high-risk sources that were not explicitly confirmed.",
            code="LIBRARY_BUILD_RISK_NOT_CONFIRMED",
        )
    return state


def parse_sources_manifest_payload(payload: Any) -> SourceProfile:
    if isinstance(payload, list):
        return SourceProfile(
            baseline=[normalize_source_path(item) for item in _parse_source_list(payload)],
            library=[],
            exclude=[],
        )

    if not isinstance(payload, dict):
        raise SourceError("Manifest content must be a JSON object or array", code="SOURCE_MANIFEST_INVALID")

    body = payload.get("sources", payload)
    if not isinstance(body, dict):
        raise SourceError("Manifest must contain an object for `sources`", code="SOURCE_MANIFEST_INVALID")

    parsed: dict[str, list[str]] = {"baseline": [], "library": [], "exclude": []}
    found = False
    for role in ALLOWED_SOURCE_ROLES:
        if role not in body:
            continue
        raw_value = body[role]
        if not isinstance(raw_value, list):
            raise SourceError(f"Role '{role}' must be a list", code="SOURCE_MANIFEST_INVALID")
        parsed[role] = [normalize_source_path(item) for item in _parse_source_list(raw_value)]
        found = True
    if not found:
        raise SourceError("Manifest must define at least one role: baseline/library/exclude", code="SOURCE_MANIFEST_INVALID")
    return SourceProfile(**parsed)


def _parse_source_list(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if isinstance(value, str):
            path = value.strip()
            if not path:
                continue
            normalized_path = normalize_source_path(path)
        elif isinstance(value, dict):
            raw_path = value.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise SourceError(
                    f"Missing path in manifest item {index}",
                    code="SOURCE_MANIFEST_INVALID",
                )
            normalized_path = normalize_source_path(raw_path)
        else:
            raise SourceError(
                f"Invalid manifest item {index}: {value!r}",
                code="SOURCE_MANIFEST_INVALID",
            )
        if normalized_path in seen:
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    return normalized


def _is_path_or_child(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _contains_high_risk_cache_token(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    text = str(path).lower()
    return any(token in text or token in parts for token in HIGH_RISK_CACHE_TOKENS)


def add_source(profile: SourceProfile, role: SourceRole, source_path: str) -> SourceProfile:
    role = normalize_role(role)
    normalized_path = normalize_source_path(source_path)
    next_profile = SourceProfile(
        baseline=list(profile.baseline),
        library=list(profile.library),
        exclude=list(profile.exclude),
    )
    bucket = getattr(next_profile, role)
    if normalized_path not in bucket:
        bucket.append(normalized_path)
    return next_profile


@dataclass(frozen=True)
class SourceScanResult:
    roles: list[str]
    scanned_roots: list[tuple[str, str]]
    file_count: int
    pptx_files: list[Path]
    excluded_directories: set[str]


def collect_pptx_files(profile: SourceProfile, roles: list[SourceRole] | None = None) -> list[Path]:
    return _scan_source_paths(profile, roles=roles).pptx_files


def scan_sources(profile: SourceProfile, roles: list[SourceRole] | None = None) -> dict[str, object]:
    result = _scan_source_paths(profile, roles=roles)
    return {
        "roles": result.roles,
        "scanned_roots": result.scanned_roots,
        "file_count": result.file_count,
        "pptx_count": len(result.pptx_files),
        "estimated_pages": max(0, result.file_count),
        "excluded_directories": sorted(result.excluded_directories),
    }


def _scan_source_paths(profile: SourceProfile, roles: list[SourceRole] | None = None) -> SourceScanResult:
    selected_roles: list[str] = roles or ["baseline", "library"]
    for role in selected_roles:
        normalize_role(role)

    exclude_dir_names = {
        ".stversions",
        ".gstack",
        ".cache",
        "cache",
        "caches",
        "cached",
        "tmp",
        "temp",
        "dist",
        "build",
        "output",
        "outputs",
        "artifacts",
        "target",
        "assembled",
        "screenshots",
        ".venv",
        "__pycache__",
        "node_modules",
    }
    exclude_file_prefixes = ("~$", ".~")

    excluded_directories: set[str] = set()
    explicit_excludes = [Path(item).expanduser().resolve(strict=False) for item in profile.exclude]
    scanned_roots: list[tuple[str, str]] = []
    file_count = 0
    pptx_files: list[Path] = []

    def is_explicitly_excluded(path: Path) -> bool:
        resolved = path.expanduser().resolve(strict=False)
        for exclude in explicit_excludes:
            if resolved == exclude or exclude in resolved.parents:
                excluded_directories.add(str(exclude))
                return True
        return False

    def should_skip_dir(path: Path) -> bool:
        if is_explicitly_excluded(path):
            return True
        name = path.name.lower()
        if name in exclude_dir_names:
            excluded_directories.add(str(path.resolve(strict=False)))
            return True
        if name.startswith(".") and "tmp" in name:
            excluded_directories.add(str(path.resolve(strict=False)))
            return True
        return False

    def scan_dir(root: Path) -> None:
        nonlocal file_count
        for candidate in root.iterdir():
            if candidate.is_dir():
                if should_skip_dir(candidate):
                    continue
                scan_dir(candidate)
                continue
            if candidate.name.startswith(exclude_file_prefixes):
                continue
            if not candidate.is_file():
                continue
            file_count += 1
            if candidate.suffix.lower() == ".pptx":
                pptx_files.append(candidate.resolve(strict=False))

    for role in selected_roles:
        for source in getattr(profile, role):
            source_path = Path(source)
            scanned_roots.append((role, str(source_path)))

            if should_skip_dir(source_path):
                continue
            if not source_path.exists():
                excluded_directories.add(str(source_path.resolve(strict=False)))
                continue

            if source_path.is_file():
                if source_path.name.startswith(exclude_file_prefixes):
                    continue
                if is_explicitly_excluded(source_path):
                    continue
                file_count += 1
                if source_path.suffix.lower() == ".pptx":
                    pptx_files.append(source_path.resolve(strict=False))
                continue

            if not source_path.is_dir():
                continue
            scan_dir(source_path)

    return SourceScanResult(
        roles=selected_roles,
        scanned_roots=scanned_roots,
        file_count=file_count,
        pptx_files=sorted(set(pptx_files)),
        excluded_directories=excluded_directories,
    )
