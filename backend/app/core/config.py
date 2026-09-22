from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, List

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

#: Named in the shared-mode validation error, so that a misconfigured start
#: tells an operator exactly which variable is missing.
ADMIN_TOKEN_ENV_VAR = "WORKSHOP_ADMIN_TOKEN"

#: Accepted but ignored: flag reads are no longer cached per process.
OBSOLETE_ENV_VARS = ("WORKSHOP_FEATURE_FLAG_CACHE_SECONDS",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WORKSHOP_")

    app_name: str = "AI Testing Workshop"
    # The version the running shop reports (WORKSHOP_APP_VERSION): the version
    # tag the image was built for ("X.Y.Z" or "workshop-<id>"), or "dev" for
    # source runs and for images built without such a tag. The shop never
    # derives its version from git.
    app_version: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./workshop.db"
    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"
    cors_allow_origins: List[str] = ["*"]
    # Deprecated: still accepted so that an older .env keeps working, but
    # ignored. ``warn_obsolete_settings`` reports it once at start-up.
    feature_flag_cache_seconds: int = 30
    # Shared mode protects the global ``default`` space on a hosted instance:
    # workshop control operations on that space then need the admin token.
    shared_mode: bool = False
    admin_token: SecretStr | None = None
    ai_provider: str = "mock"
    ai_model: str = "mock-simulated"
    ai_api_key: str | None = None
    ai_base_url: str | None = None
    ai_api_version: str | None = None
    visual_baseline_dir: str = "tests/robot/baselines"
    pdf_output_dir: str = "backend/app/static/pdfs"
    base_dir: str = "backend/app"
    feature_flag_overrides: dict[str, bool] = {}

    @model_validator(mode="after")
    def _require_admin_token_in_shared_mode(self) -> Settings:
        """Refuse shared mode without a non-empty admin token.

        ``settings`` is built at import time, so a shop started in shared mode
        without a token fails before the server binds its port, with an error
        that names the missing variable.
        """
        if not self.shared_mode:
            return self

        token = self.admin_token.get_secret_value() if self.admin_token else ""
        if not token.strip():
            raise ValueError(
                f"shared mode requires {ADMIN_TOKEN_ENV_VAR}: set it to a "
                "non-empty secret (for example `openssl rand -hex 32`) or turn "
                "off WORKSHOP_SHARED_MODE"
            )
        return self

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


def warn_obsolete_settings(settings: Settings) -> None:
    """Log one deprecation warning per obsolete variable that is still set.

    Called once from the application lifespan. The settings object records which
    fields a source actually provided, so an untouched default never warns.
    """
    for env_var in OBSOLETE_ENV_VARS:
        field_name = env_var.removeprefix("WORKSHOP_").lower()
        if field_name in settings.model_fields_set:
            logger.warning(
                "%s is deprecated and ignored: feature flags are no longer cached.",
                env_var,
            )


@lru_cache(1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
