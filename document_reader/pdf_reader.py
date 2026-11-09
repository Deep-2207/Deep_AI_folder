"""Layer 1 - Document reading: turn an uploaded book (PDF, .txt or .md) into a list of page texts.

Page numbers are the PDF's physical pages, starting at 1, so a source reference "page 3" means the 3rd page
of the file. Text files have one page per form-feed (\\f) separated block, or a single page.
"""
from __future__ import annotations

from pathlib import Path

SUPPORTED = (".pdf", ".txt", ".md")


class DocumentError(Exception):
    pass


def read_pages(path: str | Path) -> list[str]:
    """Raw text of every page, in order. Raises DocumentError for unreadable or unsupported files."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise DocumentError(f"{path.name}: unsupported file type (use {', '.join(SUPPORTED)})")
    if not path.is_file():
        raise DocumentError(f"{path.name}: file not found")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:                                   # pragma: no cover
            raise DocumentError("pypdf is not installed: pip install -r requirements.txt") from e
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                reader.decrypt("")
            pages = [(p.extract_text() or "") for p in reader.pages]
        except Exception as e:                                     # pypdf raises many exception types
            raise DocumentError(f"{path.name}: could not read PDF ({e})") from e
        if pages and not any(p.strip() for p in pages):
            raise DocumentError(f"{path.name}: no text layer (scanned PDF?). Run OCR on it first.")
        return pages
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.split("\f") if "\f" in text else [text]


def pdf_title(path: str | Path) -> str | None:
    """Title from the PDF metadata, if it has a real one."""
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return None
    try:
        from pypdf import PdfReader
        t = (PdfReader(str(path)).metadata or {}).get("/Title")
    except Exception:
        return None
    t = str(t).strip("() ") if t else ""
    return t if t and t.lower() not in ("anonymous", "untitled", "unspecified") else None
