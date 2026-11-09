"""python -m document_reader read <file> | read --all | check   (see __init__.py)"""
import argparse
import json
import sys

from stockpatterns.knowledge import KB


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m document_reader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="extract the text of an uploaded document and report what it covers")
    r.add_argument("name", nargs="?", help="file name in documents/uploaded_books")
    r.add_argument("--all", action="store_true")
    sub.add_parser("check", help="verify every source quote in the knowledge base")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        probs = KB.check()
        print("\n".join(probs) if probs else "OK: every source quote was found on its page")
        return 1 if probs else 0
    names = [d["name"] for d in KB.documents()] if a.all else [a.name]
    if not names or names == [None]:
        ap.error("give a file name or --all")
    for n in names:
        rep = KB.read_document(n)
        print(f"\n== {rep['title']} ({rep['document']}, {rep['page_count']} pages)")
        print(f"   text: documents/extracted_text/{n}.md")
        for s in rep["sections"]:
            who = ", ".join(f"{k['name']} [{k['status']}]" for k in s["knowledge"]) or (
                f"skipped: {s['skipped']}" if s["skipped"] else "NOT EXTRACTED YET")
            print(f"   {s['heading']}  (p. {s['page_start']}-{s['page_end']}): {who}")
        print("   mentions: " + ", ".join(f"{m['name']} p.{','.join(map(str, m['pages']))}" for m in rep["mentions"]))
        if rep["ask_claude"]:
            print("   ask Claude: " + rep["ask_claude"])
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
