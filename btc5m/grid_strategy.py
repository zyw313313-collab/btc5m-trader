from __future__ import annotations

from .market_analysis import analyze_pressure


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _recent_range(bars: list[dict], window: int) -> tuple[float, float, float]:
    sample = bars[-window:] if bars else []
    if not sample:
        return 0.0, 0.0, 0.0
    high = max(float(item["high"]) for item in sample)
    low = min(float(item["low"]) for item in sample)
    atr = sum(float(item["high"]) - float(item["low"]) for item in sample) / len(sample)
    return low, high, atr


def build_grid_plan(
    *,
    current_price: float,
    bars: list[dict],
    snapshot: dict,
    settings,
    seconds_left: int | None = None,
) -> dict:
    """Build a spot-grid plan; it never submits exchange orders."""
    current_price = float(current_price or 0.0)
    pressure = analyze_pressure(snapshot)
    reasons: list[str] = []
    if current_price <= 0:
        reasons.append("invalid_price")
    if (
        not snapshot.get("data_ready")
        or snapshot.get("data_age_ms") is None
        or float(snapshot.get("data_age_ms") or 0.0)
        > settings.prediction_realtime_stale_ms
    ):
        reasons.append("realtime_data_not_ready_or_stale")
    if snapshot.get("spread_bps") is not None and (
        float(snapshot["spread_bps"]) > settings.prediction_max_spread_bps
    ):
        reasons.append("spread_too_wide")
    if seconds_left is not None and seconds_left <= settings.grid_no_trade_last_seconds:
        reasons.append("round_near_close")
    if pressure["conflict"]:
        reasons.append("trade_and_book_pressure_conflict")
    if pressure["strength"] in {"STRONG_BUY", "STRONG_SELL"}:
        reasons.append("strong_trend_pressure")

    low, high, atr = _recent_range(bars, settings.grid_range_window)
    close_start = float(bars[-settings.grid_range_window]["close"]) if len(bars) >= settings.grid_range_window else current_price
    close_end = float(bars[-1]["close"]) if bars else current_price
    trend_return = close_end / close_start - 1.0 if close_start else 0.0
    if abs(trend_return) >= settings.grid_trend_return_filter:
        reasons.append("recent_trend_too_strong")

    range_pct = (high - low) / current_price if current_price and high >= low else 0.0
    spacing_pct = max(
        settings.grid_spacing_pct,
        settings.grid_min_spacing_pct,
        2.0 * (settings.fee_bps + settings.slippage_bps) / 10_000,
        (atr / current_price) * 0.75 if current_price else 0.0,
    )
    spacing_pct = _clamp(spacing_pct, settings.grid_min_spacing_pct, settings.grid_max_spacing_pct)
    half_width = max(
        spacing_pct * settings.grid_levels,
        range_pct * settings.grid_range_fraction,
        (atr / current_price) * 2.0 if current_price else 0.0,
    )
    lower_bound = current_price * (1.0 - half_width)
    upper_bound = current_price * (1.0 + half_width)
    levels = [
        round(current_price * (1.0 + spacing_pct * offset), 2)
        for offset in range(-settings.grid_levels, settings.grid_levels + 1)
    ]
    buy_levels = [level for level in levels if level < current_price]
    sell_levels = [level for level in levels if level > current_price]
    enabled = bool(settings.grid_enabled and not reasons and len(bars) >= settings.grid_range_window)
    return {
        "enabled": enabled,
        "paper_only": True,
        "regime": "RANGE" if not reasons else "PAUSED",
        "center_price": round(current_price, 2),
        "lower_bound": round(lower_bound, 2),
        "upper_bound": round(upper_bound, 2),
        "spacing_pct": round(spacing_pct, 6),
        "levels": levels,
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "range_pct": round(range_pct, 6),
        "trend_return": round(trend_return, 6),
        "pressure_filter": pressure["strength"],
        "reason": "grid_ready" if enabled else ",".join(reasons) or "grid_disabled",
        "reasons": reasons,
        "max_quote": settings.grid_max_quote,
    }
