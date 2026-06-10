from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ppt_lib.settings import ConfigError, Settings, build_settings

ENV_PREFIX = "PPT_LIB_"
SENSITIVE_KEYS = {"openai_api_key", "anthropic_api_key", "vision_api_key", "paddleocr_mcp_access_token"}
WRITABLE_CONFIG_KEYS = set(Settings.model_fields) - SENSITIVE_KEYS - {"home_dir"}


DEFAULT_CONFIG = """# PPT Library local configuration
embedding_provider: openai
embedding_model: text-embedding-3-small
embedding_dimensions: 1536
embedding_timeout_seconds: 30
vision_provider: auto
ollama_base_url: http://127.0.0.1:11434
ollama_vision_model: llava
lmstudio_base_url: http://127.0.0.1:1234/v1
lmstudio_embedding_model: text-embedding-nomic-embed-text-v1.5
lmstudio_vision_model: ""
mmx_command: mmx
mmx_vision_model: default
mmx_quota_check: true
mmx_quota_resume: true
mmx_quota_max_resume_seconds: 21600
paddleocr_mcp_pipeline: PaddleOCR-VL-1.6
paddleocr_mcp_source: aistudio
paddleocr_mcp_base_url: null
paddleocr_mcp_use_layout_detection: true
paddleocr_mcp_use_chart_recognition: true
paddleocr_mcp_use_doc_orientation_classify: false
paddleocr_mcp_use_doc_unwarping: false
cloud_vision_base_url: https://api.openai.com/v1
cloud_vision_model: gpt-4o-mini
vision_timeout_seconds: 30
vision_max_image_bytes: 10000000
vision_max_slides_per_file: null
max_workers: 4
schema_version: "1.0"
search_top_k: 5
search_threshold: 0.5
watch_debounce_seconds: 5
"""

SETUP_MODE_CONFIGS: dict[str, dict[str, object]] = {
    "lmstudio": {
        "embedding_provider": "lmstudio",
        "embedding_api_url": "http://127.0.0.1:1234/v1",
        "embedding_model": "text-embedding-nomic-embed-text-v1.5",
        "embedding_dimensions": 768,
    },
    "openai": {
        "embedding_provider": "openai",
        "embedding_api_url": "https://api.openai.com/v1",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
    },
    "text_extraction": {
        "embedding_provider": "fake",
        "embedding_model": "fake",
        "embedding_dimensions": 1536,
    },
    "mmx": {
        "vision_provider": "mmx",
        "mmx_command": "mmx",
        "mmx_vision_model": "default",
        "mmx_quota_check": True,
        "mmx_quota_resume": True,
    },
    "paddleocr_mcp": {
        "vision_provider": "paddleocr_mcp",
        "paddleocr_mcp_pipeline": "PaddleOCR-VL-1.6",
        "paddleocr_mcp_source": "aistudio",
        "paddleocr_mcp_use_layout_detection": True,
        "paddleocr_mcp_use_chart_recognition": True,
        "paddleocr_mcp_use_doc_orientation_classify": False,
        "paddleocr_mcp_use_doc_unwarping": False,
    },
}


class ConfigCommandError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ConfigSetResult:
    key: str
    old_value: object
    new_value: object
    changed: bool
    config_path: Path


def config_path_for_settings(settings: Settings) -> Path:
    return settings.home_dir / "config.yml"


def resolve_home_dir(home_dir: Path | str | None = None) -> Path:
    default_home = Path.home() / ".ppt-library"
    home_value = home_dir or os.environ.get("PPT_LIB_HOME_DIR") or default_home
    return home_value if isinstance(home_value, Path) else Path(str(home_value))


def config_path_for_home(home_dir: Path) -> Path:
    return home_dir / "config.yml"


def get_effective_config(settings: Settings, key: str | None = None) -> dict[str, object]:
    summary = settings_summary(settings)
    if key is None:
        return {"config": summary}
    _ensure_known_key(key)
    return {"key": key, "value": summary.get(key), "source": "effective"}


