"""Text extraction from uploaded files."""
import io
from dataclasses import dataclass

SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "txt",
    "text/x-markdown": "txt",
}
SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".txt": "txt", ".md": "txt"}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class UnsupportedDocument(Exception):
    pass


class ExtractionError(Exception):
    pass


@dataclass
class Page:
    number: int | None
    text: str


def detect_kind(filename: str, content_type: str) -> str:
    by_type = SUPPORTED_CONTENT_TYPES.get((content_type or "").split(";")[0].strip())
    if by_type:
        return by_type
    lowered = filename.lower()
    for ext, kind in SUPPORTED_EXTENSIONS.items():
        if lowered.endswith(ext):
            return kind
    raise UnsupportedDocument(
        f"Unsupported file type: {filename} ({content_type}). "
        "Upload a PDF, .txt or .md file."
    )


def extract_pages(data: bytes, *, filename: str, content_type: str) -> list[Page]:
    """Return text per page. TXT yields a single page with number None."""
    kind = detect_kind(filename, content_type)

    if kind == "txt":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return [Page(number=None, text=text)]

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("The PDF is encrypted and cannot be read.")
        pages = [
            Page(number=i + 1, text=(page.extract_text() or ""))
            for i, page in enumerate(reader.pages)
        ]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not read the PDF: {exc}") from exc

    if not any(p.text.strip() for p in pages):
        # A scanned PDF has pages but no text layer. Say so, rather than
        # indexing an empty document that silently answers nothing.
        raise ExtractionError(
            "No text could be extracted. If this is a scanned document it "
            "needs OCR before it can be indexed."
        )
    return pages
