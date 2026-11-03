import unittest

import pandas as pd

from stockpatterns.backtest import study


def frame(rows, step=60):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", [1_700_000_000 + step * i for i in range(len(df))])
    df["volume"] = 1.0
    return df


def fall(n=20, start=100.0):
    return [(start - k, start - k + 0.2, start - k - 1.2, start - k - 1) for k in range(n)]


class Study(unittest.TestCase):
    def test_hammer_found_explained_and_outcome_measured(self):
        hammer = (80.0, 80.35, 78.0, 80.3)
        after = [(80.3 + k, 81.5 + k, 80.1 + k, 81.3 + k) for k in range(6)]     # price rises after
        r = study(frame(fall() + [hammer] + after), ["Hammer", "Inverted Hammer"], horizon=5)
        (o,) = [x for x in r["occurrences"] if x["name"] == "Hammer"]
        self.assertEqual(o["index"], 20)
        self.assertAlmostEqual(o["body_pct"], 0.3 / 2.35 * 100)
        self.assertAlmostEqual(o["lower_wick_x_body"], 2.0 / 0.3)
        self.assertLess(o["trend_atr"], -1)
        self.assertEqual(o["status"], "done")
        self.assertAlmostEqual(o["move"], (81.3 + 4) - 80.3)
        self.assertTrue(o["worked"])
        self.assertAlmostEqual(o["best_up"], (81.5 + 4) - 80.3)
        s = r["summary"]["Hammer"]
        self.assertEqual((s["found"], s["measured"], s["worked_pct"]), (1, 1, 1.0))
        self.assertEqual(r["summary"]["Inverted Hammer"]["found"], 0)

    def test_failed_and_too_recent(self):
        hammer = (80.0, 80.35, 78.0, 80.3)
        after = [(80.3 - k, 80.5 - k, 79.0 - k, 79.3 - k) for k in range(6)]
        r = study(frame(fall() + [hammer] + after), ["Hammer"], horizon=5)
        self.assertFalse(r["occurrences"][0]["worked"])
        r = study(frame(fall() + [hammer] + after[:2]), ["Hammer"], horizon=5)
        self.assertEqual(r["occurrences"][0]["status"], "pending")
        self.assertIsNone(r["summary"]["Hammer"]["worked_pct"])

    def test_intraday_gap_skipped_but_daily_weekends_fine(self):
        hammer = (80.0, 80.35, 78.0, 80.3)
        after = [(80.3 + k, 81.5 + k, 80.1 + k, 81.3 + k) for k in range(6)]
        df = frame(fall() + [hammer] + after)
        df.loc[23:, "time"] += 16 * 3600                       # overnight break 2 candles after the hammer
        self.assertEqual(study(df, ["Hammer"], 5)["occurrences"][0]["status"], "gap")
        daily = frame(fall() + [hammer] + after, step=86400)
        daily.loc[23:, "time"] += 2 * 86400                     # a weekend
        self.assertEqual(study(daily, ["Hammer"], 5)["occurrences"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
