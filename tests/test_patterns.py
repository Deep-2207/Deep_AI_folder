import unittest

import pandas as pd

from stockpatterns.patterns import detect, predict


def frame(candles):
    df = pd.DataFrame(candles, columns=["open", "high", "low", "close"])
    df.insert(0, "time", [1_700_000_000 + 60 * i for i in range(len(df))])
    df["volume"] = 1.0
    return df


def trend(direction, n=20, start=100.0):
    """n steady candles; direction -1 = falling, +1 = rising. Ends near start-n / start+n."""
    rows = []
    for k in range(n):
        o = start + direction * k
        c = o + direction
        rows.append((o, max(o, c) + 0.2, min(o, c) - 0.2, c))
    return rows


def names(df, **kw):
    return {(p["index"], p["name"]) for p in detect(df, **kw)}


class CandlePatterns(unittest.TestCase):
    def test_too_short_returns_nothing(self):
        self.assertEqual(detect(frame(trend(-1, 10))), [])

    def test_hammer_after_downtrend(self):
        rows = trend(-1) + [(80.0, 80.35, 78.0, 80.3)]
        self.assertIn((20, "Hammer"), names(frame(rows)))

    def test_hanging_man_after_uptrend(self):
        rows = trend(1) + [(120.0, 120.05, 117.7, 120.3)]
        self.assertIn((20, "Hanging Man"), names(frame(rows)))

    def test_shooting_star_after_uptrend(self):
        rows = trend(1) + [(120.0, 122.3, 119.95, 119.7)]
        self.assertIn((20, "Shooting Star"), names(frame(rows)))

    def test_doji(self):
        rows = trend(-1) + [(80.0, 80.8, 79.2, 80.02)]
        self.assertIn((20, "Doji"), names(frame(rows)))

    def test_bullish_engulfing(self):
        rows = trend(-1) + [(79.0, 81.7, 78.6, 81.5)]
        # previous candle (index 19) is red: open 81 -> close 80
        self.assertIn((20, "Bullish Engulfing"), names(frame(rows)))

    def test_bearish_engulfing(self):
        rows = trend(1) + [(121.0, 121.2, 118.6, 118.8)]
        self.assertIn((20, "Bearish Engulfing"), names(frame(rows)))

    def test_morning_star(self):
        rows = trend(-1) + [
            (80.0, 80.1, 76.9, 77.0),   # big red
            (76.5, 76.9, 76.2, 76.6),   # small body
            (76.8, 79.3, 76.7, 79.2),   # green closing above red midpoint (78.5)
        ]
        self.assertIn((22, "Morning Star"), names(frame(rows)))

    def test_evening_star(self):
        rows = trend(1) + [
            (120.0, 123.1, 119.9, 123.0),
            (123.5, 123.8, 123.1, 123.4),
            (123.2, 123.3, 120.7, 120.8),
        ]
        self.assertIn((22, "Evening Star"), names(frame(rows)))

    def test_three_white_soldiers(self):
        rows = trend(-1) + [
            (80.0, 82.1, 79.9, 82.0),
            (81.0, 84.1, 80.9, 84.0),
            (83.0, 86.1, 82.9, 86.0),
        ]
        self.assertIn((22, "Three White Soldiers"), names(frame(rows)))

    def test_no_signal_in_quiet_trend(self):
        # a clean downtrend alone should not produce reversal patterns
        found = {n for _, n in names(frame(trend(-1, 30)))}
        self.assertFalse(found & {"Hammer", "Bullish Engulfing", "Morning Star", "Double Bottom"})


class ChartPatterns(unittest.TestCase):
    @staticmethod
    def path(points, per):
        closes, price = [], points[0]
        for target, steps in zip(points[1:], per):
            for s in range(1, steps + 1):
                closes.append(price + (target - price) * s / steps)
            price = target
        return closes

    def build(self, closes):
        rows, prev = [], closes[0]
        for cl in closes:
            rows.append((prev, max(prev, cl) + 0.3, min(prev, cl) - 0.3, cl))
            prev = cl
        return frame([(100.0, 100.3, 99.7, 100.0)] * 20 + rows)

    def test_double_top(self):
        df = self.build(self.path([100, 110, 104, 110, 100], [10, 8, 8, 10]))
        self.assertTrue(any(p["name"] == "Double Top" and p["note"] == "neckline broken" for p in detect(df)))

    def test_double_bottom(self):
        df = self.build(self.path([100, 90, 96, 90, 100], [10, 8, 8, 10]))
        self.assertTrue(any(p["name"] == "Double Bottom" and p["note"] == "neckline broken" for p in detect(df)))


class Prediction(unittest.TestCase):
    def test_few_cases_falls_back_to_textbook_direction(self):
        df = frame(trend(-1) + [(80.0, 80.35, 78.0, 80.3)])
        p = predict(df, detect(df))
        self.assertEqual((p["pattern"], p["direction"], p["basis"]), ("Hammer", "UP", "rule"))
        self.assertGreater(p["target_price"], p["entry_price"])

    def test_bearish_fallback_projects_down(self):
        df = frame(trend(1) + [(120.0, 122.3, 119.95, 119.7)])
        p = predict(df, detect(df))
        self.assertEqual(p["direction"], "DOWN")
        self.assertLess(p["target_price"], p["entry_price"])

    def test_doji_is_sideways_and_none_when_empty(self):
        df = frame(trend(-1) + [(80.0, 80.8, 79.2, 80.02)])
        p = predict(df, [x for x in detect(df) if x["name"] == "Doji"])
        self.assertEqual(p["direction"], "SIDEWAYS")
        self.assertEqual(p["target_price"], p["entry_price"])
        self.assertIsNone(predict(df, []))

    def test_history_overrides_textbook_and_measures_points(self):
        # price falls exactly 2 points per candle, so every "bullish" case was followed by -10 over 5 candles
        n = 100
        closes = [1000 - 2 * i for i in range(n)]
        df = frame([(c + 2, c + 2.2, c - 0.2, c) for c in closes])
        fake = lambda i: {"index": i, "time": int(df["time"].iloc[i]), "name": "X", "direction": "bullish",
                          "confidence": 0.7, "span": 1, "note": ""}
        pats = [fake(i) for i in range(10, 95, 5)]
        p = predict(df, pats, horizon=5)
        self.assertEqual(p["basis"], "history")
        self.assertEqual(p["rule_direction"], "UP")
        self.assertEqual(p["direction"], "DOWN")
        self.assertAlmostEqual(p["expected_move"], -10.0)
        self.assertEqual(p["up_pct"], 0.0)
        self.assertEqual(p["samples"], 16)          # 10..90 step 5 = 17, minus the pattern being predicted
        self.assertAlmostEqual(p["target_price"], p["entry_price"] - 10.0)

    def test_cases_spanning_a_time_gap_are_ignored(self):
        df = frame([(100.0, 100.5, 99.5, 100.0)] * 60)
        df.loc[30:, "time"] += 10 * 3600            # overnight gap after candle 29
        pats = [{"index": i, "time": int(df["time"].iloc[i]), "name": "X", "direction": "bullish",
                 "confidence": 0.7, "span": 1, "note": ""} for i in (10, 27, 28, 29, 59)]
        p = predict(df, pats, horizon=5)
        self.assertEqual(p["samples"], 1)           # only index 10 has a gap-free look-ahead


if __name__ == "__main__":
    unittest.main()
