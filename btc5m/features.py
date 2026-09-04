import math
from statistics import mean, pstdev


FEATURE_NAMES = [
    "ret_1",
    "ret_3",
    "ret_6",
    "ret_12",
    "range_pct",
    "body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "rsi_14",
    "ema_gap",
    "atr_pct",
    "volume_z",
    "hour_sin",
    "hour_cos",
]


def _returns(bars: list[dict], index: int, periods: int) -> float:
    if index < periods:
        return 0.0
    before = bars[index - periods]["close"]
    return bars[index]["close"] / before - 1.0 if before else 0.0


def _ema(values: list[float], period: int) -> float:
    alpha = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _rsi(bars: list[dict], index: int, period: int = 14) -> float:
    start = max(1, index - period + 1)
    gains = []
    losses = []
    for i in range(start, index + 1):
        change = bars[i]["close"] - bars[i - 1]["close"]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = mean(gains) if gains else 0.0
    average_loss = mean(losses) if losses else 0.0
    if average_loss == 0:
        return 1.0 if average_gain else 0.5
    return 1.0 - 1.0 / (1.0 + average_gain / average_loss)


def vector(bars: list[dict], index: int) -> list[float]:
    bar = bars[index]
    close = bar["close"] or 1.0
    values = [bars[i]["close"] for i in range(max(0, index - 40), index + 1)]
    volume_values = [bars[i]["volume"] for i in range(max(0, index - 20), index + 1)]
    true_ranges = []
    for i in range(max(0, index - 13), index + 1):
        previous_close = bars[i - 1]["close"] if i else bars[i]["open"]
        true_ranges.append(
            max(
                bars[i]["high"] - bars[i]["low"],
                abs(bars[i]["high"] - previous_close),
                abs(bars[i]["low"] - previous_close),
            )
        )
    volume_mean = mean(volume_values)
    volume_std = pstdev(volume_values) if len(volume_values) > 1 else 0.0
    volume_z = (bar["volume"] - volume_mean) / volume_std if volume_std else 0.0
    hour = (bar["open_time"] / 1000 / 3600) % 24
    return [
        _returns(bars, index, 1),
        _returns(bars, index, 3),
        _returns(bars, index, 6),
        _returns(bars, index, 12),
        (bar["high"] - bar["low"]) / close,
        (bar["close"] - bar["open"]) / close,
        (bar["high"] - max(bar["open"], bar["close"])) / close,
        (min(bar["open"], bar["close"]) - bar["low"]) / close,
        _rsi(bars, index),
        (_ema(values, 12) - _ema(values, 26)) / close,
        (sum(true_ranges) / len(true_ranges)) / close if true_ranges else 0.0,
        max(-4.0, min(4.0, volume_z)),
        math.sin(2 * math.pi * hour / 24),
        math.cos(2 * math.pi * hour / 24),
    ]


def can_compute(index: int) -> bool:
    return index >= 26
