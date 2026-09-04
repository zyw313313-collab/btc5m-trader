class CcxtSpotClient:
    """Optional CCXT adapter with the same small interface as BinanceSpotClient."""

    def __init__(self, base_url: str, api_key: str, api_secret: str, testnet: bool):
        try:
            import ccxt
        except ImportError as error:
            raise RuntimeError(
                "BTC_USE_CCXT=true requires: pip install -r requirements-ccxt.txt"
            ) from error
        self.ccxt = ccxt
        self.exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )
        if base_url:
            self.exchange.urls["api"] = {
                "public": f"{base_url.rstrip('/')}/api/v3",
                "private": f"{base_url.rstrip('/')}/api/v3",
            }
        if testnet:
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()

    @staticmethod
    def symbol(symbol: str) -> str:
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]}/USDT"
        return symbol

    def account(self) -> dict:
        balance = self.exchange.fetch_balance()
        balances = []
        for asset, free in balance.get("free", {}).items():
            used = float(balance.get("used", {}).get(asset, 0) or 0)
            free = float(free or 0)
            if free or used:
                balances.append({"asset": asset, "free": str(free), "locked": str(used)})
        return {"canTrade": True, "balances": balances}

    def exchange_info(self, symbol: str) -> dict:
        return self.exchange.market(self.symbol(symbol))

    def ticker_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(self.symbol(symbol))["last"])

    def free_balance(self, asset: str) -> float:
        return float(self.exchange.fetch_balance()["free"].get(asset, 0) or 0)

    def symbol_rules(self, symbol: str) -> dict:
        market = self.exchange.market(self.symbol(symbol))
        filters = {
            item.get("filterType"): item
            for item in market.get("info", {}).get("filters", [])
        }
        market_lot = filters.get("MARKET_LOT_SIZE") or {}
        lot_size = filters.get("LOT_SIZE") or {}
        step_size = float(
            market_lot.get("stepSize") or lot_size.get("stepSize") or 0
        )
        if not step_size:
            precision = market.get("precision", {}).get("amount")
            if precision is None:
                step_size = 0.000001
            elif self.exchange.precisionMode == self.ccxt.TICK_SIZE:
                step_size = float(precision)
            else:
                step_size = 10 ** (-int(precision))
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}

        def first_positive(*values):
            for value in values:
                number = float(value or 0)
                if number > 0:
                    return number
            return 0.0

        return {
            "step_size": step_size,
            "min_qty": first_positive(
                market_lot.get("minQty"),
                lot_size.get("minQty"),
                market.get("limits", {}).get("amount", {}).get("min"),
            ),
            "min_notional": first_positive(
                notional.get("minNotional"),
                market.get("limits", {}).get("cost", {}).get("min"),
            ),
        }

    def new_market_order(
        self,
        symbol: str,
        side: str,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        test: bool = False,
    ) -> dict:
        del test
        ccxt_symbol = self.symbol(symbol)
        amount = float(quantity) if quantity else 0.0
        params = {}
        if quote_order_qty:
            params["quoteOrderQty"] = float(quote_order_qty)
            amount = float(quote_order_qty) / self.ticker_price(symbol)
        order = self.exchange.create_order(
            ccxt_symbol, "market", side.lower(), amount, None, params
        )
        return order
