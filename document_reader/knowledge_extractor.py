"""Layer 2 helper - find what a document talks about, so nothing is missed during extraction.

This module does NOT write definitions. Understanding the text and writing knowledge files is done by Claude
(see CLAUDE.md, "Document reading and knowledge extraction") and approved by you on the Knowledge page.
Here we only list, deterministically:
  - every section/chapter of the document and its pages,
  - which knowledge files already cite that section (covered) and which sections nobody has extracted yet,
  - every known candlestick/chart pattern name mentioned, with the pages it appears on.
"""
from __future__ import annotations

import re

from .text_extractor import normalize

# names the scanner can detect today come from stockpatterns.patterns.PATTERN_NAMES; these are other common
# names worth noticing in a book (mention only: they have no code until approved and implemented)
OTHER_PATTERNS = (
    "Abandoned Baby", "Belt Hold", "Harami Cross", "Three Inside Up", "Three Inside Down", "Three Outside Up",
    "Three Outside Down", "Kicker", "Kicking", "Spinning Top", "Long-Legged Doji", "On Neck", "In Neck",
    "Thrusting", "Rising Three Methods", "Falling Three Methods", "Upside Gap Two Crows", "Tasuki Gap",
    "Head and Shoulders", "Inverse Head and Shoulders", "Triple Top", "Triple Bottom", "Cup and Handle",
    "Ascending Triangle", "Descending Triangle", "Symmetrical Triangle", "Bull Flag", "Bear Flag", "Pennant",
    "Rising Wedge", "Falling Wedge", "Inside Bar", "Outside Bar", "Pin Bar", "Support", "Resistance", "Breakout",
    "Volume", "Stop-loss", "Target", "Trailing Stop", "Moving Average", "RSI", "MACD", "VWAP", "Bollinger Bands",
)


def _vocabulary() -> list[str]:
    try:
        from stockpatterns.patterns import PATTERN_NAMES
    except ImportError:                                            # pragma: no cover
        PATTERN_NAMES = ()
    seen, out = set(), []
    for n in (*PATTERN_NAMES, *OTHER_PATTERNS):
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def mentions(extraction: dict) -> list[dict]:
    """[{name, pages, coded}] for every vocabulary term found in the document."""
    try:
        from stockpatterns.patterns import PATTERN_NAMES
    except ImportError:                                            # pragma: no cover
        PATTERN_NAMES = ()
    pages = [(p["page"], normalize(p["text"]).lower()) for p in extraction["pages"]]
    out = []
    for name in _vocabulary():
        rx = re.compile(r"\b" + re.escape(name.lower()).replace(r"\-", "[- ]?") + r"s?\b")
        hit = [pno for pno, t in pages if rx.search(t)]
        if hit:
            out.append({"name": name, "pages": hit, "coded": name in PATTERN_NAMES})
    return out


def coverage(extraction: dict, items: list[dict], skipped: dict | None = None) -> list[dict]:
    """Each section of the document with the knowledge files that cite it (by document + section number/title).
    Sections with no knowledge file are what is left to extract, unless listed in `skipped` ({number: reason},
    from documents/extracted_knowledge/document_notes.yaml) because they hold no trading knowledge."""
    doc = extraction["document"]
    skipped = {str(k): v for k, v in (skipped or {}).items()}
    out = []
    for s in extraction["sections"]:
        cites = []
        for it in items:
            for src in it.get("sources") or []:
                if src.get("document") != doc:
                    continue
                sec = normalize(str(src.get("section") or "")).lower()
                same_sec = sec and (sec == normalize(s["heading"]).lower() or sec.startswith(f"{s['number']}.")
                                    or normalize(s["title"]).lower() in sec)
                if same_sec:
                    cites.append({"kind": it["kind"], "id": it["id"], "name": it["name"], "status": it["status"]})
                    break
        skip = skipped.get(str(s["number"]))
        out.append({**{k: s[k] for k in ("number", "title", "heading", "page_start", "page_end")},
                    "knowledge": cites, "covered": bool(cites) or bool(skip), "skipped": skip})
    return out


def report(extraction: dict, items: list[dict], skipped: dict | None = None) -> dict:
    cov = coverage(extraction, items, skipped)
    todo = [c for c in cov if not c["covered"]]
    request = None
    if todo:
        request = (f"Read documents/uploaded_books/{extraction['document']} and extract "
                   + "; ".join(f"section {c['heading']} (p. {c['page_start']}"
                               + (f"-{c['page_end']}" if c["page_end"] != c["page_start"] else "") + ")" for c in todo)
                   + " into knowledge files, following CLAUDE.md.")
    return {"document": extraction["document"], "title": extraction["title"], "page_count": extraction["page_count"],
            "extracted_on": extraction.get("extracted_on"), "sections": cov, "mentions": mentions(extraction),
            "not_extracted": len(todo), "ask_claude": request}
