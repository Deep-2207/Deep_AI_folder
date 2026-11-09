import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from stockpatterns import learner, replay
from stockpatterns import signal as S
from stockpatterns.patterns import detect


def learn(df, key=("seeder", "T", "1m", 5)):
    """Run the walk-forward learner on `df` in one go; returns (candles, preds, model, log, processed, summary)."""
    lr = learner.Learner(key, persist=False)
    return lr.update((lr.candles, lr.preds, lr.model, [], 0), df)


def idle(lr, timeout=60):
    with lr.cond:
        lr.cond.wait_for(lambda: not lr.busy, timeout)


class Features(unittest.TestCase):
    def test_no_lookahead(self):
        df = replay.seeded_frame("1m", 0.7, 5, 900)
        pats = detect(df)
        full = learner.features(df, pats, S.components(df, pats, 5))
        for k in (300, 650):
            part = df.iloc[:k]
            p = detect(part)
            np.testing.assert_allclose(learner.features(part, p, S.components(part, p, 5)), full[:k], atol=1e-12)


class Lessons(unittest.TestCase):
    def test_outcomes_match_the_trade_engine(self):
        df = replay.seeded_frame("1m", 0.7, 6, 1500)
        k = S.components(df, detect(df), 5)
        for d in (1, -1):
            r, done = learner.outcomes(df, k["atr"], d, 20)
            for i in range(120, 1490, 23):
                dec = np.zeros(len(df), dtype=int)
                dec[i] = d
                trades, _ = S.run_trades(df, dec, k["atr"], 20)
                if trades:
                    self.assertAlmostEqual(r[i], trades[0]["r"], places=9)
                    self.assertEqual(done[i], trades[0]["exit_index"])
                else:                                   # no entry possible there, or still running at the end
                    self.assertTrue(np.isnan(r[i]))


class WalkForward(unittest.TestCase):
    def test_never_learns_from_the_future(self):
        df = replay.seeded_frame("1m", 0.7, 7, 2400)
        cut = 1700
        other = replay.seeded_frame("1m", 0.3, 8, 2400)
        moved = df.copy()                               # same past, a completely different future after `cut`
        moved.iloc[cut:, 1:5] = other.iloc[cut:, 1:5].to_numpy() - other["close"].iloc[cut] + df["close"].iloc[cut - 1]
        pa = learn(df)[1].set_index("time")
        pb = learn(moved)[1].set_index("time")
        t_cut = int(df["time"].iloc[cut])
        before = pa.index[pa.index < t_cut]
        self.assertGreater(len(before), 300)
        pd.testing.assert_frame_equal(pa.loc[before], pb.loc[before])
        after = pa.index[pa.index >= t_cut]
        self.assertFalse(np.allclose(pa.loc[after, "call_r"], pb.loc[after, "call_r"]))   # the test can tell

    def test_bit_by_bit_equals_all_at_once(self):
        df = replay.seeded_frame("1m", 0.7, 9, 2200)
        whole = learn(df)
        lr = learner.Learner(("seeder", "T2", "1m", 5), persist=False)
        state = (lr.candles, lr.preds, lr.model, [], 0)
        for end in list(range(700, 2200, 150)) + [2200]:
            state = lr.update(state[:5], df.iloc[:end])
        pd.testing.assert_frame_equal(state[1].reset_index(drop=True), whole[1].reset_index(drop=True))
        self.assertEqual(state[5]["record"], whole[5]["record"])
        self.assertEqual(state[2]["version"], whole[2]["version"])

    def test_retrains_every_200_candles_and_waits_for_enough_lessons(self):
        df = replay.seeded_frame("1m", 0.7, 10, 2000)
        candles, preds, model, log, processed, s = learn(df)
        first = preds["time"].iloc[0]
        self.assertGreater(int(np.searchsorted(df["time"], first)), learner.FIRST_LESSONS)
        sizes = preds.groupby("version").size().to_numpy()
        self.assertTrue((sizes[:-1] == learner.RETRAIN_EVERY).all())
        self.assertEqual(s["version"], len(log))
        self.assertEqual(s["phase"], "ready")
        self.assertEqual(processed, int(df["time"].iloc[-1]))


class Gate(unittest.TestCase):
    def test_takes_over_only_when_proven_and_better_than_the_rule(self):
        rec = lambda rs: learner.record([{"r": x} for x in rs])
        good = rec([2, -1, 2, -1, 2] * 30)             # 150 trades, +0.8R each
        flat = rec([2, -1, -1] * 40)                   # 0R
        g = learner.gate(good, flat)
        self.assertTrue(g["enough"] and g["beyond_luck"] and g["beats_rule"] and g["promoted"])
        self.assertFalse(learner.gate(flat, rec([]))["promoted"])                  # no profit
        self.assertFalse(learner.gate(rec([2, -1, 2] * 10), flat)["promoted"])     # too few trades
        self.assertFalse(learner.gate(good, rec([2, 2, -1] * 50))["promoted"])     # the rule did better
        self.assertFalse(learner.gate(rec([]), rec([]))["promoted"])


