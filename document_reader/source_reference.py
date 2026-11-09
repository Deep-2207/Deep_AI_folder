"""Source references: where a piece of knowledge comes from, and a check that the quoted words really are on
the cited page of the extracted text. This is how "never attribute invented information to a book" is enforced:
a knowledge file whose quote cannot be found on its page is flagged on the Knowledge page and by the tests.

A source in a knowledge file's header looks like:
  sources:
    - document: dummy_trading_knowledge_book.pdf
      section: "2. Bullish Engulfing (illustrative concept)"
      page: 2
      quote: "The first candle has a bearish real body."
"""
from __future__ import annotations

from pathlib import Path

from .text_extractor import load, normalize


def fmt(src: dict) -> str:
    """Human-readable reference, e.g. 'book.pdf, 2. Bullish Engulfing, p. 2'."""
    parts = [src.get("title") or src.get("document") or "?"]
    if src.get("section"):
        parts.append(str(src["section"]))
    if src.get("page"):
        parts.append(f"p. {src['page']}")
    return ", ".join(parts)


def verify(src: dict, text_dir: str | Path, books_dir: str | Path | None = None) -> dict:
    """{'ok': bool, 'reason': str}. ok = the document was read and the quote is on the cited page.
    Quotes may span into the next page (a sentence broken by a page end)."""
    doc, page, quote = src.get("document"), src.get("page"), src.get("quote")
    if not doc:
        return {"ok": False, "reason": "no document named"}
    if books_dir is not None and not (Path(books_dir) / doc).is_file():
        return {"ok": False, "reason": f"{doc} is not in documents/uploaded_books"}
    ext = load(doc, text_dir)
    if ext is None:
        return {"ok": False, "reason": f"{doc} has not been read yet (Read it on the Knowledge page)"}
    if not quote:
        return {"ok": False, "reason": "no quote given"}
    try:
        page = int(page)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "no page number"}
    pages = {p["page"]: p["text"] for p in ext["pages"]}
    if page not in pages:
        return {"ok": False, "reason": f"page {page} does not exist ({ext['page_count']} pages)"}
    q = normalize(quote).lower()
    here = normalize(pages[page]).lower()
    both = normalize(pages[page] + "\n" + pages.get(page + 1, "")).lower()
    if q in here or q in both:
        return {"ok": True, "reason": f"quote found on page {page}"}
    other = [p for p, t in pages.items() if q in normalize(t).lower()]
    if other:
        return {"ok": False, "reason": f"quote is on page {other[0]}, not page {page}"}
    return {"ok": False, "reason": "quote not found in the document"}
