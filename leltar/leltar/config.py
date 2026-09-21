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
        default="postgresql+asyncpg://leltar:leltar@db:5432/leltar",
        description="SQLAlchemy async DSN.",
    )
    data_dir: Path = Field(
        default=Path("/data"),
        description="Root for item photographs; bind-mounted from a ZFS dataset on the NAS.",
    )

    # --- identification ------------------------------------------------------
    identifier: str = Field(
        default="claude",
        description="Which identification engine to use: claude | openrouter | ollama.",
    )
    identifier_model: str = Field(
        default="claude-sonnet-5",
        description=(
            "Model id for the claude identifier. Naming a visible object is an easier task "
            "than transcribing a receipt, so the default is a mid-tier model rather than the "
            "largest one; claude-haiku-4-5 costs about a fifth as much again."
        ),
    )
    anthropic_api_key: str | None = None
    identifier_effort: str = Field(
        default="low",
        description=(
            "low | medium | high | xhigh | max. Recognising a kettle does not repay "
            "deliberation - effort here buys longer sentences, not better names."
        ),
    )

    # --- openrouter ----------------------------------------------------------
    # A gateway in front of many providers: Mistral, Qwen, Gemini and the rest, billed
    # from one account. Naming a visible object is a far easier task than transcribing a
    # receipt, so this is where a cheap model can genuinely do the job - see the README,
    # and check any candidate on a real photograph before trusting it with a house.
    openrouter_api_key: str | None = None
    openrouter_model: str = Field(
        default="",
        description=(
            "OpenRouter model id, in vendor/model form. It must support both vision and "
            "strict structured outputs. Deliberately empty: model ids and prices change "
            "faster than this file does, so `python scripts/list_models.py` asks "
            "OpenRouter which models qualify today rather than trusting a default here."
        ),
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = Field(
        default=None, description="Optional, for attribution on the OpenRouter dashboard."
    )

    # Images bill at roughly (width * height) / 750 tokens, so this is the main cost lever.
    # 1280 rather than the receipt scanner's 1600: an object is recognised by its shape and
    # colour, and only printed text needs the resolution that a till receipt does.
    max_image_edge: int = 1280
    jpeg_quality: int = 85

    max_items_per_photo: int = Field(
        default=12,
        description=(
            "A photograph of a full shelf can yield a long list of half-seen things. Past "
            "this many, the extra rows are guesses about the background rather than the "
            "subject, and reviewing them costs more time than typing the names would."
        ),
    )

    # --- worker --------------------------------------------------------------
    worker_enabled: bool = True
    worker_concurrency: int = Field(
        default=2,
        ge=1,
        le=8,
        description=(
            "How many photographs may be read at once. Two people working together - one "
            "photographing, one approving names - produce frames faster than a single "
            "sequential reader gets through them, and the person reviewing then waits on "
            "the queue rather than on their own judgement. Raising it multiplies the "
            "requests in flight, not the cost per photograph."
        ),
    )
    worker_poll_seconds: float = 3.0
    worker_max_attempts: int = 3
    worker_stale_seconds: int = Field(
        default=1800,
        description=(
            "A photo left in 'processing' for longer than this is assumed to belong to a "
            "worker that died, and is picked up again. Must comfortably exceed the longest "
            "an identification can take, so a live job is never stolen and paid for twice."
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
        return self.data_dir / "items"

    @property
    def crop_dir(self) -> Path:
        """Where the per-item pictures live, kept apart from the originals.

        A crop is derived data: it can be regenerated from its photograph and its box, and
        a backup that skips it loses nothing that cannot be rebuilt.
        """
        return self.data_dir / "crops"

    @property
    def active_model(self) -> str:
        """The model the configured engine will actually call.

        Two settings hold a model name and only one is in use, so anything that reports or
        records "which model" has to pick. Written twice it drifts - in the sister app the
        worker's failure path recorded the wrong model against every failed receipt for
        exactly this reason.
        """
        return self.openrouter_model if self.identifier == "openrouter" else self.identifier_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
