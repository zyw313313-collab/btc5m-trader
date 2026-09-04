import math
import threading
import time
from collections import deque


def _now_ms() -> int:
    return int(time.time() * 1000)


class RealtimeMarketState:
    """Thread-safe rolling state for Binance trade, book and 1s kline data."""

    def __init__(self, max_trade_age_ms: int = 120_000, max_bars: int = 180):
        self.max_trade_age_ms = max_trade_age_ms
        self.max_bars = max_bars
        self._lock = threading.RLock()
        self._trades = deque()
        self._bars_1s = deque(maxlen=max_bars)
        self._current_bar = None
        self._last_price = None
        self._last_event_ms = None
        self._book = None

    def update_agg_trade(self, payload: dict):
        event = payload.get("data", payload)
        price = event.get("p")
        quantity = event.get("q")
        if price is None or quantity is None:
            return
        timestamp = int(event.get("T") or event.get("E") or _now_ms())
        quote = float(price) * float(quantity)
        # Binance m=true means the buyer was the maker, so the taker sold.
        buy = not bool(event.get("m", False))
        with self._lock:
            self._trades.append((timestamp, quote if buy else 0.0, quote if not buy else 0.0, float(price)))
            self._last_price = float(price)
            self._last_event_ms = timestamp
            self._prune(timestamp)

    def update_book_ticker(self, payload: dict):
        event = payload.get("data", payload)
        bid = event.get("b")
        ask = event.get("a")
        bid_qty = event.get("B")
        ask_qty = event.get("A")
        if None in (bid, ask, bid_qty, ask_qty):
            return
        timestamp = int(event.get("E") or _now_ms())
        with self._lock:
            self._book = {
                "bid": float(bid),
                "ask": float(ask),
                "bid_qty": float(bid_qty),
                "ask_qty": float(ask_qty),
                "updated_at": timestamp,
            }
            self._last_price = (float(bid) + float(ask)) / 2.0
            self._last_event_ms = timestamp

    def update_kline(self, payload: dict):
        event = payload.get("data", payload)
        kline = event.get("k")
        if not kline:
            return
        interval = str(kline.get("i", ""))
        if interval not in {"1s", "1000ms"}:
            return
        bar = {
            "open_time": int(kline["t"]),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
            "close_time": int(kline["T"]),
            "quote_volume": float(kline["q"]),
            "trades": int(kline["n"]),
        }
        with self._lock:
            if self._bars_1s and self._bars_1s[-1]["open_time"] == bar["open_time"]:
                self._bars_1s[-1] = bar
            else:
                self._bars_1s.append(bar)
            self._current_bar = bar if not bool(kline.get("x")) else None
            self._last_price = bar["close"]
            self._last_event_ms = int(event.get("E") or _now_ms())

    def update(self, payload: dict):
        event = payload.get("data", payload)
        stream = str(payload.get("stream", "")).lower()
        event_type = str(event.get("e", "")).lower()
        if "aggtrade" in stream or event_type == "aggtrade":
            self.update_agg_trade(payload)
        elif "bookticker" in stream or event_type == "bookticker":
            self.update_book_ticker(payload)
        elif "kline" in stream or event_type == "kline":
            self.update_kline(payload)

    def _prune(self, now_ms: int):
        cutoff = now_ms - self.max_trade_age_ms
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    @staticmethod
    def _imbalance(buy: float, sell: float) -> float:
        total = buy + sell
        return (buy - sell) / total if total else 0.0

    def snapshot(self, now_ms: int | None = None) -> dict:
        now_ms = now_ms or _now_ms()
        with self._lock:
            self._prune(now_ms)
            trades_15 = [item for item in self._trades if item[0] >= now_ms - 15_000]
            trades_60 = [item for item in self._trades if item[0] >= now_ms - 60_000]

            def totals(items):
                buy = sum(item[1] for item in items)
                sell = sum(item[2] for item in items)
                return buy, sell

            buy_15, sell_15 = totals(trades_15)
            buy_60, sell_60 = totals(trades_60)
            book = self._book or {}
            bid_qty = float(book.get("bid_qty", 0.0))
            ask_qty = float(book.get("ask_qty", 0.0))
            book_total = bid_qty + ask_qty
            book_imbalance = (
                (bid_qty - ask_qty) / book_total if book_total else 0.0
            )
            bid = book.get("bid")
            ask = book.get("ask")
            mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
            spread_bps = (
                (ask - bid) / mid * 10_000
                if mid and bid is not None and ask is not None
                else None
            )
            prices_15 = [item[3] for item in trades_15]
            momentum_15 = (
                prices_15[-1] / prices_15[0] - 1.0
                if len(prices_15) >= 2 and prices_15[0]
                else 0.0
            )
            age = (
                max(0, now_ms - int(self._last_event_ms))
                if self._last_event_ms is not None
                else None
            )
            bars = list(self._bars_1s)
            if self._current_bar and (not bars or bars[-1]["open_time"] != self._current_bar["open_time"]):
                bars.append(self._current_bar)
            return {
                "last_price": self._last_price,
                "data_age_ms": age,
                "data_ready": len(trades_15) >= 5 and age is not None and age <= 3_000,
                "trade_count_15s": len(trades_15),
                "trade_count_60s": len(trades_60),
                "buy_quote_15s": buy_15,
                "sell_quote_15s": sell_15,
                "buy_quote_60s": buy_60,
                "sell_quote_60s": sell_60,
                "trade_imbalance_15s": self._imbalance(buy_15, sell_15),
                "trade_imbalance_60s": self._imbalance(buy_60, sell_60),
                "book_imbalance": book_imbalance,
                "bid": bid,
                "ask": ask,
                "spread_bps": spread_bps,
                "momentum_15s": momentum_15,
                "bars_1s": bars[-self.max_bars :],
            }


def sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def logit(probability: float) -> float:
    probability = max(0.001, min(0.999, float(probability)))
    return math.log(probability / (1.0 - probability))
