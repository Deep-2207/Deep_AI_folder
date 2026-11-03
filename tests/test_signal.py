import unittest
from unittest import mock

import numpy as np
import pandas as pd

from stockpatterns import signal
from stockpatterns.patterns import detect
from stockpatterns.replay import seeded_frame
from stockpatterns.signal import RR, SL_ATR, WARMUP, decide, recommend, run_trades, scores


def frame(closes, wick=0.2):
    rows, prev = [], closes[0]
    for c in closes:
        rows.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", [1_700_000_000 + 60 * i for i in range(len(df))])
    df["volume"] = 1.0
    return df


def noisy(n, drift, seed):
    rng = np.random.default_rng(seed)
    return list(100 + np.cumsum(drift + rng.normal(0, 1, n)))


class Rule(unittest.TestCase):
    def test_both_votes_must_agree(self):
        p = [0.5, 0.5, -0.5, -0.5, 0.0, 0.5, 0.1]
        t = [0.5, -0.5, -0.5, 0.5, 0.9, 0.0, 0.9]
        self.assertEqual(decide(p, t).tolist(), [1, 0, -1, 0, 0, 0, 0])

    def test_no_lookahead(self):
        df = frame(noisy(800, 0.0, 1))
        full, _, _ = scores(df, detect(df), 5)
        for k in (200, 450, 799):
            part, _, _ = scores(df.iloc[:k], detect(df.iloc[:k]), 5)
            self.assertAlmostEqual(part[-1], full[k - 1], places=12)

    def test_trend_without_patterns_waits_and_says_why(self):
        df = frame([100 + i for i in range(300)])
        r = recommend(df, detect(df), current_price=400.5, horizon=5)
        self.assertEqual((r["state"], r["action"], r["votes"]["trend"]), ("wait", "WAIT", "UP"))
        self.assertIn("Waiting for a bullish pattern", r["wait_reason"])
        self.assertIsNone(r["entry"])

    def test_flat_market_waits(self):
        df = frame([100.0 + (0.3 if i % 2 else -0.3) for i in range(300)])
        r = recommend(df, detect(df), 100.0, 5)
        self.assertEqual(r["action"], "WAIT")

    def test_rule_finds_real_edge_but_not_a_fake_one(self):
        # seeder: random markets where patterns either mean nothing (50%) or really are followed through (85%)
        per_trade = {}
        for follow in (0.5, 0.85):
            rs = []
            for seed in (100, 101, 102, 103):
                df = seeded_frame("1m", follow, seed)
                k = signal.components(df, detect(df), 5)
                trades, _ = run_trades(df, decide(k["pattern"], k["trend"]), k["atr"], 20)
                rs += [x["r"] for x in trades]
            per_trade[follow] = float(np.mean(rs))
        self.assertLess(abs(per_trade[0.5]), 0.12)                 # no information -> about zero per trade
        self.assertGreater(per_trade[0.85], per_trade[0.5] + 0.08)


class Trades(unittest.TestCase):
    def test_one_trade_at_a_time_with_atr_levels(self):
        df = frame([100 + 0.5 * i for i in range(200)])         # steady rise: every CALL reaches its target
        atr = np.full(len(df), 1.0)
        dec = np.ones(len(df), dtype=int)
        trades, open_t = run_trades(df, dec, atr, max_hold=20)
        first = trades[0]
        self.assertEqual(first["entry_index"], WARMUP)
        self.assertEqual(first["entry"], df.close[WARMUP])
        self.assertAlmostEqual(first["stop"], first["entry"] - SL_ATR)
        self.assertAlmostEqual(first["target"], first["entry"] + RR * SL_ATR)
        self.assertEqual(first["exit"], "target")
        for a, b in zip(trades, trades[1:]):                      # never overlapping
            self.assertGreater(b["entry_index"], a["exit_index"])
        self.assertTrue(all(x["exit"] == "target" for x in trades))
        if open_t:
            self.assertEqual(open_t["candles_held"], len(df) - 1 - open_t["entry_index"])

    def test_stop_checked_first_and_timeout(self):
        closes = [100.0] * 130
        df = frame(closes)
        df.loc[WARMUP + 2, ["high", "low"]] = [110.0, 90.0]       # one candle touches both stop and target
        atr = np.full(len(df), 1.0)
        dec = np.zeros(len(df), dtype=int)
        dec[WARMUP] = 1
        trades, _ = run_trades(df, dec, atr, max_hold=20)
        self.assertEqual((trades[0]["exit"], trades[0]["points"]), ("stop", -SL_ATR))
        dec[:] = 0
        dec[WARMUP + 5] = -1                                      # flat afterwards: PUT times out
        trades, _ = run_trades(df, dec, atr, max_hold=20)
        self.assertEqual((trades[0]["exit"], trades[0]["exit_index"]), ("timeout", WARMUP + 25))


    def test_square_off_at_market_close(self):
        df = frame([100.0] * 140)
        df.loc[WARMUP + 5:, "time"] += 17 * 3600                 # market closes after candle WARMUP + 4
        atr = np.full(len(df), 1.0)
        dec = np.zeros(len(df), dtype=int)
        dec[WARMUP] = 1
        dec[WARMUP + 4] = -1                                     # last candle of the session: no new trade
        trades, _ = run_trades(df, dec, atr, max_hold=20)
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades[0]["exit"], trades[0]["exit_index"]), ("close", WARMUP + 4))


class States(unittest.TestCase):
    def setUp(self):
        self.df = frame([100.0] * 200)                           # ATR = 0.4, so risk = 0.6, target = 1.2

    def rec(self, signal_at, price=100.0, live_bar=None):
        dec = np.zeros(len(self.df), dtype=int)
        dec[signal_at] = 1
        with mock.patch.object(signal, "decide", return_value=dec):
            return recommend(self.df, [], price, horizon=5, live_bar=live_bar)

    def test_enter_on_fresh_signal(self):
        r = self.rec(199)
        self.assertEqual((r["state"], r["action"]), ("enter", "CALL"))
        t = r["trade"]
        self.assertEqual((t["entry"], t["candles_held"], t["candles_left"]), (100.0, 0, 20))
        self.assertAlmostEqual(t["stop"], 100 - SL_ATR * 0.4)
        self.assertAlmostEqual(t["target"], 100 + RR * SL_ATR * 0.4)

    def test_hold_then_exit_on_live_candle(self):
        r = self.rec(196, price=100.3)
        self.assertEqual(r["state"], "hold")
        self.assertEqual(r["trade"]["candles_held"], 3)
        self.assertAlmostEqual(r["trade"]["pl_points"], 0.3)
        self.assertAlmostEqual(r["trade"]["progress"], 0.3 / 1.2)
        r = self.rec(196, price=100.5, live_bar={"high": 101.3, "low": 99.9, "close": 100.5})
        self.assertEqual((r["state"], r["trade"]["hit"]), ("exit", "target"))
        r = self.rec(196, price=99.5, live_bar={"high": 100.1, "low": 99.3, "close": 99.5})
        self.assertEqual((r["state"], r["trade"]["hit"]), ("exit", "stop"))

    def test_finished_trade_reported_then_wait(self):
        r = self.rec(150)                                        # flat prices: timed out long ago
        self.assertEqual(r["state"], "wait")
        self.assertEqual(r["last_trade"]["exit"], "timeout")
        self.assertEqual(r["backtest"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
