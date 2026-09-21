"""Local, offline identification engines.

Deliberately shipped as a working stub. The seam it occupies is real - `factory.py` will
instantiate it and the rest of the app cannot tell the difference - so moving off the
Claude API later is implementing one method here, not reworking the pipeline.

**Ollama + a vision model** (e.g. `qwen2.5-vl`, `llama3.2-vision`)
    Structurally identical to `ClaudeIdentifier`: same system prompt, the same JSON schema
    through the model's structured-output support, then
    `IdentifiedPhoto.model_validate_json` on the reply. Needs a GPU in the NAS to be
    tolerable - on CPU expect minutes per photograph. Point `OLLAMA_URL` at the host and
    reuse `leltar.extraction.prompt.SYSTEM_PROMPT` unchanged.

    Feed whatever comes back through `leltar.extraction.rules` exactly as the Claude path
    does. That matters more with a smaller model, not less: the rules are what stop an
    inferred brand or an invented serial number reaching the inventory, and a local 7B
    model invents both far more readily than Claude does.
"""

from __future__ import annotations

from leltar.config import Settings
from leltar.extraction.base import IdentificationError, IdentificationResult


class OllamaIdentifier:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def identify(
        self,
        image: bytes,
        *,
        place_path: str | None = None,
        single: bool = False,
        mime_type: str = "image/jpeg",
    ) -> IdentificationResult:
        raise IdentificationError(
            "The ollama identifier is not implemented yet. "
            "See leltar/extraction/local.py for the intended shape, or set IDENTIFIER=claude."
        )
