import time
import unittest

import numpy as np
from datetime import datetime

from stockpatterns import replay
from stockpatterns.patterns import detect

BULL = {"Hammer", "Inverted Hammer", "Bullish Engulfing", "Bullish Harami", "Piercing Line", "Tweezer Bottom",
        "Morning Star", "Three White Soldiers", "Dragonfly Doji", "Bullish Marubozu"}


class Seeder(unittest.TestCase):
    def test_candles_are_valid_and_planted_patterns_are_detected(self):
        df = replay.seeded_frame("1m", 0.7, 3)
        self.assertTrue(((df.high >= df[["open", "close"]].max(axis=1)) & (df.low <= df[["open", "close"]].min(axis=1))).all())
        _, planted = replay.seed_candles(3000, 0.7, 3)
        self.assertGreater(len(planted), 100)                      # frequent: roughly one every 15-20 candles
        found = {(p["index"], p["name"]) for p in detect(df)}
        hit = sum((i, n) in found for i, n in planted)
        self.assertGreaterEqual(hit / len(planted), 0.95)

    def test_follow_through_rate_matches_setting(self):
        for follow in (0.5, 0.9):
            ok = tot = 0
            for seed in (1, 2, 3):
                rows, planted = replay.seed_candles(3000, follow, seed)
                c = [r[3] for r in rows]
                for i, n in planted:
                    if n != "Doji" and i + 5 < len(c):
                        ok += (c[i + 5] - c[i]) * (1 if n in BULL else -1) > 0
                        tot += 1
            self.assertAlmostEqual(ok / tot, follow, delta=0.08)

    def test_nothing_to_predict_when_patterns_mean_nothing(self):
        # at 50% the closes are a pure random walk: the last 5-candle move says nothing about the next one, and
        # neither does a just-finished pattern; at 90% the move after a pattern clearly goes the textbook way.
        # (A learning model is the stricter check: see test_learner.LearnsWhatIsReal.)
        for follow in (0.5, 0.9):
            past, future, after = [], [], []
            for seed in (1, 2, 3):
                rows, planted = replay.seed_candles(3000, follow, seed)
                c = np.array([r[3] for r in rows])
                i = np.arange(25, len(c) - 5, 5)
                past += list(c[i] - c[i - 5])
                future += list(c[i + 5] - c[i])
                after += [(c[k + 5] - c[k]) * (1 if n in BULL else -1) for k, n in planted if k + 5 < len(c)]
            mean, se = np.mean(after), np.std(after) / np.sqrt(len(after))
            if follow == 0.5:
                self.assertLess(abs(np.corrcoef(past, future)[0, 1]), 0.08)
                self.assertLess(abs(mean), 3 * se)
            else:
                self.assertGreater(mean, 5 * se)

    def test_times_are_inside_nse_sessions(self):
        for t in replay.nse_times(1000, 300):
            d = datetime.fromtimestamp(t, replay.IST)
            self.assertLess(d.weekday(), 5)
            self.assertTrue((9, 15) <= (d.hour, d.minute) <= (15, 29))


class Sessions(unittest.TestCase):
    def setUp(self):
        replay._sessions.clear()

    def test_view_reveals_up_to_position_with_partial_candle(self):
        s = replay.session("seeder", "TEST", "1m")
        s.playing = False
        s.pos = 500.5
        df, forming = s.view()
        self.assertTrue(forming)
        self.assertEqual(len(df), 501)
        src = s.source.iloc[500]
        last = df.iloc[-1]
        self.assertEqual(last.open, src.open)
        self.assertAlmostEqual(last.close, src.open + (src.close - src.open) * 0.5)
        self.assertLessEqual(last.high, src.high)
        self.assertGreaterEqual(last.low, src.low)
        s.pos = 500.0
        df, forming = s.view()
        self.assertFalse(forming)
        self.assertEqual(len(df), 500)
        self.assertTrue((df.time.values == s.source.time.values[:500]).all())

    def test_play_advances_at_speed_and_controls(self):
        s = replay.control("seeder", "TEST", "1m", "pause")
        start = s.pos
        replay.control("seeder", "TEST", "1m", "speed", 600)       # 10 candles per second
        replay.control("seeder", "TEST", "1m", "play")
        time.sleep(0.3)
        s = replay.session("seeder", "TEST", "1m")
        self.assertGreater(s.pos - start, 1.5)
        s = replay.control("seeder", "TEST", "1m", "step")
        self.assertFalse(s.playing)
        self.assertEqual(s.pos, int(s.pos))
        s = replay.control("seeder", "TEST", "1m", "seek", 100)
        self.assertEqual(s.pos, 100)
        old = s.source.close.iloc[-1]
        s = replay.control("seeder", "TEST", "1m", "new")
        self.assertNotEqual(s.source.close.iloc[-1], old)
        s = replay.control("seeder", "TEST", "1m", "follow", 0.9)
        self.assertEqual(s.follow, 0.9)
        with self.assertRaises(ValueError):
            replay.control("seeder", "TEST", "1m", "bogus")


if __name__ == "__main__":
    unittest.main()
