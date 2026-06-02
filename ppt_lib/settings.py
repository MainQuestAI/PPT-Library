from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator


class Settings(BaseModel):
    home_dir: Path = Field(default_factory=lambda: Path.home() / ".ppt-library")
    db_path: Path | None = None
    screenshots_dir: Path | None = None
    symlinks_dir: Path | None = None
    html_dir: Path | None = None
    logs_dir: Path | None = None
    backups_dir: Path | None = None
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    embedding_timeout_seconds: int = Field(default=30, ge=1)
    # Unified OpenAI-compatible endpoint (replaces separate provider configs)
    embedding_api_url: str | None = None
    embedding_api_key: str | None = None
    vision_provider: str = "auto"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_vision_model: str = "llava"
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    lmstudio_vision_model: str = ""
    cloud_vision_base_url: str = "https://api.openai.com/v1"
    cloud_vision_model: str = "gpt-4o-mini"
    vision_timeout_seconds: int = Field(default=30, ge=1)
    vision_max_image_bytes: int = Field(default=10_000_000, ge=1)
    vision_max_slides_per_file: int | None = Field(default=None, ge=0)
    max_workers: int = Field(default=4, ge=1)
    schema_version: str = "1.0"
    search_top_k: int = Field(default=5, ge=1)
    search_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    watch_debounce_seconds: int = Field(default=5, ge=0)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    vision_api_key: str | None = None

    @model_validator(mode="after")
    def derive_paths(self) -> Settings:
        home_dir = self.home_dir.expanduser()
        self.home_dir = home_dir
        self.db_path = self.db_path or home_dir / "index.db"
        self.screenshots_dir = self.screenshots_dir or home_dir / "screenshots"
        self.symlinks_dir = self.symlinks_dir or home_dir / "symlinks"
        self.html_dir = self.html_dir or home_dir / "html"
        self.logs_dir = self.logs_dir or home_dir / "logs"
        self.backups_dir = self.backups_dir or home_dir / "backups"
        if (
            self.embedding_provider == "lmstudio"
            and self.lmstudio_embedding_model == "text-embedding-nomic-embed-text-v1.5"
            and self.embedding_dimensions == 1536
        ):
            self.embedding_dimensions = 768
        return self


class ConfigError(RuntimeError):
    pass


def build_settings(data: dict[str, Any]) -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
