from __future__ import annotations

from .microstructure import sigmoid


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _side(value: float, threshold: float) -> str:
    if value >= threshold:
        return "UP"
    if value <= -threshold:
        return "DOWN"
    return "NONE"


def analyze_pressure(snapshot: dict) -> dict:
    """Summarize aggressive flow, top-of-book pressure and divergence.

    The result is deliberately descriptive. It is not a claim that order-book
    imbalance is a calibrated probability of the five-minute close.
    """
    trade_15 = float(snapshot.get("trade_imbalance_15s") or 0.0)
    trade_60 = float(snapshot.get("trade_imbalance_60s") or 0.0)
    book = float(snapshot.get("book_imbalance") or 0.0)
    momentum = float(snapshot.get("momentum_15s") or 0.0)
    momentum_score = _clamp(momentum / 0.001)
    score = _clamp(
        0.45 * trade_15 + 0.25 * trade_60 + 0.20 * book + 0.10 * momentum_score
    )
    direction = "UP" if score >= 0.12 else "DOWN" if score <= -0.12 else "NEUTRAL"
    strength = (
        "STRONG_BUY"
        if score >= 0.35
        else "BUY"
        if score >= 0.12
        else "STRONG_SELL"
        if score <= -0.35
        else "SELL"
        if score <= -0.12
        else "NEUTRAL"
    )
    price_direction = _side(momentum, 0.0001)
    trade_direction = _side(trade_15, 0.08)
    book_direction = _side(book, 0.08)
    conflict = (
        trade_direction != "NONE"
        and book_direction != "NONE"
        and trade_direction != book_direction
    )
    divergence = "NONE"
    if price_direction == "UP" and direction == "DOWN":
        divergence = "UP_EXHAUSTION"
    elif price_direction == "DOWN" and direction == "UP":
        divergence = "DOWN_EXHAUSTION"
    elif price_direction == "UP" and direction == "UP":
        divergence = "CONFIRMED_BUY"
    elif price_direction == "DOWN" and direction == "DOWN":
        divergence = "CONFIRMED_SELL"

    # This is an interpretable pressure score, not a settlement probability.
    pressure_probability = sigmoid(score * 2.2)
    return {
        "direction": direction,
        "strength": strength,
        "score": round(score, 6),
        "pressure_probability": round(pressure_probability, 6),
        "trade_direction": trade_direction,
        "book_direction": book_direction,
        "price_direction": price_direction,
        "conflict": conflict,
        "divergence": divergence,
        "buy_quote_15s": float(snapshot.get("buy_quote_15s") or 0.0),
        "sell_quote_15s": float(snapshot.get("sell_quote_15s") or 0.0),
        "buy_quote_60s": float(snapshot.get("buy_quote_60s") or 0.0),
        "sell_quote_60s": float(snapshot.get("sell_quote_60s") or 0.0),
        "trade_imbalance_15s": trade_15,
        "trade_imbalance_60s": trade_60,
        "book_imbalance": book,
        "momentum_15s": momentum,
    }


def rolling_up_rate(bars: list[dict], window: int = 96) -> float:
    """Return the recent up-close prior without looking into the future."""
    if len(bars) < 2:
        return 0.5
    sample = bars[-(window + 1) :]
    outcomes = [
        1.0 if sample[index + 1]["close"] > sample[index]["close"] else 0.0
        for index in range(len(sample) - 1)
    ]
    return sum(outcomes) / len(outcomes) if outcomes else 0.5
