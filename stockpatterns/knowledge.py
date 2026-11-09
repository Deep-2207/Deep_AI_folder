"""Layer 3 - Trading knowledge base, review workflow and the approval gate used by the live signal.

Every concept, pattern and strategy is one Markdown file with a YAML header (see CLAUDE.md). Its folder follows its
status, so the file system always shows what is approved:

  documents/extracted_knowledge/{patterns,strategies,concepts}/   EXTRACTED, PENDING_REVIEW, REJECTED
  knowledge/approved_{patterns,strategies,concepts}/              APPROVED, IMPLEMENTED, BACKTESTED

Statuses:  EXTRACTED -> PENDING_REVIEW -> APPROVED -> IMPLEMENTED -> BACKTESTED   (or REJECTED)
  APPROVED     you reviewed it and accept it as the rule to use
  IMPLEMENTED  approved AND has Python code + tests that follow the approved definition (`implemented_in`)
  BACKTESTED   implemented and measured on historical candles (results stored in the file)

The gate: the live signal only uses patterns and strategies that are IMPLEMENTED or BACKTESTED. It reads these
files (cached by modification time); it never asks an AI anything while the market runs.
"""
from __future__ import annotations

import re
import threading
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

STATUSES = ("EXTRACTED", "PENDING_REVIEW", "APPROVED", "REJECTED", "IMPLEMENTED", "BACKTESTED")
APPROVED_SET = {"APPROVED", "IMPLEMENTED", "BACKTESTED"}
USABLE = {"IMPLEMENTED", "BACKTESTED"}
KINDS = {"pattern": "patterns", "strategy": "strategies", "concept": "concepts"}
TRANSITIONS = {
    "EXTRACTED": {"PENDING_REVIEW", "REJECTED"},
    "PENDING_REVIEW": {"APPROVED", "REJECTED", "EXTRACTED"},
    "APPROVED": {"IMPLEMENTED", "PENDING_REVIEW", "REJECTED"},
    "IMPLEMENTED": {"BACKTESTED", "PENDING_REVIEW", "REJECTED"},
    "BACKTESTED": {"BACKTESTED", "PENDING_REVIEW", "REJECTED"},
    "REJECTED": {"PENDING_REVIEW"},
}
RULE_STRATEGY = "trend_pattern_rule"
MODEL_STRATEGY = "self_learning_model"
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


class KnowledgeError(ValueError):
    pass


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:64] or "item"


