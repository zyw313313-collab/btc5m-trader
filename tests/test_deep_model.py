import json
import math
import tempfile
import unittest

from btc5m.config import Settings
from btc5m.deep_model import DeepModelManager
from btc5m.engine import PredictionEngine


def synthetic_bars(count=180):
    bars = []
    price = 100.0
    for index in range(count):
        wave = math.sin(index / 4.0) * 0.35
        drift = 0.08 if (index // 7) % 2 == 0 else -0.05
        open_price = price
        close_price = max(1.0, open_price + wave + drift)
        high = max(open_price, close_price) + 0.08
        low = min(open_price, close_price) - 0.08
        bars.append(
            {
                "open_time": index * 300_000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1000.0 + (index % 9) * 25.0,
                "close_time": index * 300_000 + 299_999,
                "quote_volume": close_price * 1000.0,
                "trades": 100 + index,
            }
        )
        price = close_price
    return bars


class DeepModelTests(unittest.TestCase):
    def test_untrained_reference_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                deep_model_path=f"{directory}/deep.json",
            )
            manager = DeepModelManager(settings)
            reference = manager.reference(synthetic_bars(40))
            self.assertFalse(reference.available)
            self.assertFalse(reference.approved_for_decision)
            self.assertEqual(reference.reason, "deep_model_not_trained")

    def test_train_reload_and_time_split_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                deep_model_path=f"{directory}/deep.json",
                prediction_deep_min_train_samples=60,
                prediction_deep_epochs=1,
            )
            manager = DeepModelManager(settings)
            status = manager.train(synthetic_bars())

            self.assertTrue(status["available"])
            self.assertEqual(status["approved_for_decision"], False)
            self.assertEqual(
                status["training_samples"],
                status["train_samples"]
                + status["validation_samples"]
                + status["test_samples"],
            )
            self.assertEqual(status["calibration_status"], "temperature_scaled")

            reloaded = DeepModelManager(settings)
            reference = reloaded.reference(synthetic_bars())
            self.assertTrue(reference.available)
            self.assertGreaterEqual(reference.calibrated_probability, 0.0)
            self.assertLessEqual(reference.calibrated_probability, 1.0)
            with open(settings.deep_model_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertFalse(saved["metadata"]["approved_for_decision"])

    def test_unapproved_deep_model_cannot_change_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                prediction_deep_use_for_decision=True,
            )
            engine = PredictionEngine(settings)
            snapshot = {
                "data_ready": True,
                "data_age_ms": 100,
                "trade_count_15s": 20,
                "trade_imbalance_15s": 0.35,
                "trade_imbalance_60s": 0.22,
                "book_imbalance": 0.30,
                "momentum_15s": 0.0008,
                "spread_bps": 1.2,
            }
            baseline = engine._combine_realtime_probability(
                0.65, snapshot, deep_probability=0.10, deep_approved=False
            )
            reference_only = engine._combine_realtime_probability(
                0.65, snapshot, deep_probability=None, deep_approved=False
            )
            self.assertAlmostEqual(baseline, reference_only)

            decision = engine.realtime_decision(
                {
                    "start_time": 0,
                    "end_time": 300_000,
                    "p_up": baseline,
                    "up_odds": 1.9,
                    "down_odds": 1.9,
                },
                snapshot,
                now_ms=60_000,
                baseline_p_up=0.65,
                deep_probability=0.10,
                deep_status={
                    "model_version": "test",
                    "training_samples": 500,
                    "calibration_status": "temperature_scaled",
                    "approved_for_decision": False,
                },
                deep_approved=False,
            )
            self.assertFalse(decision["deep_used_for_decision"])
            self.assertNotIn("deep", decision["votes"])


if __name__ == "__main__":
    unittest.main()
