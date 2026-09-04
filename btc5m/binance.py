import hashlib
import hmac
import json
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BinanceSpotClient:
    """Minimal signed Binance Spot REST client; secrets never leave this process."""

    def __init__(self, base_url: str, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret

    def _request(self, method: str, path: str, params=None, signed: bool = False):
        payload = dict(params or {})
        if signed:
            payload["timestamp"] = int(time.time() * 1000)
            payload["recvWindow"] = 5000
        encoded = urlencode(payload)
        if signed:
            signature = hmac.new(
                self.api_secret.encode(), encoded.encode(), hashlib.sha256
            ).hexdigest()
            encoded = f"{encoded}&signature={signature}"
        url = f"{self.base_url}{path}"
        if method == "GET" and encoded:
            url = f"{url}?{encoded}"
            data = None
        else:
            data = encoded.encode()
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "btc5m-research/0.2",
            },
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def account(self) -> dict:
        return self._request("GET", "/api/v3/account", signed=True)

    def commission(self, symbol: str) -> dict:
        return self._request(
            "GET", "/api/v3/account/commission", {"symbol": symbol}, signed=True
        )

    def exchange_info(self, symbol: str) -> dict:
        return self._request(
            "GET", "/api/v3/exchangeInfo", {"symbol": symbol}, signed=False
        )

    def ticker_price(self, symbol: str) -> float:
        data = self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    def new_market_order(
        self,
        symbol: str,
        side: str,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        test: bool = False,
    ) -> dict:
        params = {"symbol": symbol, "side": side.upper(), "type": "MARKET"}
        if quantity:
            params["quantity"] = quantity
        if quote_order_qty:
            params["quoteOrderQty"] = quote_order_qty
        path = "/api/v3/order/test" if test else "/api/v3/order"
        return self._request("POST", path, params, signed=True)

    def free_balance(self, asset: str) -> float:
        for balance in self.account().get("balances", []):
            if balance["asset"] == asset:
                return float(balance["free"])
        return 0.0

    def symbol_rules(self, symbol: str) -> dict:
        info = self.exchange_info(symbol)
        symbol_info = info["symbols"][0]
        rules = {item["filterType"]: item for item in symbol_info["filters"]}
        return {
            "step_size": float(rules.get("LOT_SIZE", {}).get("stepSize", "0.000001")),
            "min_qty": float(rules.get("LOT_SIZE", {}).get("minQty", "0")),
            "min_notional": float(
                rules.get("MIN_NOTIONAL", rules.get("NOTIONAL", {})).get(
                    "minNotional", "0"
                )
            ),
        }


def format_quantity(quantity: float, step_size: float) -> str:
    step = Decimal(str(step_size))
    value = Decimal(str(quantity)).quantize(step, rounding=ROUND_DOWN)
    return format(value, "f")
