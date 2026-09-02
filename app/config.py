"""Application settings, read from the environment (TrueNAS app config or .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- storage -------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://receipts:receipts@db:5432/receipts",
        description="SQLAlchemy async DSN.",
    )
    data_dir: Path = Field(
        default=Path("/data"),
        description="Root for receipt images; bind-mounted from a ZFS dataset on the NAS.",
    )

    # --- extraction ----------------------------------------------------------
    extractor: str = Field(
        default="claude",
        description="Which extraction engine to use: claude | tesseract | ollama.",
    )
    extractor_model: str = Field(
        default="claude-opus-5",
        description=(
            "Model id for the claude extractor. claude-haiku-4-5 costs roughly a fifth as much "
            "per receipt; compare accuracy on the Costs page before switching."
        ),
    )
    anthropic_api_key: str | None = None
    extractor_effort: str = Field(default="medium", description="low | medium | high | xhigh | max")

    # --- openrouter -----------------------------------------------------------
    # A gateway in front of many providers. Useful if you already hold credit there,
    # or want to try a non-Anthropic vision model without changing any code.
    openrouter_api_key: str | None = None
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-4.5",
        description=(
            "OpenRouter model id, in vendor/model form. It must support both vision and "
            "structured outputs. Check openrouter.ai/models for current ids."
        ),
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = Field(
        default=None, description="Optional, for attribution on the OpenRouter dashboard."
    )

    # Image preprocessing. Claude bills images at (width * height) / 750 tokens, so the
    # longest-edge cap is the main cost lever in the whole app.
    max_image_edge: int = 1600
    jpeg_quality: int = 85

    # --- worker --------------------------------------------------------------
    worker_enabled: bool = True
    worker_poll_seconds: float = 3.0
    worker_max_attempts: int = 3
    worker_stale_seconds: int = Field(
        default=1800,
        description=(
            "A receipt left in 'processing' for longer than this is assumed to belong to a "
            "worker that died, and is picked up again. Must comfortably exceed the longest "
            "an extraction can take, so a live job is never stolen and paid for twice."
        ),
    )

    # --- auth ----------------------------------------------------------------
    secret_key: str = Field(
        default="change-me-in-production",
        description="Signs the session cookie.",
    )
    app_password_hash: str | None = Field(
        default=None,
        description="Argon2 hash of the single user's password; see scripts/hash_password.py.",
    )
    api_key: str | None = Field(
        default=None,
        description="Static key for the iOS Shortcut upload path (X-API-Key header).",
    )
    session_max_age_days: int = 30
    auth_disabled: bool = Field(
        default=False,
        description="Local development escape hatch. Never enable on a reachable host.",
    )

    # --- locale (Hungary only, by design) ------------------------------------
    currency: str = "HUF"
    timezone: str = "Europe/Budapest"

    @property
    def image_dir(self) -> Path:
        return self.data_dir / "receipts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
