"""Local, offline extraction engines.

Deliberately shipped as working stubs. The seam they occupy is real - `factory.py` will
instantiate them and the rest of the app cannot tell the difference - so moving off the
Claude API later is implementing one method here, not reworking the pipeline.

Two routes, if you take them:

**Tesseract** (`pip install pytesseract`, `apt install tesseract-ocr-hun`)
    Cheap and fully offline, but it gives you *text*, not structure. You would run
    `pytesseract.image_to_data(img, lang="hun")` to get words with coordinates, group them
    into rows by y-position, then write per-chain rules to find the amount column and the
    ÁFA letter. Expect to write a rule set per chain, and expect thermal-paper receipts to
    defeat it regularly. Feed the result through `hu_rules.validate` exactly as the Claude
    path does - low-confidence rows will then route themselves to the review screen.

**Ollama + a vision model** (e.g. `qwen2.5-vl`, `llama3.2-vision`)
    Structurally identical to `ClaudeExtractor`: same system prompt, same JSON schema via
    the model's structured-output support, `ExtractedReceipt.model_validate_json` on the
    reply. Needs a GPU in the NAS to be tolerable - on CPU expect minutes per receipt.
    Point `OLLAMA_URL` at the host and reuse `app.extraction.prompt.SYSTEM_PROMPT`.
"""

from __future__ import annotations

from app.config import Settings
from app.extraction.base import ExtractionError, ExtractionResult


class TesseractExtractor:
    name = "tesseract"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractionResult:
        raise ExtractionError(
            "The tesseract extractor is not implemented yet. "
            "See app/extraction/local.py for the intended shape, or set EXTRACTOR=claude."
        )


class OllamaExtractor:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractionResult:
        raise ExtractionError(
            "The ollama extractor is not implemented yet. "
            "See app/extraction/local.py for the intended shape, or set EXTRACTOR=claude."
        )
