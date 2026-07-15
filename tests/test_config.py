from pathlib import Path

import pytest

from ppt_lib.config import (
    PLAINTEXT_SECRET_WARNING_CODE,
    SENSITIVE_KEYS,
    ConfigCommandError,
    ConfigError,
    ConfigSecurityWarning,
    ensure_dirs,
    load_settings,
    set_config_value,
    settings_summary,
    write_default_config,
)
from ppt_lib.settings import Settings


def test_default_settings_paths_use_home_dir_override(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path})

    assert settings.home_dir == tmp_path
    assert settings.db_path == tmp_path / "index.db"
    assert settings.screenshots_dir == tmp_path / "screenshots"
    assert settings.symlinks_dir == tmp_path / "symlinks"
    assert settings.html_dir == tmp_path / "html"
    assert settings.logs_dir == tmp_path / "logs"
    assert settings.backups_dir == tmp_path / "backups"


def test_write_default_config_once(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"

    first = write_default_config(config_path)
    original = config_path.read_text()
    second = write_default_config(config_path)

    assert first is True
    assert second is False
    assert config_path.read_text() == original


def test_missing_config_is_created_and_loaded(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"

    settings = load_settings({"home_dir": tmp_path}, config_path=config_path)

    assert config_path.exists()
    assert settings.home_dir == tmp_path


def test_env_override_wins_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("search_top_k: 3\nembedding_provider: openai\n")
    monkeypatch.setenv("PPT_LIB_SEARCH_TOP_K", "8")

    settings = load_settings({"home_dir": tmp_path}, config_path=config_path)

    assert settings.search_top_k == 8


def test_local_model_settings_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PPT_LIB_EMBEDDING_PROVIDER", "lmstudio")
    monkeypatch.setenv("PPT_LIB_LMSTUDIO_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")
    monkeypatch.setenv("PPT_LIB_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("PPT_LIB_EMBEDDING_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("PPT_LIB_VISION_MAX_SLIDES_PER_FILE", "3")

    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    assert settings.embedding_provider == "lmstudio"
    assert settings.lmstudio_embedding_model == "text-embedding-nomic-embed-text-v1.5"
    assert settings.embedding_dimensions == 768
    assert settings.embedding_timeout_seconds == 9
    assert settings.vision_max_slides_per_file == 3


def test_lmstudio_default_nomic_dimensions_are_derived(tmp_path: Path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "lmstudio"},
        config_path=tmp_path / "config.yml",
    )

    assert settings.embedding_dimensions == 768


def test_default_config_does_not_use_fake_lmstudio_vision_model(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    assert settings.lmstudio_vision_model == ""


def test_cli_override_wins_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PPT_LIB_SEARCH_TOP_K", "8")

    settings = load_settings(
        {"home_dir": tmp_path, "search_top_k": 4},
        config_path=tmp_path / "config.yml",
    )

    assert settings.search_top_k == 4


def test_invalid_yaml_returns_config_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("search_top_k: [unterminated\n")

    with pytest.raises(ConfigError):
        load_settings({"home_dir": tmp_path}, config_path=config_path)


def test_ensure_dirs_creates_all_dirs(tmp_path: Path) -> None:
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    ensure_dirs(settings)

    assert settings.screenshots_dir.is_dir()
    assert settings.symlinks_dir.is_dir()
    assert settings.html_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.backups_dir.is_dir()


def test_settings_summary_redacts_sensitive_values(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "openai_api_key": "sk-test-openai",
            "embedding_api_key": "sk-test-embedding",
            "paddleocr_mcp_access_token": "test-paddle-token",
        },
        config_path=tmp_path / "config.yml",
    )

    summary = settings_summary(settings)

    assert summary["openai_api_key"] == "present"
    assert summary["embedding_api_key"] == "present"
    assert summary["paddleocr_mcp_access_token"] == "present"
    assert "sk-test-openai" not in repr(summary)
    assert "sk-test-embedding" not in repr(summary)
    assert "test-paddle-token" not in repr(summary)


def test_sensitive_registry_covers_all_secret_settings_fields() -> None:
    secret_like_fields = {
        name
        for name in Settings.model_fields
        if name.endswith(("_api_key", "_access_token"))
    }

    assert secret_like_fields <= SENSITIVE_KEYS


def test_embedding_api_key_cannot_be_written_to_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"

    with pytest.raises(ConfigCommandError) as exc_info:
        set_config_value(
            config_path,
            "embedding_api_key",
            "sk-should-never-be-written",
            home_dir=tmp_path,
        )

    assert exc_info.value.code == "CONFIG_SENSITIVE_KEY_REJECTED"
    assert not config_path.exists()


def test_plaintext_secret_config_warns_without_leaking_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "sk-canary-must-never-appear-in-diagnostics"
    config_path = tmp_path / "config.yml"
    config_path.write_text(f"embedding_api_key: {canary}\n", encoding="utf-8")

    with pytest.warns(ConfigSecurityWarning) as captured:
        settings = load_settings({"home_dir": tmp_path}, config_path=config_path)

    streams = capsys.readouterr()
    diagnostic = "\n".join(str(item.message) for item in captured)
    assert settings.embedding_api_key == canary
    assert PLAINTEXT_SECRET_WARNING_CODE in diagnostic
    assert "embedding_api_key" in diagnostic
    assert canary not in diagnostic
    assert canary not in streams.out
    assert canary not in streams.err


def test_invalid_threshold_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(
            {"home_dir": tmp_path, "search_threshold": 1.5},
            config_path=tmp_path / "config.yml",
        )
