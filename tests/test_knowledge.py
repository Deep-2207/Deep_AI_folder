"""Knowledge base, review workflow, approval gate, document reading and source checks."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from document_reader import knowledge_extractor, text_extractor
from document_reader.source_reference import verify
from stockpatterns import knowledge, replay
from stockpatterns.backtest import pattern_performance, rule_performance
from stockpatterns.patterns import PATTERN_NAMES, detect
from tests.kb_helpers import make_kb, write_item

REAL = knowledge.KB
BOOK = "dummy_trading_knowledge_book.pdf"


class Workflow(unittest.TestCase):
    def test_nothing_is_usable_until_approved(self):
        kb = make_kb()
        self.assertEqual(kb.usable_patterns(), set())
        self.assertFalse(kb.strategy_usable(knowledge.RULE_STRATEGY))

    def test_approving_coded_pattern_makes_it_implemented_and_moves_the_file(self):
        kb = make_kb()
        it = kb.set_status("pattern", "hammer", "APPROVED", "looks right")
        self.assertEqual(it["status"], "IMPLEMENTED")
        self.assertTrue(it["path"].startswith("knowledge/approved_patterns/"))
        self.assertFalse((kb.root / "documents/extracted_knowledge/patterns/hammer.md").exists())
        self.assertEqual(kb.usable_patterns(), {"Hammer"})
        self.assertEqual([h["status"] for h in it["history"]], ["APPROVED", "IMPLEMENTED"])
        self.assertEqual(it["review"]["note"], "looks right")
        self.assertIn("Hammer", kb.index_file.read_text(encoding="utf-8"))

    def test_approved_without_code_is_not_used(self):
        kb = make_kb(patterns=())
        write_item(kb, "pattern", "bullish_engulfing", name="Bullish Engulfing", code_name="Bullish Engulfing")
        it = kb.set_status("pattern", "bullish_engulfing", "APPROVED")
        self.assertEqual(it["status"], "APPROVED")
        self.assertEqual(kb.usable_patterns(), set())
        with self.assertRaises(knowledge.KnowledgeError):              # no code yet
            kb.set_status("pattern", "bullish_engulfing", "IMPLEMENTED")

    def test_transitions_are_enforced(self):
        kb = make_kb()
        write_item(kb, "concept", "raw", "EXTRACTED")
        with self.assertRaises(knowledge.KnowledgeError):              # must be reviewed first
            kb.set_status("concept", "raw", "APPROVED")
        with self.assertRaises(knowledge.KnowledgeError):              # only a backtest sets BACKTESTED
            kb.set_status("pattern", "hammer", "BACKTESTED")
        kb.set_status("pattern", "hammer", "REJECTED", "no")
        self.assertEqual(kb.get("pattern", "hammer")["status"], "REJECTED")
        self.assertEqual(kb.set_status("pattern", "hammer", "PENDING_REVIEW")["status"], "PENDING_REVIEW")
        with self.assertRaises(knowledge.KnowledgeError):
            kb.get("pattern", "../secret")

    def test_revoking_removes_it_from_the_gate(self):
        kb = make_kb()
        kb.set_status("pattern", "hammer", "APPROVED")
        kb.set_status("pattern", "hammer", "PENDING_REVIEW", "re-check")
        self.assertEqual(kb.usable_patterns(), set())

    def test_backtest_only_after_implemented(self):
        kb = make_kb()
        with self.assertRaises(knowledge.KnowledgeError):
            kb.record_backtest("pattern", "hammer", {"summary": "x"})
        kb.set_status("pattern", "hammer", "APPROVED")
        it = kb.record_backtest("pattern", "hammer", {"summary": "ok", "runs": []})
        self.assertEqual(it["status"], "BACKTESTED")
        self.assertEqual(kb.usable_patterns(), {"Hammer"})

    def test_bad_files_are_flagged_and_never_used(self):
        kb = make_kb(patterns=())
        # claims IMPLEMENTED but sits in the extracted folder, and its detector does not exist
        d = kb.folder("pattern", "PENDING_REVIEW")
        d.mkdir(parents=True, exist_ok=True)
        (d / "fake.md").write_text(knowledge.dump({"id": "fake", "name": "Fake", "kind": "pattern",
                                                   "status": "IMPLEMENTED", "code_name": "Unicorn",
                                                   "implemented_in": "x.py"}, "# Fake\n"), encoding="utf-8")
        it = kb.get("pattern", "fake")
        self.assertTrue(any("status IMPLEMENTED but the file is in" in p for p in it["problems"]))
        self.assertTrue(any("not detected by patterns.py" in p for p in it["problems"]))
        self.assertEqual(kb.usable_patterns(), set())


class RealKnowledgeBase(unittest.TestCase):
    def test_every_coded_pattern_has_a_knowledge_file(self):
        names = {it.get("code_name") for it in REAL.items() if it["kind"] == "pattern"}
        self.assertEqual(set(PATTERN_NAMES) - names, set())

    def test_detect_only_returns_known_names(self):
        df = replay.seeded_frame("1m", 0.7, 3, 3000)
        self.assertTrue({p["name"] for p in detect(df)} <= set(PATTERN_NAMES))

    def test_no_problems_and_every_quote_is_on_its_page(self):
        self.assertEqual(REAL.check(), [])

    def test_book_is_fully_covered(self):
        rep = REAL.document_report(BOOK)
        self.assertIsNotNone(rep)
        self.assertEqual(rep["not_extracted"], 0, rep["ask_claude"])
        self.assertEqual(rep["page_count"], 5)


class Documents(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="docs_"))
        hdr = "My Book - sample\n"
        pages = [hdr + "MY TRADING\nBOOK\nIntro text\n1", hdr + "Chapter 1: Hammers\nA hammer has a long lower "
                 "wick.\nSee also Morning Star.\n2", hdr + "2. Risk rules\nAlways use a stop-loss.\n3"]
        (self.dir / "book.txt").write_text("\f".join(pages), encoding="utf-8")
        self.ext = text_extractor.extract(self.dir / "book.txt", self.dir / "out")

    def test_pages_headers_and_sections(self):
        self.assertEqual(self.ext["page_count"], 3)
        self.assertEqual(self.ext["title"], "My Trading Book")
        self.assertNotIn("My Book - sample", self.ext["pages"][1]["text"])       # running header removed
        self.assertEqual([(s["number"], s["title"], s["page_start"]) for s in self.ext["sections"]],
                         [("1", "Hammers", 2), ("2", "Risk rules", 3)])

    def test_mentions_and_coverage(self):
        names = {m["name"]: m["pages"] for m in knowledge_extractor.mentions(self.ext)}
        self.assertEqual(names["Hammer"], [2])
        self.assertEqual(names["Morning Star"], [2])
        items = [{"kind": "pattern", "id": "hammer", "name": "Hammer", "status": "PENDING_REVIEW",
                  "sources": [{"document": "book.txt", "section": "Chapter 1: Hammers", "page": 2}]}]
        rep = knowledge_extractor.report(self.ext, items)
        self.assertEqual([s["covered"] for s in rep["sections"]], [True, False])
        self.assertIn("2. Risk rules", rep["ask_claude"])
        rep = knowledge_extractor.report(self.ext, items, {"2": "not knowledge"})
        self.assertEqual(rep["not_extracted"], 0)

    def test_source_quotes_are_checked_against_the_page(self):
        out = self.dir / "out"
        ok = {"document": "book.txt", "page": 2, "quote": "A hammer has a long   lower wick."}
        self.assertTrue(verify(ok, out)["ok"])
        self.assertIn("is on page 2", verify({**ok, "page": 3}, out)["reason"])
        self.assertIn("not found", verify({**ok, "quote": "A hammer always wins."}, out)["reason"])
        self.assertIn("not been read", verify({**ok, "document": "other.pdf"}, out)["reason"])


class Backtests(unittest.TestCase):
    def test_pattern_and_rule_performance_split_dev_and_oos(self):
        df = replay.seeded_frame("1d", 0.85, 5, 3000)
        r = pattern_performance(df, "Hammer", 5)
        self.assertEqual(r["direction"], "UP")
        dev, oos = r["development"], r["out_of_sample"]
        self.assertEqual(dev["candles"] + oos["candles"], len(df))
        self.assertGreater(dev["found"], 0)
        self.assertGreater(oos["found"], 0)
        self.assertGreater(oos["hit_pct"], oos["baseline_pct"])        # the seeder makes patterns work at 85%
        rr = rule_performance(df, set(PATTERN_NAMES), 5)
        self.assertGreater(rr["development"]["trades"] + rr["out_of_sample"]["trades"], 0)
        self.assertEqual(rule_performance(df, set(), 5)["out_of_sample"]["trades"], 0)


class Api(unittest.TestCase):
    def setUp(self):
        import app as web
        self.web, self.c = web, web.app.test_client()
        replay.control("seeder", "KBTEST", "1m", "pause")
        self.q = "/api/signal?provider=seeder&symbol=KBTEST&interval=1m&horizon=5&logic=rule"

    def tearDown(self):
        knowledge.KB = REAL
        self.web.knowledge.KB = REAL

    def use(self, kb):
        knowledge.KB = kb
        self.web.knowledge.KB = kb

    def test_signal_waits_until_the_rule_is_approved(self):
        self.use(make_kb())
        d = self.c.get(self.q).get_json()
        self.assertEqual((d["action"], d["state"], d["signal_now"]), ("WAIT", "wait", "WAIT"))
        self.assertIn("Knowledge gate", d["wait_reason"])
        self.assertEqual(d["backtest"]["trades"], 0)
        self.assertEqual(d["knowledge"]["rule"], "PENDING_REVIEW")

    def test_only_approved_patterns_reach_the_signal(self):
        self.use(make_kb(patterns=("Hammer",), status="IMPLEMENTED"))
        d = self.c.get(self.q).get_json()
        self.assertEqual(d["knowledge"]["patterns"], ["Hammer"])
        self.assertTrue(all(p["name"] == "Hammer" for p in d["detail"]["patterns"]))
        s = self.c.get("/api/scan?provider=seeder&symbol=KBTEST&interval=1m&limit=300").get_json()
        self.assertTrue(all(p["approved"] == (p["name"] == "Hammer") for p in s["patterns"]))

    def test_knowledge_endpoints(self):
        self.use(make_kb())
        d = self.c.get("/api/knowledge").get_json()
        self.assertEqual(len(d["items"]), len(PATTERN_NAMES) + 2)
        r = self.c.post("/api/knowledge/pattern/hammer/status", json={"status": "APPROVED"})
        self.assertEqual(r.get_json()["item"]["status"], "IMPLEMENTED")
        self.assertEqual(self.c.post("/api/knowledge/pattern/hammer/status", json={"status": "EXTRACTED"}).status_code, 400)
        self.assertEqual(self.c.post("/api/knowledge/concept/nope/backtest").status_code, 400)
        self.assertEqual(self.c.post("/api/documents/read", json={"name": "../app.py"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
