import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def utc_now_ms() -> int:
    return int(time.time() * 1000)


def fetch_klines(
    base_url: str,
    symbol: str,
    interval: str,
    limit: int = 1000,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[dict]:
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    query = urlencode(params)
    request = Request(
        f"{base_url}/api/v3/klines?{query}",
        headers={"User-Agent": "btc5m-research/0.1"},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    now = utc_now_ms()
    rows = []
    for item in payload:
        close_time = int(item[6])
        if close_time >= now:
            continue
        rows.append(
            {
                "open_time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time": close_time,
                "quote_volume": float(item[7]),
                "trades": int(item[8]),
            }
        )
    return rows


def fetch_current_kline(
    base_url: str, symbol: str, interval: str
) -> dict | None:
    """Fetch the currently forming candle without dropping it."""
    params = urlencode({"symbol": symbol, "interval": interval, "limit": 1})
    request = Request(
        f"{base_url}/api/v3/klines?{params}",
        headers={"User-Agent": "btc5m-research/0.2"},
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload:
        return None
    item = payload[-1]
    return {
        "open_time": int(item[0]),
        "open": float(item[1]),
        "high": float(item[2]),
        "low": float(item[3]),
        "close": float(item[4]),
        "volume": float(item[5]),
        "close_time": int(item[6]),
        "quote_volume": float(item[7]),
        "trades": int(item[8]),
    }


def fetch_historical_klines(
    base_url: str, symbol: str, interval: str, total_limit: int
) -> list[dict]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval for pagination: {interval}")
    remaining = max(1, total_limit)
    cursor = max(0, utc_now_ms() - remaining * INTERVAL_MS[interval])
    rows = []
    while remaining:
        batch = fetch_klines(
            base_url,
            symbol,
            interval,
            min(1000, remaining),
            start_time=cursor,
        )
        if not batch:
            break
        rows.extend(batch)
        remaining = total_limit - len(rows)
        next_cursor = batch[-1]["open_time"] + INTERVAL_MS[interval]
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < min(1000, remaining + len(batch)):
            break
        time.sleep(0.15)
    unique = {row["open_time"]: row for row in rows}
    return [unique[key] for key in sorted(unique)][-total_limit:]


def format_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def kline_event_to_bar(payload: dict) -> dict | None:
    """Convert a Binance kline event into the local bar format."""
    event = payload.get("data", payload)
    kline = event.get("k")
    if not kline or not kline.get("x"):
        return None
    return {
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
