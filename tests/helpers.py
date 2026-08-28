"""Shared test helpers."""

from aptiordesk.ai.base import AIProvider, Capabilities, CompletionResult
from aptiordesk.database.models.provider import ProviderConfig, ProviderKind


def make_minimal_pdf(lines: list[str]) -> bytes:
    """Build a tiny valid single-page PDF with extractable text.

    Used instead of QPdfWriter because the offscreen Qt platform (used in
    CI) emits PDFs without a text layer. ASCII text only, no parentheses.
    """
    text_ops = []
    y = 720
    for line in lines:
        text_ops.append(f"BT /F1 12 Tf 72 {y} Td ({line}) Tj ET")
        y -= 18
    content = "\n".join(text_ops).encode("ascii")
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(bodies) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(bodies) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return out


class ScriptedProvider(AIProvider):
    """Deterministic AIProvider returning canned responses in order."""

    def __init__(self, responses: list[str]):
        super().__init__(ProviderConfig(kind=ProviderKind.OLLAMA, model="fake"))
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []
        self.overrides: list[dict] = []

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=False,
            json_mode=False,
            model_listing=False,
            is_local=self.config.is_local,
        )

    def chat(self, messages, **overrides) -> CompletionResult:
        self.calls += 1
        self.prompts.append("\n".join(m.content for m in messages))
        self.overrides.append(dict(overrides))
        return CompletionResult(text=self._responses.pop(0), model="fake")

    def chat_stream(self, messages, **overrides):
        raise NotImplementedError

    def list_models(self):
        return []


class SectionedProvider(AIProvider):
    """Thread-safe scripted provider for the parallel section extractor.

    Sections now run concurrently, so ordered-pop scripting (ScriptedProvider)
    would hand responses to whichever section's thread asked first. This
    provider routes by the section label embedded in the prompt instead; each
    section gets its own response queue, so repair round-trips still work.
    """

    def __init__(self, by_section: dict[str, list[str] | str]):
        super().__init__(ProviderConfig(kind=ProviderKind.OLLAMA, model="fake"))
        import threading

        self._lock = threading.Lock()
        self._queues = {
            key: list(value) if isinstance(value, list) else [value]
            for key, value in by_section.items()
        }
        self.calls = 0
        self.prompts: list[str] = []

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=False,
            json_mode=False,
            model_listing=False,
            is_local=self.config.is_local,
        )

    def chat(self, messages, **overrides) -> CompletionResult:
        text = "\n".join(m.content for m in messages)
        with self._lock:
            self.calls += 1
            self.prompts.append(text)
            queue = self._queues[self._section_key(text)]
            if not queue:
                raise AssertionError("SectionedProvider queue exhausted")
            response = queue.pop(0)
        return CompletionResult(text=response, model="fake")

    def chat_stream(self, messages, **overrides):
        raise NotImplementedError

    def list_models(self):
        return []

    @staticmethod
    def _section_key(prompt: str) -> str:
        from aptiordesk.features.resumes.extraction import SECTIONS

        flat = " ".join(prompt.lower().split())
        for spec in SECTIONS:
            if f"extract only the {spec.label}" in flat:
                return spec.key
        raise AssertionError("Prompt does not name a known section")
