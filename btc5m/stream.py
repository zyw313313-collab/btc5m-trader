import asyncio
import json
from collections.abc import AsyncIterator

from .exchange import kline_event_to_bar


class BinanceKlineStream:
    """Reconnectable stream of closed Binance candles."""

    def __init__(
        self,
        ws_url: str,
        symbol: str,
        interval: str,
        reconnect_seconds: int = 5,
    ):
        self.ws_url = ws_url.rstrip("/")
        self.symbol = symbol.lower()
        self.interval = interval
        self.reconnect_seconds = max(1, reconnect_seconds)
        self.last_open_time = None

    def _url(self) -> str:
        return f"{self.ws_url}/{self.symbol}@kline_{self.interval}"

    async def closed_bars(self) -> AsyncIterator[dict]:
        try:
            import aiohttp
        except ImportError as error:
            raise RuntimeError(
                "BTC_WEBSOCKET=true requires: pip install -r requirements.txt"
            ) from error

        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=45)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(
                        self._url(), heartbeat=20, autoping=True
                    ) as connection:
                        async for message in connection:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                bar = kline_event_to_bar(json.loads(message.data))
                                if bar and bar["open_time"] != self.last_open_time:
                                    self.last_open_time = bar["open_time"]
                                    yield bar
                            elif message.type in {
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.ERROR,
                            }:
                                raise ConnectionError("Binance websocket closed")
            except Exception as error:
                print(f"websocket disconnected: {error}")
                await asyncio.sleep(self.reconnect_seconds)


class BinanceRealtimeStream:
    """Reconnectable Binance combined stream for microstructure data."""

    def __init__(
        self,
        ws_url: str,
        symbol: str,
        reconnect_seconds: int = 5,
    ):
        self.ws_url = ws_url.rstrip("/")
        self.symbol = symbol.lower()
        self.reconnect_seconds = max(1, reconnect_seconds)

    def _url(self) -> str:
        base = self.ws_url
        if base.endswith("/ws"):
            base = base[:-3] + "/stream"
        streams = "/".join(
            [
                f"{self.symbol}@aggTrade",
                f"{self.symbol}@bookTicker",
                f"{self.symbol}@kline_1s",
                f"{self.symbol}@kline_5m",
            ]
        )
        return f"{base}?streams={streams}"

    async def events(self) -> AsyncIterator[dict]:
        try:
            import aiohttp
        except ImportError as error:
            raise RuntimeError(
                "BTC_WEBSOCKET=true requires: pip install -r requirements.txt"
            ) from error

        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=45)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(
                        self._url(), heartbeat=20, autoping=True
                    ) as connection:
                        async for message in connection:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                if payload.get("data"):
                                    yield payload
                            elif message.type in {
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.ERROR,
                            }:
                                raise ConnectionError("Binance realtime websocket closed")
            except Exception as error:
                print(f"realtime websocket disconnected: {error}")
                await asyncio.sleep(self.reconnect_seconds)