def parse(text: str) -> tuple[dict, str]:
    """(header dict, markdown body) of a knowledge file."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise KnowledgeError("missing YAML header (--- ... ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise KnowledgeError("YAML header must be a mapping")
    return meta, m.group(2)


def dump(meta: dict, body: str) -> str:
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110, default_flow_style=False)
    return f"---\n{head}---\n{body if body.startswith(chr(10)) else chr(10) + body}"


def _coded_patterns() -> set[str]:
    from .patterns import PATTERN_NAMES
    return set(PATTERN_NAMES)


class KnowledgeBase:
    def __init__(self, root: str | Path = ROOT):
        self.root = Path(root)
        self.books = self.root / "documents" / "uploaded_books"
        self.text_dir = self.root / "documents" / "extracted_text"
        self.index_file = self.root / "knowledge" / "knowledge_index.md"
        self._lock = threading.RLock()
        self._cache: tuple[tuple, list[dict]] | None = None

    # ---------- locations ----------
    def folder(self, kind: str, status: str) -> Path:
        sub = KINDS[kind]
        if status in APPROVED_SET:
            return self.root / "knowledge" / f"approved_{sub}"
        return self.root / "documents" / "extracted_knowledge" / sub

    def _folders(self):
        for kind in KINDS:
            yield kind, self.folder(kind, "PENDING_REVIEW")
            yield kind, self.folder(kind, "APPROVED")

    def _stamp(self) -> tuple:
        out = []
        for _, d in self._folders():
            if d.is_dir():
                out.extend((str(f), f.stat().st_mtime_ns) for f in sorted(d.glob("*.md")))
        return tuple(out)

    # ---------- reading ----------
    def items(self) -> list[dict]:
        """Every knowledge file as a dict: header fields + kind, id, status, body, path, folder_ok, problems."""
        with self._lock:
            stamp = self._stamp()
            if self._cache and self._cache[0] == stamp:
                return self._cache[1]
            out = []
            for kind, d in self._folders():
                if not d.is_dir():
                    continue
                for f in sorted(d.glob("*.md")):
                    out.append(self._load(kind, f))
            out.sort(key=lambda x: (list(KINDS).index(x["kind"]), x["name"].lower()))
            self._cache = (stamp, out)
            return out

    def _load(self, kind: str, f: Path) -> dict:
        problems = []
        try:
            meta, body = parse(f.read_text(encoding="utf-8"))
        except (KnowledgeError, yaml.YAMLError, OSError) as e:
            meta, body = {}, ""
            problems.append(f"cannot read file: {e}")
        status = str(meta.get("status", "EXTRACTED")).upper()
        if status not in STATUSES:
            problems.append(f"unknown status {status}")
        if meta.get("kind", kind) != kind:
            problems.append(f"kind '{meta.get('kind')}' but stored in the {KINDS[kind]} folder")
        if status in STATUSES and self.folder(kind, status) != f.parent:
            problems.append(f"status {status} but the file is in {f.parent.relative_to(self.root).as_posix()}")
        it = {**meta, "kind": kind, "id": meta.get("id") or f.stem, "name": meta.get("name") or f.stem,
              "status": status, "body": body, "path": f.relative_to(self.root).as_posix()}
        if it["id"] != f.stem:
            problems.append(f"id '{it['id']}' does not match the file name")
        if kind == "pattern" and status in USABLE and it.get("code_name") not in _coded_patterns():
            problems.append(f"marked {status} but code_name '{it.get('code_name')}' is not detected by patterns.py")
        if status in USABLE and not it.get("implemented_in"):
            problems.append(f"marked {status} without implemented_in")
        it["problems"] = problems
        return it

    def get(self, kind: str, id_: str) -> dict:
        if kind not in KINDS or not _ID.match(id_ or ""):
            raise KnowledgeError("unknown knowledge item")
        for it in self.items():
            if it["kind"] == kind and it["id"] == id_:
                return it
        raise KnowledgeError(f"no {kind} '{id_}'")

    # ---------- the gate ----------
    def usable_patterns(self) -> set[str]:
        """detect() names the live signal may use: patterns IMPLEMENTED/BACKTESTED with no problems."""
        return {it["code_name"] for it in self.items()
                if it["kind"] == "pattern" and it["status"] in USABLE and not it["problems"] and it.get("code_name")}

    def strategy_usable(self, id_: str) -> bool:
        return any(it["kind"] == "strategy" and it["id"] == id_ and it["status"] in USABLE and not it["problems"]
                   for it in self.items())

    def status_of(self, kind: str, id_: str) -> str | None:
        return next((it["status"] for it in self.items() if it["kind"] == kind and it["id"] == id_), None)

    def gate(self) -> dict:
        pats = sorted(self.usable_patterns())
        return {"patterns": pats, "rule": self.strategy_usable(RULE_STRATEGY),
                "model": self.strategy_usable(MODEL_STRATEGY),
                "rule_status": self.status_of("strategy", RULE_STRATEGY),
                "model_status": self.status_of("strategy", MODEL_STRATEGY)}

    # ---------- changing ----------
    def _write(self, it: dict, meta: dict, body: str, new_status: str) -> dict:
        src = self.root / it["path"]
        dst = self.folder(it["kind"], new_status) / f"{it['id']}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".md.tmp")
        tmp.write_text(dump(meta, body), encoding="utf-8")
        tmp.replace(dst)
        if src.resolve() != dst.resolve():
            src.unlink(missing_ok=True)
        self._cache = None
        self.write_index()
        return self.get(it["kind"], it["id"])

    @staticmethod
    def _meta(it: dict) -> dict:
        return {k: v for k, v in it.items() if k not in ("body", "path", "problems")}

    def set_status(self, kind: str, id_: str, status: str, note: str = "", by: str = "you") -> dict:
        """Move an item through the workflow. Approving an item that already has matching code (implemented_in)
        makes it IMPLEMENTED straight away (both steps are recorded in its history)."""
        status = str(status).upper()
        with self._lock:
            it = self.get(kind, id_)
            if status not in STATUSES:
                raise KnowledgeError(f"unknown status {status}")
            if status not in TRANSITIONS[it["status"]]:
                raise KnowledgeError(f"cannot go from {it['status']} to {status}")
            if status == "IMPLEMENTED":
                self._check_implementable(it)
            if status == "BACKTESTED":
                raise KnowledgeError("BACKTESTED is set by running a backtest")
            note = str(note or "").strip()[:500]
            meta = self._meta(it)
            today = date.today().isoformat()
            hist = list(meta.get("history") or [])
            hist.append({"date": today, "status": status, "by": by, "note": note or None})
            if status in ("APPROVED", "REJECTED"):
                meta["review"] = {"by": by, "date": today, "decision": status, "note": note or None}
            if status == "APPROVED" and it.get("implemented_in"):
                try:
                    self._check_implementable(it)
                    status = "IMPLEMENTED"
                    hist.append({"date": today, "status": status, "by": "system",
                                 "note": f"code already follows this definition: {it['implemented_in']}"})
                except KnowledgeError:
                    pass
            meta["status"] = status
            meta["history"] = hist
            return self._write(it, meta, it["body"], status)

    def _check_implementable(self, it: dict):
        if not it.get("implemented_in"):
            raise KnowledgeError("no Python code yet: implement it, add tests and set implemented_in first")
        if it["kind"] == "pattern" and it.get("code_name") not in _coded_patterns():
            raise KnowledgeError(f"patterns.py does not detect '{it.get('code_name')}'")

    def record_backtest(self, kind: str, id_: str, results: dict) -> dict:
        with self._lock:
            it = self.get(kind, id_)
            if it["status"] not in USABLE:
                raise KnowledgeError(f"only IMPLEMENTED items can be backtested (this one is {it['status']})")
            meta = self._meta(it)
            meta["backtest"] = results
            meta["status"] = "BACKTESTED"
            meta["history"] = list(meta.get("history") or []) + [
                {"date": date.today().isoformat(), "status": "BACKTESTED", "by": "system",
                 "note": results.get("summary")}]
            return self._write(it, meta, it["body"], "BACKTESTED")

    # ---------- documents (layer 1) ----------
    def notes(self) -> dict:
        f = self.root / "documents" / "extracted_knowledge" / "document_notes.yaml"
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except (yaml.YAMLError, OSError):
            d = {}
        return d if isinstance(d, dict) else {}

    def book_path(self, name: str) -> Path:
        from document_reader.pdf_reader import SUPPORTED
        p = (self.books / str(name)).resolve()
        if p.parent != self.books.resolve() or p.suffix.lower() not in SUPPORTED:
            raise KnowledgeError("unknown document")
        if not p.is_file():
            raise KnowledgeError(f"{name} is not in documents/uploaded_books")
        return p

    def document_report(self, name: str) -> dict | None:
        from document_reader import knowledge_extractor, text_extractor
        ext = text_extractor.load(name, self.text_dir)
        if ext is None:
            return None
        skipped = (self.notes().get(name) or {}).get("skipped_sections") or {}
        return knowledge_extractor.report(ext, self.items(), skipped)

    def read_document(self, name: str) -> dict:
        """Extract the text of an uploaded document (page by page) and report what it covers."""
        from document_reader import text_extractor
        text_extractor.extract(self.book_path(name), self.text_dir)
        return self.document_report(name)

    def documents(self) -> list[dict]:
        from document_reader.pdf_reader import SUPPORTED
        out = []
        if self.books.is_dir():
            for f in sorted(self.books.iterdir()):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    rep = self.document_report(f.name)
                    out.append({"name": f.name, "size": f.stat().st_size, "read": rep is not None, "report": rep})
        return out

    # ---------- reports ----------
    def check(self) -> list[str]:
        """Problems in the knowledge base: bad files, wrong folders, and source quotes not found in the books."""
        from document_reader.source_reference import fmt, verify
        out = []
        for it in self.items():
            out += [f"{it['path']}: {p}" for p in it["problems"]]
            for s in it.get("sources") or []:
                v = verify(s, self.text_dir, self.books)
                if not v["ok"]:
                    out.append(f"{it['path']}: source '{fmt(s)}': {v['reason']}")
        return out

    def write_index(self) -> None:
        items = self.items()
        lines = ["# Knowledge index", "",
                 "Generated by `stockpatterns/knowledge.py` whenever a status changes "
                 "(or `python -m stockpatterns.knowledge index`). Do not edit by hand.", "",
                 "The live signal only uses items that are **IMPLEMENTED** or **BACKTESTED**.", ""]
        g = self.gate()
        lines += [f"- Patterns the live signal may use: {', '.join(g['patterns']) or 'none yet'}",
                  f"- Trend + pattern rule: {g['rule_status'] or 'missing'}"
                  f"{' (in use)' if g['rule'] else ' (not in use)'}",
                  f"- Self-learning model: {g['model_status'] or 'missing'}"
                  f"{' (may take over)' if g['model'] else ' (may not take over)'}", ""]
        for kind, sub in KINDS.items():
            rows = [it for it in items if it["kind"] == kind]
            lines += [f"## {sub.title()} ({len(rows)})", "", "| Name | Status | Source | Code | File |",
                      "|---|---|---|---|---|"]
            for it in rows:
                srcs = it.get("sources") or []
                src = "; ".join(f"{s.get('document')} p.{s.get('page')}" for s in srcs[:2]) or (
                    "existing code" if it.get("origin") == "existing-code" else "-")
                code = it.get("implemented_in") or "-"
                code = ", ".join(code) if isinstance(code, list) else code
                lines.append(f"| {it['name']} | {it['status']} | {src} | {code} | `{it['path']}` |")
            lines.append("")
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text("\n".join(lines), encoding="utf-8")


KB = KnowledgeBase()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m stockpatterns.knowledge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="rewrite knowledge/knowledge_index.md")
    sub.add_parser("check", help="list problems (bad files, unverified source quotes)")
    sub.add_parser("gate", help="what the live signal may use right now")
    s = sub.add_parser("status", help="change a status, e.g. status pattern hammer APPROVED")
    s.add_argument("kind", choices=list(KINDS))
    s.add_argument("id")
    s.add_argument("status")
    s.add_argument("--note", default="")
    s.add_argument("--by", default="you")
    a = ap.parse_args(argv)
    if a.cmd == "index":
        KB.write_index()
        print(f"wrote {KB.index_file}")
    elif a.cmd == "check":
        probs = KB.check()
        print("\n".join(probs) if probs else "OK: no problems, every source quote was found on its page")
        return 1 if probs else 0
    elif a.cmd == "gate":
        print(yaml.safe_dump(KB.gate(), sort_keys=False))
    elif a.cmd == "status":
        it = KB.set_status(a.kind, a.id, a.status, a.note, a.by)
        print(f"{it['name']}: {it['status']} ({it['path']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
