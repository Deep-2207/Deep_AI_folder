"""Clean page texts and find the document's structure (chapters / numbered sections and the pages they span).

The result is saved as documents/extracted_text/<doc>.json (machine readable) and <doc>.md (page by page, easy to
read and to quote from). Source references in the knowledge base are checked against this text.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from .pdf_reader import pdf_title, read_pages

# "1. Basic market data concepts", "Chapter 3: Reversal Patterns", "CHAPTER 3 - ..."
HEADING = re.compile(r"^(?:(?:chapter|part)\s+(\d+|[ivxlc]+)\b[\s:.\-–—]*(.*)|(\d{1,2})\.\s+([A-Z][^\n]{2,90}))$", re.I)
_PAGE_NO = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*$", re.I)


def normalize(s: str) -> str:
    """Text for matching: unicode-normalized, curly quotes/dashes/bullets made plain, whitespace collapsed."""
    s = unicodedata.normalize("NFKC", s)
    s = (s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
         .replace("–", "-").replace("—", "-").replace("•", " ").replace("▪", " ")
         .replace("�", " ").replace("­", ""))
    s = re.sub(r"-\n(?=[a-z])", "", s)            # words hyphenated across lines
    return re.sub(r"\s+", " ", s).strip()


def clean_pages(pages: list[str]) -> list[str]:
    """Drop running headers/footers (lines repeated on most pages, page numbers) and tidy whitespace."""
    lines = [[ln.strip() for ln in p.splitlines()] for p in pages]
    if len(pages) >= 3:
        strip_no = lambda ln: re.sub(r"\s*page\s*\d+\s*$|\s*\d+\s*$", "", ln, flags=re.I).strip()
        seen = Counter(k for page in lines for k in {strip_no(ln) for ln in page if ln})
        running = {k for k, n in seen.items() if k and n >= 0.6 * len(pages)}
    else:
        running = set()
    out = []
    for page in lines:
        keep = [ln for ln in page if ln and not _PAGE_NO.match(ln)
                and re.sub(r"\s*page\s*\d+\s*$|\s*\d+\s*$", "", ln, flags=re.I).strip() not in running]
        out.append("\n".join(keep))
    return out


def find_sections(pages: list[str]) -> list[dict]:
    """Numbered sections / chapters with the page each starts and ends on."""
    found = []
    for pno, text in enumerate(pages, start=1):
        for ln in text.splitlines():
            m = HEADING.match(ln.strip())
            if not m:
                continue
            num = m.group(1) or m.group(3)
            title = (m.group(2) or m.group(4) or "").strip()
            if len(title.split()) > 12 or title.endswith((",", ";")):      # a numbered sentence, not a heading
                continue
            found.append({"number": num, "title": title, "heading": ln.strip(), "page_start": pno})
    for a, b in zip(found, found[1:] + [None]):
        a["page_end"] = b["page_start"] if b else len(pages)
    return found


def extract(path: str | Path, out_dir: str | Path) -> dict:
    """Read a document, save its cleaned text, and return {document, title, pages, sections, ...}."""
    path, out_dir = Path(path), Path(out_dir)
    pages = clean_pages(read_pages(path))
    sections = find_sections(pages)
    head = [ln for ln in (pages[0].splitlines() if pages else []) if len(ln.strip()) > 2]
    caps = []                                    # a title in capitals may be split over several lines
    for ln in head:
        if ln.isupper() and len(caps) < 4:
            caps.append(ln.strip())
        elif caps:
            break
    first = " ".join(caps) if caps else (head[0] if head else path.stem)
    res = {
        "document": path.name,
        "title": pdf_title(path) or (first.title() if first.isupper() else first),
        "extracted_on": date.today().isoformat(),
        "page_count": len(pages),
        "sections": sections,
        "pages": [{"page": i, "text": t} for i, t in enumerate(pages, start=1)],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{path.name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# {res['title']}\n", f"Extracted text of `{path.name}` ({len(pages)} pages, {res['extracted_on']}). "
          "Page numbers are the file's pages. Quote from here when citing.\n"]
    md += [f"\n---\n## Page {p['page']}\n\n{p['text']}\n" for p in res["pages"]]
    (out_dir / f"{path.name}.md").write_text("".join(md), encoding="utf-8")
    return res


def load(document: str, out_dir: str | Path) -> dict | None:
    """The saved extraction of a document, or None if it has not been read yet."""
    f = Path(out_dir) / f"{document}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
