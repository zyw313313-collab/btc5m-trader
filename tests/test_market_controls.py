import tempfile
import unittest

from btc5m.config import Settings
from btc5m.engine import PredictionEngine
from btc5m.grid_strategy import build_grid_plan
from btc5m.market_analysis import analyze_pressure


def market_snapshot(**changes):
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


def bars(count=12, trend=0.0):
    result = []
    price = 100.0
    for index in range(count):
        close = price * (1.0 + trend)
        result.append(
            {
                "open_time": index * 300_000,
                "open": price,
                "high": max(price, close) + 0.1,
                "low": min(price, close) - 0.1,
                "close": close,
            }
        )
        price = close
    return result


class MarketControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(
            db_path=f"{self.directory.name}/test.sqlite3",
            prediction_entry_probability=0.64,
            prediction_decision_min_ev=0.01,
            prediction_observation_seconds=30,
            prediction_max_spread_bps=4,
            grid_enabled=True,
            grid_range_window=10,
        )
        self.engine = PredictionEngine(self.settings)
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

    def test_neutral_probability_does_not_trade(self):
        round_data = dict(self.round, p_up=0.52, entry_p_up=0.52)
        decision = self.engine.realtime_decision(
            round_data, market_snapshot(), now_ms=60_000
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("neutral_probability_zone", decision["reasons"])

    def test_sell_pressure_blocks_up_entry(self):
        decision = self.engine.realtime_decision(
            self.round,
            market_snapshot(
                trade_imbalance_15s=-0.35,
                trade_imbalance_60s=-0.22,
                book_imbalance=-0.30,
                momentum_15s=-0.0008,
            ),
            now_ms=60_000,
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("pressure_does_not_confirm_model", decision["reasons"])

    def test_trade_and_book_conflict_blocks_entry(self):
        decision = self.engine.realtime_decision(
            self.round,
            market_snapshot(
                trade_imbalance_15s=0.35,
                trade_imbalance_60s=0.22,
                book_imbalance=-0.35,
                momentum_15s=0.0008,
            ),
            now_ms=60_000,
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("trade_book_pressure_conflict", decision["reasons"])

    def test_opposite_close_forecast_blocks_entry(self):
        round_data = dict(
            self.round,
            close_forecast={"p_up": 0.40},
        )
        decision = self.engine.realtime_decision(
            round_data, market_snapshot(), now_ms=60_000
        )
        self.assertEqual(decision["action"], "NO_TRADE")
        self.assertIn("entry_and_close_forecast_conflict", decision["reasons"])

    def test_grid_is_enabled_in_range(self):
        plan = build_grid_plan(
            current_price=100.0,
            bars=bars(),
            snapshot=market_snapshot(
                trade_imbalance_15s=0.01,
                trade_imbalance_60s=0.01,
                book_imbalance=0.01,
                momentum_15s=0.0,
            ),
            settings=self.settings,
            seconds_left=180,
        )
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["regime"], "RANGE")
        self.assertTrue(plan["buy_levels"])
        self.assertTrue(plan["sell_levels"])

    def test_grid_pauses_on_strong_trend(self):
        trend_bars = bars(trend=0.01)
        plan = build_grid_plan(
            current_price=trend_bars[-1]["close"],
            bars=trend_bars,
            snapshot=market_snapshot(),
            settings=self.settings,
            seconds_left=180,
        )
        self.assertFalse(plan["enabled"])
        self.assertIn("recent_trend_too_strong", plan["reasons"])

    def test_grid_pauses_on_stale_data(self):
        plan = build_grid_plan(
            current_price=100.0,
            bars=bars(),
            snapshot=market_snapshot(data_age_ms=10_000),
            settings=self.settings,
            seconds_left=180,
        )
        self.assertFalse(plan["enabled"])
        self.assertIn("realtime_data_not_ready_or_stale", plan["reasons"])

    def test_pressure_reports_sell_direction(self):
        pressure = analyze_pressure(
            market_snapshot(
                trade_imbalance_15s=-0.35,
                trade_imbalance_60s=-0.22,
                book_imbalance=-0.30,
                momentum_15s=-0.0008,
            )
        )
        self.assertEqual(pressure["direction"], "DOWN")
        self.assertEqual(pressure["divergence"], "CONFIRMED_SELL")


if __name__ == "__main__":
    unittest.main()
