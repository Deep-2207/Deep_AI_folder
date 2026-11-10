"""End-to-End API and Integration Test for Flask endpoints in app.py"""
import unittest
from app import app


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    # 1. HTML Pages
    def test_pages_load(self):
        pages = ["/", "/test", "/backtest", "/knowledge", "/market", "/strategy/ema"]
        for path in pages:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"Failed loading {path}")
            self.assertIn("text/html", r.content_type)
            self.assertGreater(len(r.data), 500, f"{path} returned empty or very short body")

    # 2. Market APIs
    def test_market_status(self):
        r = self.client.get("/api/markets")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("nse", data)
        self.assertIn("us", data)
        self.assertIn("open", data["nse"])

    def test_market_universes(self):
        r = self.client.get("/api/market/universes")
        self.assertEqual(r.status_code, 200)
        universes = r.get_json()
        self.assertIsInstance(universes, list)
        keys = [u["key"] for u in universes]
        self.assertIn("nifty50", keys)
        self.assertIn("nse_it", keys)

    # 3. Scan API with Replay/Seeder
    def test_scan_api_seeder(self):
        r = self.client.get("/api/scan?provider=seeder&symbol=SEEDED&interval=1m")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["provider"], "seeder")
        self.assertIn("candles", data)
        self.assertIn("patterns", data)
        self.assertIn("prediction", data)
        self.assertGreater(len(data["candles"]), 0)

    # 4. Signal API with Seeder
    def test_signal_api_seeder(self):
        r = self.client.get("/api/signal?provider=seeder&symbol=SEEDED&interval=1m&logic=auto")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("action", data)
        self.assertIn("state", data)
        self.assertIn("votes", data)
        self.assertIn("knowledge", data)

    # 5. Replay State and Control API
    def test_replay_state_and_control(self):
        r = self.client.get("/api/replay/state?provider=seeder&symbol=SEEDED&interval=1m")
        self.assertEqual(r.status_code, 200)
        state = r.get_json()
        self.assertIn("playing", state)
        self.assertIn("speed", state)

        # Pause
        r2 = self.client.post("/api/replay/control", json={
            "provider": "seeder", "symbol": "SEEDED", "interval": "1m", "action": "pause"
        })
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.get_json()["playing"])

        # Play
        r3 = self.client.post("/api/replay/control", json={
            "provider": "seeder", "symbol": "SEEDED", "interval": "1m", "action": "play"
        })
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(r3.get_json()["playing"])

    # 6. Knowledge API
    def test_knowledge_api(self):
        r = self.client.get("/api/knowledge")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("gate", data)
        self.assertIn("statuses", data)
        self.assertIn("items", data)

    # 7. Model API
    def test_model_actions(self):
        r = self.client.post("/api/model/reset", json={
            "provider": "seeder", "symbol": "SEEDED", "interval": "1m"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json().get("ok"))

    # 8. EMA Strategy integration
    def test_ema_strategy_integration(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn("EMA Strategy", body)
        self.assertIn("emabody", body)
        self.assertIn("executeEmaTrade", body)
        self.assertIn("applyEmaRibbon", body)
        self.assertIn("/strategy/ema", body)

        r2 = self.client.get("/strategy/ema")
        self.assertEqual(r2.status_code, 200)
        body2 = r2.data.decode("utf-8")
        self.assertIn("EMA Execution: When to Buy Calls vs. Puts", body2)
        self.assertIn("Pro Trader Visual Playbook", body2)

    # 9. NIFTY 50 and F&O support
    def test_nifty50_and_fo_support(self):
        from stockpatterns.replay import nse_symbol
        self.assertEqual(nse_symbol("NIFTY"), "^NSEI")
        self.assertEqual(nse_symbol("BANKNIFTY"), "^NSEBANK")
        self.assertEqual(nse_symbol("FINNIFTY"), "NIFTY_FIN_SERVICE.NS")
        self.assertEqual(nse_symbol("RELIANCE"), "RELIANCE.NS")

        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn("fo-bar", body)
        self.assertIn("renderFoBar", body)

        r_js = self.client.get("/static/nifty500.js")
        self.assertEqual(r_js.status_code, 200)
        js_body = r_js.data.decode("utf-8")
        self.assertIn("NIFTY50_SYMBOLS", js_body)
        self.assertIn("FO_TOP_STOCKS", js_body)


if __name__ == "__main__":
    unittest.main()
