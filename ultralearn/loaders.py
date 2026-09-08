"""Local document loaders for source ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO


@dataclass(frozen=True)
class PDFExtractionResult:
    text: str
    page_count: int
    title: str


class PDFTextExtractionError(RuntimeError):
    """Raised when a PDF cannot be converted into usable text."""


def extract_pdf_text(data: bytes) -> PDFExtractionResult:
    """Extract text from a PDF entirely locally.

    This uses `pypdf`, which works well for digitally generated PDFs. Scanned
    image-only PDFs need OCR, which is intentionally a later loader step.
    """

    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise PDFTextExtractionError("Install pypdf to ingest PDFs: pip install pypdf") from exc

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise PDFTextExtractionError("This PDF is encrypted and could not be opened.") from exc

        parts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            page_text = page_text.strip()
            if page_text:
                parts.append(f"[Page {index}]\n{page_text}")
    except PDFTextExtractionError:
        raise
    except Exception as exc:
        raise PDFTextExtractionError(f"Could not read this PDF: {exc}") from exc

    text = "\n\n".join(parts).strip()
    if not text:
        raise PDFTextExtractionError(
            "No selectable text was found. This looks like a scanned/image-only PDF; OCR is not wired in yet."
        )

    metadata_title = ""
    try:
        metadata_title = str(reader.metadata.title or "").strip()
    except Exception:
        metadata_title = ""

    return PDFExtractionResult(text=text, page_count=len(reader.pages), title=metadata_title)