class LearnsWhatIsReal(unittest.TestCase):
    def test_finds_a_real_edge_but_not_a_fake_one(self):
        for seed in (21, 22):
            s85 = learn(replay.seeded_frame("1m", 0.85, seed))[5]
            self.assertGreater(s85["record"]["model"]["avg_r"], 0.15)
            self.assertTrue(s85["gate"]["beyond_luck"])
            s50 = learn(replay.seeded_frame("1m", 0.5, seed))[5]      # patterns mean nothing: nothing to learn
            self.assertFalse(s50["gate"]["beyond_luck"])
            self.assertFalse(s50["gate"]["promoted"])


class Saving(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(learner, "MODEL_DIR", self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_saved_model_is_loaded_and_keeps_learning(self):
        df = replay.seeded_frame("1m", 0.7, 11, 2200)
        key = ("yahoo", "TEST", "1m", 5)
        lr = learner.Learner(key, persist=True)
        lr.submit(df.iloc[:2000])
        idle(lr)
        self.assertIsNone(lr.error)
        self.assertTrue((self.tmp / "yahoo_TEST_1m_h5" / "model.joblib").exists())

        again = learner.Learner(key, persist=True)        # e.g. after restarting the app
        self.assertEqual(again.processed, lr.processed)
        self.assertEqual(again.model["version"], lr.model["version"])
        pd.testing.assert_frame_equal(again.preds.reset_index(drop=True), lr.preds.reset_index(drop=True),
                                      check_dtype=False)
        again.submit(df)
        idle(again)
        old, new = lr.preds.set_index("time"), again.preds.set_index("time")
        pd.testing.assert_frame_equal(new.loc[old.index], old, check_dtype=False)   # the past is never rewritten
        self.assertGreater(len(new), len(old))
        self.assertEqual(again.processed, int(df["time"].iloc[-1]))

        learner._learners[learner.chart_key(*key)] = again
        learner.reset(*key)
        self.assertFalse((self.tmp / "yahoo_TEST_1m_h5").exists())


class TestLab(unittest.TestCase):
    def test_new_or_rewound_replay_data_starts_over(self):
        lr = learner.Learner(("seeder", "TL", "1m", 5), persist=False)
        a = replay.seeded_frame("1m", 0.7, 12, 1300)
        lr.submit(a)
        idle(lr)
        self.assertEqual(lr.processed, int(a["time"].iloc[-1]))
        b = replay.seeded_frame("1m", 0.7, 13, 1300)    # "New data": same times, other prices
        lr.submit(b)
        idle(lr)
        np.testing.assert_allclose(lr.candles["close"].to_numpy(), b["close"].to_numpy())
        lr.submit(b.iloc[:900])                         # jumped back in time
        idle(lr)
        self.assertEqual(len(lr.candles), 900)
        self.assertEqual(lr.processed, int(b["time"].iloc[899]))


class Api(unittest.TestCase):
    def setUp(self):                    # everything approved, so the knowledge gate does not block the logic switch
        from stockpatterns import knowledge
        from tests.kb_helpers import make_kb
        import app as web
        self.real, self.web = knowledge.KB, web
        knowledge.KB = web.knowledge.KB = make_kb(status="IMPLEMENTED")

    def tearDown(self):
        from stockpatterns import knowledge
        knowledge.KB = self.web.knowledge.KB = self.real

    def test_signal_reports_the_model_and_obeys_the_logic_switch(self):
        web = self.web
        c = web.app.test_client()
        replay.control("seeder", "APITEST", "1m", "pause")
        q = "/api/signal?provider=seeder&symbol=APITEST&interval=1m&horizon=5"
        d = c.get(q).get_json()
        self.assertEqual(d["logic"], "rule")
        self.assertIn(d["model"]["phase"], ("learning", "ready"))
        idle(learner.get("seeder", "APITEST", "1m", 5, persist=False))
        d = c.get(q + "&logic=model").get_json()
        self.assertEqual((d["logic"], d["model"]["active"], d["model"]["phase"]), ("model", "model", "ready"))
        self.assertIsNotNone(d["model"]["opinion"])
        self.assertIn(d["state"], ("enter", "hold", "exit", "wait"))
        self.assertEqual(c.get(q + "&logic=rule").get_json()["logic"], "rule")
        self.assertEqual(c.get(q + "&logic=bogus").status_code, 400)
        version = d["model"]["version"]
        body = {"provider": "seeder", "symbol": "APITEST", "interval": "1m", "horizon": 5}
        self.assertTrue(c.post("/api/model/retrain", json=body).get_json()["ok"])
        idle(learner.get("seeder", "APITEST", "1m", 5, persist=False))
        self.assertEqual(c.get(q).get_json()["model"]["version"], version + 1)
        self.assertTrue(c.post("/api/model/reset", json=body).get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
