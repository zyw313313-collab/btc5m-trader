import unittest

from btc5m.config import Settings
from btc5m.costs import CostModel
from btc5m.exchange import kline_event_to_bar
from btc5m.trader import SpotTrader


class TradingTests(unittest.TestCase):
    def test_cost_model_is_worse_than_raw_return(self):
        costs = CostModel(fee_bps=10, slippage_bps=5)
        self.assertLess(costs.long_return(100, 101), 0.01)

    def test_paper_position_cap(self):
        settings = Settings(
            live_trading=False,
            max_quote_per_trade=50,
            max_position_quote=50,
            min_quote_per_trade=5,
            paper_quote_balance=100,
        )
        trader = SpotTrader(settings)
        first = trader.execute("BTCUSDT", 0.8, 100)
        second = trader.execute("BTCUSDT", 0.8, 100)
        self.assertEqual(first["decision"], "BUY")
        self.assertTrue(first["paper_order"])
        self.assertEqual(second["reason"], "paper_max_position_reached")

    def test_paper_trade_applies_slippage(self):
        settings = Settings(
            live_trading=False,
            max_quote_per_trade=50,
            max_position_quote=50,
            min_quote_per_trade=5,
            paper_quote_balance=100,
            fee_bps=10,
            slippage_bps=5,
        )
        trader = SpotTrader(settings)
        result = trader.execute("BTCUSDT", 0.8, 100)
        self.assertAlmostEqual(result["paper_order"]["fill_price"], 100.05)
        self.assertLess(result["paper_order"]["paper_base"], 0.5)

    def test_kline_parser_only_accepts_closed_candle(self):
        payload = {
            "e": "kline",
            "k": {
                "t": 1000,
                "T": 299999,
                "o": "100",
                "h": "101",
                "l": "99",
                "c": "100.5",
                "v": "12",
                "q": "1200",
                "n": 7,
                "x": True,
            },
        }
        bar = kline_event_to_bar(payload)
        self.assertEqual(bar["open_time"], 1000)
        self.assertEqual(bar["trades"], 7)
        payload["k"]["x"] = False
        self.assertIsNone(kline_event_to_bar(payload))


if __name__ == "__main__":
    unittest.main()
