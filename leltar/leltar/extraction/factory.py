"""Chooses the identification engine from configuration."""

from __future__ import annotations

from leltar.config import Settings, get_settings
from leltar.extraction.base import ObjectIdentifier
from leltar.extraction.claude import ClaudeIdentifier
from leltar.extraction.local import OllamaIdentifier
from leltar.extraction.openrouter import OpenRouterIdentifier

_BUILDERS = {
    "claude": ClaudeIdentifier,
    "openrouter": OpenRouterIdentifier,
    "ollama": OllamaIdentifier,
}


def build_identifier(settings: Settings | None = None) -> ObjectIdentifier:
    settings = settings or get_settings()
    try:
        builder = _BUILDERS[settings.identifier.lower()]
    except KeyError:
        raise ValueError(
            f"Unknown IDENTIFIER={settings.identifier!r}. Choose one of: {', '.join(_BUILDERS)}."
        ) from None
    return builder(settings)
