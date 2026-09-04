import unittest

from btc5m.features import FEATURE_NAMES, can_compute, vector


def make_bars(count=40):
    bars = []
    for i in range(count):
        close = 100 + i * 0.2
        bars.append(
            {
                "open_time": i * 300000,
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 10 + (i % 4),
                "close_time": i * 300000 + 299999,
                "quote_volume": 1000,
                "trades": 10,
            }
        )
    return bars


class FeatureTests(unittest.TestCase):
    def test_vector_shape_and_finiteness(self):
        values = vector(make_bars(), 30)
        self.assertEqual(len(values), len(FEATURE_NAMES))
        self.assertTrue(all(value == value for value in values))

    def test_warmup(self):
        self.assertFalse(can_compute(25))
        self.assertTrue(can_compute(26))


if __name__ == "__main__":
    unittest.main()
