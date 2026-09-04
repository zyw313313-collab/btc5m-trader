import tempfile
import unittest
from unittest.mock import patch

from btc5m.config import Settings
from btc5m.engine import PredictionEngine
from btc5m.prediction_market import (
    expected_value,
    kelly_fraction,
    quote_from_probability,
    trade_risk,
)
from btc5m.storage import Store


class PredictionMarketTests(unittest.TestCase):
    def test_quote_has_two_sides_and_paper_margin(self):
        quote = quote_from_probability(
            0.7, margin=0.04, market_probability=0.55
        )
        self.assertGreater(quote.up_odds, 1.0)
        self.assertGreater(quote.down_odds, 1.0)
        self.assertAlmostEqual(quote.up_pool + quote.down_pool, 100_000, places=2)
        self.assertLess(quote.up_implied + quote.down_implied, 1.1)

    def test_positive_edge_produces_fractional_kelly(self):
        self.assertGreater(expected_value(0.7, 1.8, 0.002), 0)
        self.assertGreater(kelly_fraction(0.7, 1.8), 0)

    def test_prediction_account_and_position_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"{directory}/test.sqlite3", 100)
            position_id = store.add_prediction_position(
                {
                    "round_id": "BTCUSDT-1",
                    "direction": "UP",
                    "stake": 10,
                    "entry_odds": 1.8,
                    "opened_at": 1,
                }
            )
            self.assertEqual(position_id, 1)
            self.assertEqual(len(store.active_prediction_positions()), 1)
            store.save_prediction_account(90, 0)
            self.assertEqual(store.prediction_account()["quote"], 90)

    def test_round_position_history_survives_close(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"{directory}/test.sqlite3", 100)
            position_id = store.add_prediction_position(
                {
                    "round_id": "BTCUSDT-2",
                    "direction": "UP",
                    "stake": 10,
                    "entry_odds": 1.8,
                    "opened_at": 1,
                }
            )
            store.close_prediction_position(
                position_id,
                "closed",
                2,
                1.9,
                0.5,
                0.02,
            )
            positions = store.prediction_positions_for_round("BTCUSDT-2")
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["status"], "closed")

    def test_auto_trade_does_not_reopen_a_closed_round(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                prediction_mode="paper",
                prediction_min_probability=0.6,
                prediction_min_odds=1.5,
                prediction_min_stake=5,
                prediction_max_stake=50,
            )
            engine = PredictionEngine(settings)
            round_data = {
                "round_id": "BTCUSDT-3",
                "start_time": 0,
                "end_time": 10**15,
                "lock_price": 100,
                "current_price": 101,
                "p_up": 0.8,
                "up_odds": 1.8,
                "down_odds": 2.0,
            }
            position_id = engine.store.add_prediction_position(
                {
                    "round_id": round_data["round_id"],
                    "direction": "UP",
                    "stake": 10,
                    "entry_odds": 1.8,
                    "opened_at": 1,
                }
            )
            engine.store.close_prediction_position(
                position_id, "closed", 2, 1.7, -1.0, 0.02
            )
            engine.prediction_controls["auto_trading"] = True
            engine._maybe_auto_trade(round_data)
            self.assertEqual(
                len(engine.store.prediction_positions_for_round(round_data["round_id"])),
                1,
            )

    def test_take_profit_and_probability_flip_close_active_position(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                prediction_mode="paper",
                prediction_fee_bps=20,
                prediction_slippage_bps=10,
                prediction_take_profit_pct=0.50,
            )
            engine = PredictionEngine(settings)
            position_id = engine.store.add_prediction_position(
                {
                    "round_id": "BTCUSDT-4",
                    "direction": "UP",
                    "stake": 10,
                    "entry_odds": 1.5,
                    "opened_at": 1,
                }
            )
            engine.store.save_prediction_account(90, 0)
            round_data = {
                "round_id": "BTCUSDT-4",
                "end_time": 100_000,
                "p_up": 0.4,
                "up_odds": 2.4,
                "down_odds": 1.5,
            }
            with patch("btc5m.engine.utc_now_ms", return_value=1_000):
                engine._manage_prediction_positions(round_data)
            position = next(
                item
                for item in engine.store.prediction_positions_for_round("BTCUSDT-4")
                if item["id"] == position_id
            )
            self.assertEqual(position["status"], "closed")
            self.assertGreater(position["pnl"], 0)

    def test_stop_loss_closes_active_position(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                db_path=f"{directory}/test.sqlite3",
                prediction_mode="paper",
                prediction_stop_loss_pct=0.30,
            )
            engine = PredictionEngine(settings)
            position_id = engine.store.add_prediction_position(
                {
                    "round_id": "BTCUSDT-5",
                    "direction": "DOWN",
                    "stake": 10,
                    "entry_odds": 1.8,
                    "opened_at": 1,
                }
            )
            engine.store.save_prediction_account(90, 0)
            round_data = {
                "round_id": "BTCUSDT-5",
                "end_time": 100_000,
                "p_up": 0.2,
                "up_odds": 2.4,
                "down_odds": 1.0,
            }
            with patch("btc5m.engine.utc_now_ms", return_value=1_000):
                engine._manage_prediction_positions(round_data)
            position = next(
                item
                for item in engine.store.prediction_positions_for_round("BTCUSDT-5")
                if item["id"] == position_id
            )
            self.assertEqual(position["status"], "closed")
            self.assertLess(position["pnl"], 0)

    def test_last_seconds_risk_gate(self):
        settings = Settings(
            prediction_mode="paper",
            prediction_min_probability=0.6,
            prediction_min_odds=1.5,
            prediction_min_stake=5,
            prediction_max_stake=50,
            prediction_no_trade_last_seconds=10,
        )
        decision = trade_risk(
            now_ms=1000,
            end_ms=10_000,
            direction="UP",
            p_up=0.8,
            odds=1.8,
            quote_balance=100,
            equity=100,
            active_stake=0,
            daily_trades=0,
            daily_loss=0,
            loss_streak=0,
            settings=settings,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "last_seconds_protection")


if __name__ == "__main__":
    unittest.main()
