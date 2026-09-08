from io import BytesIO

import pytest
from pypdf import PdfWriter

from ultralearn.loaders import PDFTextExtractionError, extract_pdf_text


def test_blank_pdf_reports_no_selectable_text():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(PDFTextExtractionError, match="No selectable text"):
        extract_pdf_text(buffer.getvalue())
