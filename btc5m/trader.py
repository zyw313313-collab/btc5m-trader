from dataclasses import dataclass
import time

from .binance import BinanceSpotClient, format_quantity
from .costs import CostModel


@dataclass
class TradeDecision:
    action: str
    reason: str
    p_up: float


class SpotTrader:
    """Spot-only executor. Down signals reduce BTC; they do not open shorts."""

    def __init__(self, settings, store=None):
        self.settings = settings
        self.store = store
        self.client = None
        paper = store.paper_account() if store else None
        self.paper_quote = paper["quote"] if paper else settings.paper_quote_balance
        self.paper_base = paper["base"] if paper else 0.0
        self.account_source = "none"
        self.account_testnet = settings.testnet
        self._account_cache = None
        self._account_cache_at = 0.0
        if settings.api_key and settings.api_secret:
            self.connect_account(
                settings.api_key,
                settings.api_secret,
                settings.testnet,
                source="environment",
            )
        self.rules = None
        self.costs = CostModel(settings.fee_bps, settings.slippage_bps)

    @property
    def connected(self) -> bool:
        return self.client is not None

    def account_snapshot(self) -> dict:
        if not self.client:
            return {"connected": False, "source": self.account_source}
        if self._account_cache and time.time() - self._account_cache_at < 5:
            return self._account_cache
        account = self.client.account()
        balances = {
            item["asset"]: {
                "free": float(item["free"]),
                "locked": float(item["locked"]),
            }
            for item in account.get("balances", [])
            if float(item["free"]) or float(item["locked"])
        }
        self._account_cache = {
            "connected": True,
            "source": self.account_source,
            "testnet": self.account_testnet,
            "can_trade": account.get("canTrade"),
            "balances": balances,
        }
        self._account_cache_at = time.time()
        return self._account_cache

    def connect_account(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool,
        source: str = "dashboard",
    ):
        if not api_key or not api_secret:
            raise ValueError("API key and secret are required")
        account_url = (
            "https://testnet.binance.vision"
            if testnet
            else "https://api.binance.com"
        )
        if testnet == self.settings.testnet and self.settings.account_base_url:
            account_url = self.settings.account_base_url
        if self.settings.use_ccxt:
            from .ccxt_adapter import CcxtSpotClient

            client = CcxtSpotClient(
                account_url, api_key, api_secret, testnet
            )
        else:
            client = BinanceSpotClient(account_url, api_key, api_secret)
        self.client = client
        self.account_source = source
        self.account_testnet = testnet
        self._account_cache = None
        self._account_cache_at = 0.0
        self.rules = None

    def disconnect_account(self):
        self.client = None
        self.account_source = "none"
        self._account_cache = None
        self._account_cache_at = 0.0
        self.rules = None

    def decision(self, p_up: float) -> TradeDecision:
        threshold = self.settings.trade_threshold
        if p_up >= threshold:
            return TradeDecision("BUY", "probability_above_threshold", p_up)
        if p_up <= 1 - threshold:
            return TradeDecision("SELL", "probability_below_threshold", p_up)
        return TradeDecision("HOLD", "inside_no_trade_band", p_up)

    def execute(self, symbol: str, p_up: float, price: float) -> dict:
        decision = self.decision(p_up)
        result = {
            "mode": "live" if self.settings.live_trading else "paper",
            "decision": decision.action,
            "reason": decision.reason,
            "p_up": p_up,
            "price": price,
            "executed": False,
        }
        if decision.action == "HOLD":
            return result
        if not self.settings.live_trading:
            position_value = self.paper_base * price
            if decision.action == "BUY":
                available = max(0.0, self.settings.max_position_quote - position_value)
                quote_amount = min(
                    self.settings.max_quote_per_trade,
                    self.paper_quote,
                    available,
                )
                if quote_amount < self.settings.min_quote_per_trade:
                    result["reason"] = "paper_max_position_reached"
                    return result
                fill_price = self.costs.buy_fill(price)
                fee = quote_amount * self.costs.fee_rate
                quantity = (quote_amount - fee) / fill_price
                self.paper_quote -= quote_amount
                self.paper_base += quantity
                if self.store:
                    self.store.save_paper_account(self.paper_quote, self.paper_base)
            else:
                quantity = self.paper_base
                fill_price = self.costs.sell_fill(price)
                quote_amount = quantity * fill_price * (1 - self.costs.fee_rate)
                self.paper_quote += quote_amount
                self.paper_base = 0.0
                if self.store:
                    self.store.save_paper_account(self.paper_quote, self.paper_base)
            result["paper_order"] = {
                "symbol": symbol,
                "side": decision.action,
                "quote_amount": quote_amount,
                "quantity": quantity,
                "fill_price": fill_price,
                "paper_quote": self.paper_quote,
                "paper_base": self.paper_base,
            }
            result["executed"] = True
            if self.store:
                self.store.record_order(
                    {
                        "created_at": int(time.time() * 1000),
                        "mode": "paper",
                        "symbol": symbol,
                        "side": decision.action,
                        "decision": decision.action,
                        "p_up": p_up,
                        "price": fill_price,
                        "quote_amount": quote_amount,
                        "quantity": quantity,
                        "status": "FILLED",
                        "raw": result["paper_order"],
                    }
                )
                self.store.record_equity(
                    "paper", self.paper_quote, self.paper_base, price
                )
            return result
        if self.settings.live_confirmation != "I_UNDERSTAND_REAL_ORDERS":
            raise RuntimeError(
                "Live orders require BTC_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_ORDERS"
            )
        if not self.client:
            raise RuntimeError("Trading enabled but Binance API credentials are missing")
        account = self.account_snapshot()
        if account.get("can_trade") is not True:
            raise RuntimeError("Binance account does not have trading permission")
        if not self.rules:
            self.rules = self.client.symbol_rules(symbol)
        if decision.action == "BUY":
            current_base = self.client.free_balance(symbol.removesuffix("USDT"))
            available = max(
                0.0, self.settings.max_position_quote - current_base * price
            )
            quote_amount = min(self.settings.max_quote_per_trade, available)
            if quote_amount < self.rules["min_notional"]:
                result["reason"] = "max_position_reached_or_below_minimum"
                return result
            response = self.client.new_market_order(
                symbol,
                "BUY",
                quote_order_qty=f"{quote_amount:.2f}",
            )
        else:
            base_asset = symbol.removesuffix("USDT")
            free_base = self.client.free_balance(base_asset)
            quantity = free_base * 0.995
            if quantity < self.rules["min_qty"] or quantity * price < self.rules["min_notional"]:
                result["reason"] = "position_below_exchange_minimum"
                return result
            response = self.client.new_market_order(
                symbol,
                "SELL",
                quantity=format_quantity(quantity, self.rules["step_size"]),
            )
        result["executed"] = True
        result["order"] = response
        if self.store:
            self.store.record_order(
                {
                    "created_at": int(time.time() * 1000),
                    "mode": "live",
                    "symbol": symbol,
                    "side": decision.action,
                    "decision": decision.action,
                    "p_up": p_up,
                    "price": price,
                    "quote_amount": quote_amount if decision.action == "BUY" else None,
                    "quantity": quantity if decision.action == "SELL" else None,
                    "status": response.get("status", "UNKNOWN"),
                    "exchange_order_id": str(response.get("orderId", response.get("id", ""))),
                    "raw": response,
                }
            )
        return result

    def mark_to_market(self, symbol: str, price: float) -> dict:
        """Persist a sanitized equity snapshot without storing credentials."""
        quote_asset = "USDT" if symbol.endswith("USDT") else symbol[-4:]
        base_asset = symbol[: -len(quote_asset)]
        if not self.client:
            snapshot = {
                "mode": "paper",
                "quote": self.paper_quote,
                "base": self.paper_base,
                "equity": self.paper_quote + self.paper_base * price,
            }
        else:
            account = self.account_snapshot()
            balances = account.get("balances", {})
            quote = balances.get(quote_asset, {}).get("free", 0.0) + balances.get(
                quote_asset, {}
            ).get("locked", 0.0)
            base = balances.get(base_asset, {}).get("free", 0.0) + balances.get(
                base_asset, {}
            ).get("locked", 0.0)
            snapshot = {
                "mode": "live",
                "quote": quote,
                "base": base,
                "equity": quote + base * price,
            }
        if self.store:
            self.store.record_equity(
                snapshot["mode"], snapshot["quote"], snapshot["base"], price
            )
        return snapshot
