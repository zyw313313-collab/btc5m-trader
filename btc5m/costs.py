from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    @property
    def fee_rate(self) -> float:
        return self.fee_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000

    def long_return(self, entry: float, exit: float) -> float:
        entry_fill = self.buy_fill(entry)
        exit_fill = self.sell_fill(exit)
        return exit_fill / entry_fill * (1 - self.fee_rate) ** 2 - 1

    def buy_fill(self, price: float) -> float:
        return price * (1 + self.slippage_rate)

    def sell_fill(self, price: float) -> float:
        return price * (1 - self.slippage_rate)
