from dataclasses import dataclass
import time


ROUND_MS = 5 * 60 * 1000


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def round_window(now_ms: int | None = None) -> tuple[int, int]:
    now_ms = now_ms or int(time.time() * 1000)
    start = (now_ms // ROUND_MS) * ROUND_MS
    return start, start + ROUND_MS


@dataclass(frozen=True)
class MarketQuote:
    up_odds: float
    down_odds: float
    up_pool: float
    down_pool: float
    up_implied: float
    down_implied: float


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    suggested_stake: float


def quote_from_probability(
    p_up: float,
    margin: float = 0.04,
    pool_size: float = 100_000.0,
    market_probability: float | None = None,
) -> MarketQuote:
    """Create transparent paper-market odds from model probability.

    This is deliberately not presented as Binance's live order book. It gives
    the paper account realistic spread/margin and liquidity values until a
    supported prediction-market execution adapter is configured.
    """
    p_up = clamp(float(p_up), 0.02, 0.98)
    fair_up = clamp(
        p_up if market_probability is None else float(market_probability),
        0.02,
        0.98,
    )
    fair_down = 1.0 - fair_up
    total = 1.0 + max(0.0, margin)
    implied_up = fair_up * total
    implied_down = fair_down * total
    return MarketQuote(
        up_odds=round(1.0 / implied_up, 4),
        down_odds=round(1.0 / implied_down, 4),
        up_pool=round(pool_size * fair_up, 2),
        down_pool=round(pool_size * fair_down, 2),
        up_implied=implied_up,
        down_implied=implied_down,
    )


def expected_value(probability: float, odds: float, fee_rate: float) -> float:
    """Expected net return per unit stake, including settlement fee."""
    return float(probability) * float(odds) * (1.0 - fee_rate) - 1.0


def kelly_fraction(probability: float, odds: float) -> float:
    """Full Kelly for a binary contract quoted as decimal gross odds."""
    b = float(odds) - 1.0
    if b <= 0:
        return 0.0
    return clamp((b * probability - (1.0 - probability)) / b, 0.0, 1.0)


def trade_risk(
    *,
    now_ms: int,
    end_ms: int,
    direction: str,
    p_up: float,
    odds: float,
    quote_balance: float,
    equity: float,
    active_stake: float,
    daily_trades: int,
    daily_loss: float,
    loss_streak: int,
    settings,
) -> RiskDecision:
    direction = direction.upper()
    probability = p_up if direction == "UP" else 1.0 - p_up
    seconds_left = max(0, (end_ms - now_ms) // 1000)
    if direction not in {"UP", "DOWN"}:
        return RiskDecision(False, "invalid_direction", 0.0)
    if settings.prediction_mode != "paper":
        return RiskDecision(False, "live_prediction_adapter_not_configured", 0.0)
    if seconds_left <= settings.prediction_no_trade_last_seconds:
        return RiskDecision(False, "last_seconds_protection", 0.0)
    if daily_trades >= settings.prediction_max_daily_trades:
        return RiskDecision(False, "daily_trade_limit", 0.0)
    if daily_loss >= settings.prediction_daily_loss_limit:
        return RiskDecision(False, "daily_loss_limit", 0.0)
    if loss_streak >= settings.prediction_max_loss_streak:
        return RiskDecision(False, "loss_streak_circuit_breaker", 0.0)
    if probability < settings.prediction_min_probability:
        return RiskDecision(False, "probability_below_threshold", 0.0)
    if odds < settings.prediction_min_odds:
        return RiskDecision(False, "odds_below_threshold", 0.0)
    ev = expected_value(probability, odds, settings.prediction_fee_bps / 10_000)
    if ev <= 0:
        return RiskDecision(False, "negative_expected_value_after_fee", 0.0)
    kelly = kelly_fraction(probability, odds)
    suggested = min(
        settings.prediction_max_stake,
        quote_balance,
        max(0.0, equity * kelly * 0.25),
        max(0.0, settings.prediction_max_stake - active_stake),
    )
    if suggested < settings.prediction_min_stake:
        return RiskDecision(False, "stake_below_minimum_or_balance", 0.0)
    return RiskDecision(True, "edge_and_risk_checks_passed", round(suggested, 2))


def position_mark(
    stake: float, entry_odds: float, current_odds: float, fee_rate: float
) -> dict:
    """Approximate early-close value for a paper prediction position."""
    stake = float(stake)
    entry_odds = max(0.01, float(entry_odds))
    current_odds = max(0.01, float(current_odds))
    value = stake * current_odds / entry_odds * (1.0 - fee_rate)
    return {
        "value": value,
        "pnl": value - stake,
        "return_pct": value / stake - 1.0 if stake else 0.0,
    }
