"""Splitting documents into retrievable passages.

Paragraph-aware with a character overlap. Overlap matters: a policy
sentence split across a chunk boundary is otherwise retrievable by neither
half.
"""
import re
from dataclasses import dataclass

from app.rag.loader import Page

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 40


@dataclass
class Chunk:
    index: int
    text: str
    page_number: int | None


_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _split_page(text: str, size: int, overlap: int) -> list[str]:
    text = normalise(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, then a space.
            window = text[start:end]
            for sep in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(sep)
                if cut > size // 2:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_pages(
    pages: list[Page], *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    out: list[Chunk] = []
    for page in pages:
        for piece in _split_page(page.text, size, overlap):
            if len(piece) < MIN_CHUNK_CHARS and out:
                continue
            out.append(Chunk(index=len(out), text=piece, page_number=page.number))
    return out