def set_config_value(config_path: Path, key: str, raw_value: str, *, home_dir: Path) -> ConfigSetResult:
    _ensure_known_key(key)
    if key in SENSITIVE_KEYS:
        raise ConfigCommandError(
            f"Sensitive config key must be supplied through environment variables: {key}",
            code="CONFIG_SENSITIVE_KEY_REJECTED",
        )
    if key not in WRITABLE_CONFIG_KEYS:
        raise ConfigCommandError(f"Config key is not writable: {key}", code="CONFIG_KEY_NOT_WRITABLE")
    try:
        value = yaml.safe_load(raw_value)
    except yaml.YAMLError as exc:
        raise ConfigCommandError(f"Invalid YAML value for {key}: {exc}", code="CONFIG_VALUE_PARSE_ERROR") from exc

    config_data = _read_config(config_path) if config_path.exists() else _default_config_data()
    old_value = config_data.get(key)
    validation_data = dict(config_data)
    validation_data[key] = value
    if "home_dir" not in validation_data:
        validation_data["home_dir"] = home_dir
    try:
        build_settings(validation_data)
    except ConfigError as exc:
        raise ConfigCommandError(str(exc), code="CONFIG_VALIDATION_ERROR") from exc

    config_data[key] = value
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True))
    return ConfigSetResult(key=key, old_value=old_value, new_value=value, changed=old_value != value, config_path=config_path)


def _ensure_known_key(key: str) -> None:
    if key not in Settings.model_fields:
        raise ConfigCommandError(f"Unknown config key: {key}", code="CONFIG_UNKNOWN_KEY")


def write_default_config(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG)
    return True


def _default_config_data() -> dict[str, Any]:
    raw = yaml.safe_load(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        raise ConfigError("Default config must contain a mapping")
    return raw


def write_setup_config(path: Path, mode: str) -> list[str]:
    normalized_mode = mode.replace("-", "_")
    if normalized_mode not in SETUP_MODE_CONFIGS:
        raise ConfigError(f"Unsupported setup mode: {mode}")

    write_default_config(path)
    config_data = _read_config(path)
    updates = SETUP_MODE_CONFIGS[normalized_mode]
    changed_keys = [key for key, value in updates.items() if config_data.get(key) != value]
    config_data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True))
    return changed_keys


def load_settings(
    overrides: dict[str, object] | None = None,
    *,
    config_path: Path | None = None,
) -> Settings:
    overrides = dict(overrides or {})
    default_home = Path.home() / ".ppt-library"
    home_value = overrides.get("home_dir") or os.environ.get("PPT_LIB_HOME_DIR") or default_home
    home_dir = home_value if isinstance(home_value, Path) else Path(str(home_value))
    config_path = config_path or home_dir / "config.yml"

    if not config_path.exists():
        write_default_config(config_path)

    config_data = _read_config(config_path)
    env_data = _read_env()
    merged: dict[str, Any] = {}
    merged.update(config_data)
    merged.update(env_data)
    merged.update(overrides)

    if "home_dir" not in merged:
        merged["home_dir"] = home_dir

    return build_settings(merged)


def ensure_dirs(settings: Settings) -> None:
    for path in [
        settings.home_dir,
        settings.screenshots_dir,
        settings.symlinks_dir,
        settings.html_dir,
        settings.logs_dir,
        settings.backups_dir,
    ]:
        if path is None:
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create directory {path}: {exc}") from exc


def settings_summary(settings: Settings) -> dict[str, object]:
    summary = settings.model_dump()
    for key in SENSITIVE_KEYS:
        value = summary.get(key)
        summary[key] = "present" if value else "missing"
    return summary


def _read_config(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a mapping")
    return raw


def _read_env() -> dict[str, Any]:
    data: dict[str, Any] = {}
    valid_fields = set(Settings.model_fields)
    for key, value in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        field = key.removeprefix(ENV_PREFIX).lower()
        if field not in valid_fields:
            continue
        data[field] = yaml.safe_load(value)
    return data
