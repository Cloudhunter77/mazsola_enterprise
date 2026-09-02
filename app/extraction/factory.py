"""Chooses the extraction engine from configuration."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.extraction.base import ReceiptExtractor
from app.extraction.claude import ClaudeExtractor
from app.extraction.local import OllamaExtractor, TesseractExtractor
from app.extraction.openrouter import OpenRouterExtractor

_BUILDERS = {
    "claude": ClaudeExtractor,
    "openrouter": OpenRouterExtractor,
    "tesseract": TesseractExtractor,
    "ollama": OllamaExtractor,
}


def build_extractor(settings: Settings | None = None) -> ReceiptExtractor:
    settings = settings or get_settings()
    try:
        builder = _BUILDERS[settings.extractor.lower()]
    except KeyError:
        raise ValueError(
            f"Unknown EXTRACTOR={settings.extractor!r}. Choose one of: {', '.join(_BUILDERS)}."
        ) from None
    return builder(settings)
