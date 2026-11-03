import unittest

import pandas as pd

from stockpatterns.feeds import _snap_live_point


def frame(times, closes):
    return pd.DataFrame({"time": times, "open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes, "volume": [10.0] * len(times)})


class LivePoint(unittest.TestCase):
    def test_point_after_last_candle_becomes_the_forming_candle(self):
        df = _snap_live_point(frame([1200, 1260, 1375], [10.0, 11.0, 12.0]), 60)     # 1375 = 2 min 55 s later
        self.assertEqual(df["time"].tolist(), [1200, 1260, 1320])
        self.assertEqual(df["close"].iloc[-1], 12.0)

    def test_point_inside_the_last_candle_is_merged_into_it(self):
        df = _snap_live_point(frame([1200, 1260, 1290], [10.0, 11.0, 15.0]), 60)
        self.assertEqual(df["time"].tolist(), [1200, 1260])
        last = df.iloc[-1]
        self.assertEqual((last.open, last.close, last.high, last.low, last.volume), (11.0, 15.0, 16.0, 10.0, 20.0))

    def test_aligned_and_daily_data_untouched(self):
        df = frame([1200, 1260, 1320], [10.0, 11.0, 12.0])
        self.assertTrue(_snap_live_point(df.copy(), 60).equals(df))
        daily = frame([0, 86400, 86400 * 2 + 777], [1.0, 2.0, 3.0])
        self.assertTrue(_snap_live_point(daily.copy(), 86400).equals(daily))

    def test_session_not_on_a_round_hour(self):
        # NSE hourly candles start at 09:15 IST, so they are not multiples of 3600 since 1970
        start = 1_793_000_000 - 1_793_000_000 % 3600 + 2700
        df = _snap_live_point(frame([start, start + 3600, start + 7200 + 1234], [1.0, 2.0, 3.0]), 3600)
        self.assertEqual(df["time"].iloc[-1], start + 7200)


if __name__ == "__main__":
    unittest.main()
