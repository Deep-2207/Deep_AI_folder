import unittest
from datetime import datetime, timezone

from stockpatterns.markets import _us_fallback, _us_local, status

utc = lambda *a: datetime(*a, tzinfo=timezone.utc)


class Hours(unittest.TestCase):
    def test_evening_in_india_us_open(self):
        s = status(utc(2026, 11, 3, 15, 42))               # Tue 21:12 IST, 10:42 New York (EST)
        self.assertFalse(s["nse"]["open"])
        self.assertEqual(s["nse"]["next_ist"], "Wed 09:15 IST")
        self.assertTrue(s["us"]["open"])
        self.assertEqual((s["us"]["next"], s["us"]["next_ist"]), ("closes", "Wed 02:30 IST"))

    def test_morning_in_india_nse_open(self):
        s = status(utc(2026, 11, 3, 5, 0))                  # Tue 10:30 IST, 00:00 New York
        self.assertTrue(s["nse"]["open"])
        self.assertEqual(s["nse"]["next_ist"], "Tue 15:30 IST")
        self.assertFalse(s["us"]["open"])
        self.assertEqual(s["us"]["next_ist"], "Tue 20:00 IST")

    def test_weekend_and_summer_time(self):
        s = status(utc(2026, 11, 7, 6, 0))                  # Saturday
        self.assertFalse(s["nse"]["open"] or s["us"]["open"])
        self.assertEqual(s["nse"]["next_ist"], "Mon 09:15 IST")
        s = status(utc(2026, 7, 1, 14, 0))                  # 10:00 New York in summer (EDT)
        self.assertTrue(s["us"]["open"])
        self.assertEqual(s["us"]["next_ist"], "Thu 01:30 IST")

    def test_fallback_matches_tz_database(self):
        for t in (utc(2026, 1, 15, 15), utc(2026, 3, 8, 6, 59), utc(2026, 3, 8, 7, 1), utc(2026, 7, 1, 14),
                  utc(2026, 11, 1, 5, 59), utc(2026, 11, 1, 6, 1), utc(2026, 12, 31, 23)):
            self.assertEqual(_us_fallback(t).utcoffset(), _us_local(t).utcoffset(), t)


if __name__ == "__main__":
    unittest.main()
