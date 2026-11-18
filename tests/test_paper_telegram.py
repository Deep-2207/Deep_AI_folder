"""Paper trader: turns /api/signal responses into paper trades and Telegram messages (no network)."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import paper_telegram as pt

SEC = 300
T0 = 1_794_000_000 - 1_794_000_000 % SEC     # entry candle open time


def rec(state="wait", trade=None, **kw):
    r = {"provider": "yahoo", "symbol": "^NSEI", "interval": "5m", "interval_seconds": SEC, "state": state,
         "action": trade["side"] if trade else "WAIT", "logic": "rule", "rr": 2.0, "stale": False,
         "current_price": 24000.0, "trade": trade, "last_trade": None, "trades": [],
         "explain": ["Trend UP: EMA20 is 1.2 ATR above EMA50", "Hammer (1 candles ago): rose 68% of 25 times"]}
    r.update(kw)
    return r


def call_trade(held=0, hit=None):
    return {"side": "CALL", "entry_time": T0, "entry": 24000.0, "stop": 23970.0, "target": 24060.0,
            "stop_points": 30.0, "target_points": 60.0, "candles_held": held, "max_hold": 20, "hit": hit}


class PaperTraderTest(unittest.TestCase):
    def test_wait_sends_nothing(self):
        p = pt.PaperTrader()
        self.assertEqual(p.step(rec(), T0 + SEC), ([], []))

    def test_enter_opens_once(self):
        p = pt.PaperTrader()
        msgs, _ = p.step(rec("enter", call_trade()), T0 + SEC + 5)
        self.assertEqual(len(msgs), 1)
        self.assertIn("PAPER TRADE TAKEN", msgs[0])
        self.assertIn("BUY CALL", msgs[0])
        self.assertIn("NIFTY 50", msgs[0])
        self.assertIn("24,000.00", msgs[0])
        self.assertIn("Not financial advice", msgs[0])
        # the same signal polled again (and after a restart from saved state) is not sent twice
        self.assertEqual(p.step(rec("enter", call_trade()), T0 + SEC + 20)[0], [])
        p2 = pt.PaperTrader(p.state)
        self.assertEqual(p2.step(rec("enter", call_trade()), T0 + SEC + 40)[0], [])

    def test_running_trade_is_joined_late_and_tracked(self):
        p = pt.PaperTrader()
        running = {**call_trade(held=3), "pl_points": 12.0, "pl_r": 0.4, "candles_left": 17}
        msgs, _ = p.step(rec("hold", running), T0 + 4 * SEC)
        self.assertEqual(len(msgs), 1)
        self.assertIn("RUNNING TRADE (bot joined late)", msgs[0])
        self.assertIn("+12.00 pts", msgs[0])
        self.assertTrue(next(iter(p.state["open"].values()))["joined_late"])
        self.assertEqual(p.step(rec("hold", running), T0 + 5 * SEC)[0], [])          # sent once
        msgs, closed = p.step(rec("exit", {**running, "hit": "target"}), T0 + 6 * SEC)
        self.assertIn("TARGET HIT", msgs[0])
        self.assertTrue(closed[0]["joined_late"])

    def test_exit_state_seen_first_is_ignored(self):
        p = pt.PaperTrader()
        self.assertEqual(p.step(rec("exit", call_trade(held=3, hit="stop")), T0 + 4 * SEC)[0], [])

    def test_stale_feed_opens_nothing(self):
        p = pt.PaperTrader()
        self.assertEqual(p.step(rec("enter", call_trade(), stale=True), T0 + SEC)[0], [])

    def test_target_hit_live(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        self.assertEqual(p.step(rec("hold", call_trade(held=1)), T0 + 2 * SEC)[0], [])
        msgs, closed = p.step(rec("exit", call_trade(held=2, hit="target")), T0 + 3 * SEC)
        self.assertIn("TARGET HIT", msgs[0])
        self.assertAlmostEqual(closed[0]["r"], 2.0)
        self.assertAlmostEqual(closed[0]["points"], 60.0)
        self.assertEqual(p.state["open"], {})

    def test_stop_hit_on_put(self):
        t = {**call_trade(), "side": "PUT", "stop": 24030.0, "target": 23940.0}
        p = pt.PaperTrader()
        p.step(rec("enter", t), T0 + SEC)
        msgs, closed = p.step(rec("exit", {**t, "hit": "stop", "candles_held": 1}), T0 + 2 * SEC)
        self.assertIn("STOP HIT", msgs[0])
        self.assertAlmostEqual(closed[0]["r"], -1.0)

    def test_engine_closed_trade_time_exit(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        done = {"side": "CALL", "entry_time": T0, "entry": 24000.0, "stop": 23970.0, "target": 24060.0,
                "exit": "timeout", "exit_time": T0 + 20 * SEC, "exit_price": 24015.0, "points": 15.0, "r": 0.5}
        msgs, closed = p.step(rec("wait", None, last_trade=done), T0 + 21 * SEC)
        self.assertIn("TIME EXIT", msgs[0])
        self.assertAlmostEqual(closed[0]["r"], 0.5)
        self.assertEqual(closed[0]["candles_held"], 20)

    def test_market_close_from_trade_list(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        x = {"side": "CALL", "entry_time": T0, "exit": "close", "exit_time": T0 + 5 * SEC, "points": -12.0, "r": -0.4}
        msgs, closed = p.step(rec("wait", None, trades=[x]), T0 + 10 * SEC)
        self.assertIn("MARKET CLOSE EXIT", msgs[0])
        self.assertAlmostEqual(closed[0]["exit_price"], 23988.0)

    def test_lost_trade_is_closed_eventually(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        self.assertEqual(p.step(rec(), T0 + 30 * SEC)[0], [])
        msgs, _ = p.step(rec(), T0 + SEC + 3 * 20 * SEC + 1)      # > 3 x max_hold candles after entry
        self.assertIn("TRADE LOST", msgs[0])

    def test_trade_missing_from_history_is_replaced_by_newer_one(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        newer = {**call_trade(held=1), "entry_time": T0 + 2 * SEC, "pl_points": 1.0, "pl_r": 0.1, "candles_left": 19}
        msgs, closed = p.step(rec("hold", newer, current_price=24010.0), T0 + 4 * SEC)
        self.assertIn("TRADE REPLACED", msgs[0])
        self.assertAlmostEqual(closed[0]["points"], 10.0)
        self.assertIn("RUNNING TRADE", msgs[1])                  # the engine's current trade is picked up
        self.assertEqual(len(p.state["open"]), 1)

    def test_orphan_on_unwatched_chart_is_closed(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        self.assertEqual(p.orphans({("yahoo", "^NSEI", "5m")}), [])
        ks = p.orphans({("yahoo", "^NSEI", "1m")})
        self.assertEqual(len(ks), 1)
        running = {**call_trade(held=2), "pl_points": 6.0, "pl_r": 0.2, "candles_left": 18}
        msgs, closed = p.close_orphan(ks[0], rec("hold", running, current_price=24006.0), T0 + 3 * SEC)
        self.assertEqual(len(msgs), 1)
        self.assertIn("bot no longer watches", msgs[0])
        self.assertAlmostEqual(closed[0]["points"], 6.0)
        self.assertEqual(p.state["open"], {})

    def test_other_chart_does_not_close_trade(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        p.step(rec(symbol="^NSEBANK"), T0 + 2 * SEC)
        self.assertEqual(len(p.state["open"]), 1)

    def test_summary_once_per_weekday_after_time(self):
        p = pt.PaperTrader()
        wed_1500 = datetime(2026, 11, 11, 15, 0, tzinfo=pt.IST).timestamp()
        wed_1540 = datetime(2026, 11, 11, 15, 40, tzinfo=pt.IST).timestamp()
        sat_1540 = datetime(2026, 11, 14, 15, 40, tzinfo=pt.IST).timestamp()
        self.assertIsNone(p.summary_due(wed_1500, "15:35"))
        self.assertEqual(p.summary_due(wed_1540, "15:35"), "2026-11-11")
        p.state["last_summary"] = "2026-11-11"
        self.assertIsNone(p.summary_due(wed_1540 + 60, "15:35"))
        self.assertIsNone(p.summary_due(sat_1540, "15:35"))

    def test_csv_and_summary(self):
        p = pt.PaperTrader()
        p.step(rec("enter", call_trade()), T0 + SEC)
        _, closed = p.step(rec("exit", call_trade(held=2, hit="target")), T0 + 3 * SEC)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trades.csv"
            pt.append_trades(path, closed)
            day = pt.ist(T0 + 3 * SEC).strftime("%Y-%m-%d")
            rows = pt.trades_on(path, day)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["exit"], "target")
            text = pt.summary_message(day, rows)
            self.assertIn("Trades: 1", text)
            self.assertIn("+2.0R", text)
        self.assertIn("No paper trades today", pt.summary_message("2026-11-13", []))

    def test_sent_messages_log_and_report(self):
        p = pt.PaperTrader()
        m1, _ = p.step(rec("enter", call_trade()), T0 + SEC)
        m2, closed = p.step(rec("exit", call_trade(held=2, hit="target")), T0 + 3 * SEC)
        self.assertEqual((m1[0].kind, m2[0].kind), ("entry", "exit"))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for m in m1 + m2:
                pt.log_message(d / "messages.csv", m.to_outbox(T0), T0 + 3 * SEC, "sent")
            pt.append_trades(d / "trades.csv", closed)
            import csv
            with (d / "messages.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r["kind"] for r in rows], ["entry", "exit"])
            self.assertEqual(rows[0]["side"], "CALL")
            self.assertEqual(float(rows[0]["target"]), 24060.0)
            self.assertEqual(rows[1]["exit"], "target")
            self.assertIn("PAPER TRADE TAKEN", rows[0]["text"])
            text = pt.report(d)
            self.assertIn("Closed trades: 1", text)
            self.assertIn("+2.00R", text)
            self.assertIn("Messages sent: 2 (entry 1, exit 1)", text)

    def test_parse_symbols(self):
        self.assertEqual(pt.parse_symbols("yahoo:^NSEI, nse:RELIANCE,BTC"),
                         [("yahoo", "^NSEI"), ("nse", "RELIANCE"), ("yahoo", "BTC")])


if __name__ == "__main__":
    unittest.main()
