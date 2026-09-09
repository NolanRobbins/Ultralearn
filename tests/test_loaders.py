from io import BytesIO
from xml.sax.saxutils import escape
import zipfile

import pytest
from pypdf import PdfWriter

from ultralearn.loaders import (
    PDFTextExtractionError,
    UnsupportedSourceError,
    extract_docx_text,
    extract_file,
    extract_pdf_text,
)


def test_blank_pdf_reports_no_selectable_text():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(PDFTextExtractionError, match="No selectable text"):
        extract_pdf_text(buffer.getvalue())


def _docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p>" for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_docx_extracts_paragraphs_in_order():
    document = extract_file("notes.docx", _docx_bytes("Chain rule.", "Gradients shrink."))
    assert "Chain rule." in document.text
    assert "Gradients shrink." in document.text
    assert document.title == "notes"


def test_empty_docx_is_rejected():
    with pytest.raises(UnsupportedSourceError, match="No readable text"):
        extract_docx_text(_docx_bytes("   "))


def test_garbage_is_not_treated_as_docx():
    with pytest.raises(UnsupportedSourceError, match="does not look like a Word"):
        extract_docx_text(b"not a zip")
