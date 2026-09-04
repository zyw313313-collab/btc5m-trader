import tempfile
import unittest

from btc5m.config import Settings
from btc5m.engine import PredictionEngine


def snapshot(**changes):
    value = {
        "data_ready": True,
        "data_age_ms": 100,
        "trade_count_15s": 20,
        "trade_imbalance_15s": 0.35,
        "trade_imbalance_60s": 0.22,
        "book_imbalance": 0.30,
        "momentum_15s": 0.0008,
        "spread_bps": 1.2,
    }
    value.update(changes)
    return value


class RealtimeDecisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = PredictionEngine(
            Settings(
                db_path=f"{self.directory.name}/test.sqlite3",
                prediction_entry_probability=0.64,
                prediction_decision_min_ev=0.01,
                prediction_observation_seconds=30,
                prediction_max_spread_bps=4,
            )
        )
        self.round = {
            "round_id": "BTCUSDT-0",
            "start_time": 0,
            "end_time": 300_000,
            "p_up": 0.72,
            "baseline_p_up": 0.72,
            "up_odds": 1.9,
            "down_odds": 1.9,
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_observation_window_waits(self):
        decision = self.engine.realtime_decision(
            self.round, snapshot(), now_ms=10_000
        )
        self.assertEqual(decision["action"], "WAIT")

    def test_stale_data_does_not_trade(self):
        decision = self.engine.realtime_decision(
            self.round, snapshot(data_age_ms=10_000), now_ms=60_000
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("过期", decision["reason"])

    def test_wide_spread_does_not_trade(self):
        decision = self.engine.realtime_decision(
            self.round, snapshot(spread_bps=8), now_ms=60_000
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("价差", decision["reason"])

    def test_aligned_edge_enters_up(self):
        decision = self.engine.realtime_decision(
            self.round, snapshot(), now_ms=60_000
        )
        self.assertEqual(decision["action"], "ENTER_UP")
        self.assertEqual(decision["direction"], "UP")
        self.assertGreater(decision["expected_value"], 0.01)

    def test_last_seconds_block_new_entry(self):
        decision = self.engine.realtime_decision(
            self.round, snapshot(), now_ms=275_000
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertEqual(decision["quality"], "late_round")

    def test_position_changes_to_hold_or_close(self):
        position = {"direction": "UP"}
        self.round["decision"] = self.engine.realtime_decision(
            self.round, snapshot(), now_ms=60_000
        )
        self.assertEqual(
            self.engine._position_decision(self.round, position)["action"], "HOLD"
        )
        self.round["p_up"] = 0.40
        self.round["decision"] = self.engine.realtime_decision(
            self.round,
            snapshot(
                trade_imbalance_15s=-0.35,
                trade_imbalance_60s=-0.22,
                book_imbalance=-0.30,
                momentum_15s=-0.0008,
            ),
            now_ms=60_000,
            baseline_p_up=0.40,
        )
        self.assertEqual(
            self.engine._position_decision(self.round, position)["action"], "CLOSE"
        )


if __name__ == "__main__":
    unittest.main()
