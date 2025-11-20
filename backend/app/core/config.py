from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WORKSHOP_")

    app_name: str = "AI Testing Workshop"
    database_url: str = "sqlite+aiosqlite:///./workshop.db"
    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"
    cors_allow_origins: List[str] = ["*"]
    feature_flag_cache_seconds: int = 30
    ai_provider: str = "mock"
    ai_model: str = "mock-simulated"
    ai_api_key: str | None = None
    ai_base_url: str | None = None
    ai_api_version: str | None = None
    visual_baseline_dir: str = "tests/robot/baselines"
    pdf_output_dir: str = "backend/app/static/pdfs"
    base_dir: str = "backend/app"
    feature_flag_overrides: dict[str, bool] = {}

    def model_post_init(self, __context: Any) -> None:
        overrides: dict[str, bool] = {}
        prefix = "WORKSHOP_FLAG_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                flag_key = key.removeprefix(prefix).upper()
                overrides[flag_key] = value.lower() in {"1", "true", "yes", "on"}

        if overrides:
            self.feature_flag_overrides = overrides

        # Allow fallback to un-prefixed environment variables often used for OpenAI-compatible providers.
        if not self.ai_api_key:
            self.ai_api_key = os.environ.get("OPENAI_API_KEY") or self.ai_api_key
        if not self.ai_base_url:
            self.ai_base_url = os.environ.get("BASE_URL") or self.ai_base_url
        if not self.ai_api_version:
            self.ai_api_version = os.environ.get("OPENAI_API_VERSION") or self.ai_api_version


@lru_cache(1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
