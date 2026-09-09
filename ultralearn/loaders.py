"""Local document loaders for source ingestion.

Everything here runs on the machine. Only a URL fetch reaches the network, and
only for the address the learner explicitly dropped in.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class PDFExtractionResult:
    text: str
    page_count: int
    title: str


@dataclass(frozen=True)
class ExtractedDocument:
    """Normalised result of loading any supported source."""

    text: str
    title: str = ""
    author: str = ""
    source_type: str = "note"
    identifier: str = ""


class PDFTextExtractionError(RuntimeError):
    """Raised when a PDF cannot be converted into usable text."""


class UnsupportedSourceError(RuntimeError):
    """Raised when a dropped file or URL cannot be read."""


#: File extensions that can be ingested directly.
SUPPORTED_SUFFIXES = {
    ".pdf",
    ".epub",
    ".docx",
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".html",
    ".htm",
}

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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


def extract_epub_text(data: bytes) -> ExtractedDocument:
    """Extract readable text from an EPUB, chapter by chapter."""

    try:
        import ebooklib
        from ebooklib import epub
    except Exception as exc:
        raise UnsupportedSourceError(
            "Install the epub extra to ingest EPUBs: uv sync --extra epub"
        ) from exc

    import tempfile

    # ebooklib reads from a path, not bytes.
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=True) as handle:
        handle.write(data)
        handle.flush()
        try:
            book = epub.read_epub(handle.name)
        except Exception as exc:
            raise UnsupportedSourceError(f"Could not read this EPUB: {exc}") from exc

        parts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            chapter = html_to_text(item.get_content().decode("utf-8", errors="replace"))
            if chapter.strip():
                parts.append(chapter.strip())

        title = ""
        author = ""
        try:
            title = (book.get_metadata("DC", "title") or [("", None)])[0][0]
            author = (book.get_metadata("DC", "creator") or [("", None)])[0][0]
        except Exception:
            pass

    text = "\n\n".join(parts).strip()
    if not text:
        raise UnsupportedSourceError("No readable text was found in this EPUB.")
    return ExtractedDocument(text=text, title=title, author=author, source_type="book")


def extract_docx_text(data: bytes) -> ExtractedDocument:
    """Extract readable paragraphs from a .docx (Office Open XML) file.

    Word files are a zip of XML. We only need ``word/document.xml`` — no extra
    dependency, and it works for the notes and chapter exports learners actually
    drop in.
    """

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            try:
                xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise UnsupportedSourceError("This Word file has no document body.") from exc
    except zipfile.BadZipFile as exc:
        raise UnsupportedSourceError("This does not look like a Word (.docx) file.") from exc

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise UnsupportedSourceError("This Word file could not be parsed.") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_W_NS}p"):
        pieces = [node.text or "" for node in paragraph.iter(f"{_W_NS}t")]
        line = "".join(pieces).strip()
        if line:
            paragraphs.append(line)
    text = "\n\n".join(paragraphs).strip()
    if not text:
        raise UnsupportedSourceError("No readable text was found in this Word file.")
    return ExtractedDocument(text=text, source_type="note")


def html_to_text(markup: str) -> str:
    """Reduce HTML to readable prose, dropping chrome, scripts, and styling."""

    try:
        from bs4 import BeautifulSoup
    except Exception:
        # Crude, but better than failing an ingest over a missing optional dep.
        stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.DOTALL | re.I)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", stripped)).strip()

    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    # Prefer the main content region when the page marks one.
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = root.get_text("\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def iter_supported_files(folder: str | Path, limit: int = 200) -> list[Path]:
    """Files in a dropped folder that Ultralearn can actually read.

    Nested directories are included; hidden files and unsupported types are not,
    so a notes folder full of images does not become a pile of failed jobs.
    """

    root = Path(folder)
    if not root.is_dir():
        raise UnsupportedSourceError(f"{folder} is not a folder.")
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            found.append(path)
            if len(found) >= limit:
                break
    return found


def extract_file(filename: str, data: bytes) -> ExtractedDocument:
    """Load any supported dropped file into normalised text."""

    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()

    if suffix == ".pdf":
        result = extract_pdf_text(data)
        return ExtractedDocument(
            text=result.text, title=result.title or stem, source_type="paper"
        )
    if suffix == ".epub":
        document = extract_epub_text(data)
        return ExtractedDocument(
            text=document.text,
            title=document.title or stem,
            author=document.author,
            source_type="book",
        )
    if suffix == ".docx":
        document = extract_docx_text(data)
        return ExtractedDocument(
            text=document.text, title=document.title or stem, source_type="book"
        )
    if suffix in {".html", ".htm"}:
        markup = data.decode("utf-8", errors="replace")
        return ExtractedDocument(
            text=html_to_text(markup), title=_html_title(markup) or stem, source_type="note"
        )
    if suffix in {".md", ".markdown", ".txt", ".rst"} or not suffix:
        text = data.decode("utf-8", errors="replace")
        return ExtractedDocument(text=text, title=_markdown_title(text) or stem, source_type="note")

    raise UnsupportedSourceError(
        f"Ultralearn cannot read '{suffix or filename}' yet. "
        f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
    )


def fetch_url(url: str, timeout: float = 30.0) -> ExtractedDocument:
    """Fetch a web page or arXiv paper and reduce it to text."""

    try:
        import httpx
    except Exception as exc:
        raise UnsupportedSourceError("Install httpx to ingest URLs.") from exc

    url = _normalize_arxiv(url)
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Ultralearn/0.2 (personal study tool)"},
        )
        response.raise_for_status()
    except Exception as exc:
        raise UnsupportedSourceError(f"Could not fetch {url}: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        result = extract_pdf_text(response.content)
        return ExtractedDocument(
            text=result.text,
            title=result.title or _url_title(url),
            source_type="paper",
            identifier=url,
        )

    markup = response.text
    return ExtractedDocument(
        text=html_to_text(markup),
        title=_html_title(markup) or _url_title(url),
        source_type="paper" if "arxiv.org" in url else "note",
        identifier=url,
    )


def _normalize_arxiv(url: str) -> str:
    """Point arXiv abstract links at the PDF, which carries the actual content."""

    match = re.match(r"https?://arxiv\.org/abs/([\w.\-/]+)", url.strip())
    if match:
        return f"https://arxiv.org/pdf/{match.group(1)}"
    return url.strip()


def _html_title(markup: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", markup, re.DOTALL | re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            break
    return ""


def _url_title(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail.replace("-", " ").replace("_", " ") or url
