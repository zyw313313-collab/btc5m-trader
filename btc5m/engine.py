import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .costs import CostModel
from .deep_model import DeepModelManager
from .exchange import (
    fetch_current_kline,
    fetch_historical_klines,
    fetch_klines,
    utc_now_ms,
)
from .features import can_compute, vector
from .grid_strategy import build_grid_plan
from .market_analysis import analyze_pressure, rolling_up_rate
from .model import OnlineLogistic
from .microstructure import RealtimeMarketState, logit, sigmoid
from .prediction_market import (
    expected_value,
    kelly_fraction,
    position_mark,
    quote_from_probability,
    round_window,
    trade_risk,
)
from .storage import Store
from .stream import BinanceKlineStream, BinanceRealtimeStream
from .trader import SpotTrader


@dataclass
class BacktestResult:
    samples: int
    accuracy: float | None
    active_signals: int
    strategy_return: float
    buy_and_hold_return: float
    fee_bps: float
    slippage_bps: float


class PredictionEngine:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.db_path, settings.paper_quote_balance)
        state = self.store.load_model()
        self.model = OnlineLogistic(14) if not state else OnlineLogistic.from_state(state)
        self.deep_model = DeepModelManager(settings)
        self.trader = SpotTrader(settings, self.store)
        self.costs = CostModel(settings.fee_bps, settings.slippage_bps)
        self.realtime = RealtimeMarketState(
            max_trade_age_ms=max(60_000, settings.prediction_realtime_stale_ms * 20)
        )
        self._engine_lock = threading.RLock()
        self.prediction_controls = {
            "auto_trading": settings.prediction_auto_trading,
            "paused": False,
            "emergency_stop": False,
        }
        self.prediction_state = {
            "error": None,
            "round": None,
            "positions": [],
            "account": self.store.prediction_account(),
        }

    def _combine_realtime_probability(
        self,
        baseline_p_up: float,
        snapshot: dict,
        deep_probability: float | None = None,
        deep_approved: bool = False,
    ) -> float:
        """Blend the candle model with short-lived order-flow evidence.

        This is a decision overlay, not a calibrated probability model. It is
        intentionally capped so noisy microstructure data cannot dominate the
        trained 5-minute baseline.
        """
        model_probability = float(baseline_p_up)
        if (
            self.settings.prediction_deep_enabled
            and self.settings.prediction_deep_use_for_decision
            and deep_approved
            and deep_probability is not None
        ):
            # Keep the established online model dominant until the deep model
            # has passed a separate walk-forward review.
            model_probability = 0.65 * model_probability + 0.35 * float(deep_probability)
        if not snapshot.get("data_ready"):
            return model_probability
        momentum = max(-0.003, min(0.003, float(snapshot.get("momentum_15s") or 0.0)))
        adjustment = (
            0.55 * float(snapshot.get("trade_imbalance_15s") or 0.0)
            + 0.30 * float(snapshot.get("trade_imbalance_60s") or 0.0)
            + 0.25 * float(snapshot.get("book_imbalance") or 0.0)
            + 0.10 * (momentum / 0.001)
        )
        return sigmoid(logit(model_probability) + max(-1.25, min(1.25, adjustment)))

    def _close_probability(
        self,
        *,
        baseline_p_up: float,
        pressure_probability: float,
        current_price: float,
        lock_price: float,
        seconds_left: int,
        deep_probability: float | None = None,
        deep_approved: bool = False,
    ) -> float:
        """Estimate the five-minute settlement direction.

        A short-lived order-flow burst is useful for entry timing, but it is
        not enough to determine whether the close will finish above the round
        open. The round displacement is therefore an independent input and
        is given more weight as settlement approaches.
        """
        if lock_price <= 0 or current_price <= 0:
            displacement_probability = 0.5
        else:
            displacement = current_price / lock_price - 1.0
            # A 0.10% move is already meaningful on a five-minute horizon.
            displacement_probability = sigmoid(displacement / 0.0008)

        time_left_ratio = max(0.0, min(1.0, seconds_left / 300.0))
        displacement_weight = 0.28 + 0.12 * (1.0 - time_left_ratio)
        baseline_weight = 0.47 - 0.08 * (1.0 - time_left_ratio)
        pressure_weight = 1.0 - baseline_weight - displacement_weight
        values = [
            baseline_weight * float(baseline_p_up),
            pressure_weight * float(pressure_probability),
            displacement_weight * displacement_probability,
        ]
        weights = [baseline_weight, pressure_weight, displacement_weight]
        if (
            self.settings.prediction_deep_enabled
            and self.settings.prediction_deep_use_for_decision
            and deep_approved
            and deep_probability is not None
        ):
            # Keep the deep model a small reference component even after
            # approval; it must not erase the current-round price evidence.
            values.append(0.10 * float(deep_probability))
            weights = [weight * 0.90 for weight in weights] + [0.10]
        probability = sum(values) / sum(weights)
        return max(0.02, min(0.98, probability))

    def realtime_decision(
        self,
        round_data: dict,
        snapshot: dict | None = None,
        now_ms: int | None = None,
        baseline_p_up: float | None = None,
        deep_probability: float | None = None,
        deep_status: dict | None = None,
        deep_approved: bool = False,
    ) -> dict:
        """Return an explicit action for the current five-minute round."""
        now_ms = now_ms or utc_now_ms()
        snapshot = snapshot or self.realtime.snapshot(now_ms)
        baseline = float(
            baseline_p_up
            if baseline_p_up is not None
            else round_data.get("baseline_p_up", round_data.get("p_up", 0.5))
        )
        combined = float(round_data.get("p_up", baseline))
        deep_status = deep_status or {}
        deep_calibration = deep_status.get("calibration_status", "not_available")
        deep_version = deep_status.get("model_version", "not_available")
        deep_samples = int(deep_status.get("training_samples", 0) or 0)
        deep_used_for_decision = bool(
            self.settings.prediction_deep_enabled
            and self.settings.prediction_deep_use_for_decision
            and deep_approved
            and deep_probability is not None
        )
        model_agreement = "unavailable"
        if deep_probability is not None:
            model_agreement = (
                "agree"
                if (baseline >= 0.5) == (float(deep_probability) >= 0.5)
                else "disagree"
            )
        elapsed = max(0, (now_ms - int(round_data["start_time"])) // 1000)
        seconds_left = max(0, (int(round_data["end_time"]) - now_ms) // 1000)
        spread = snapshot.get("spread_bps")
        stale = snapshot.get("data_age_ms")
        reasons = []

        if elapsed < self.settings.prediction_observation_seconds:
            return {
                "action": "WAIT",
                "direction": "NONE",
                "combined_probability": combined,
                "baseline_probability": baseline,
                "deep_probability": deep_probability,
                "calibrated_probability": deep_probability,
                "ensemble_probability": combined,
                "model_agreement": model_agreement,
                "deep_used_for_decision": deep_used_for_decision,
                "model_version": deep_version,
                "training_samples": deep_samples,
                "calibration_status": deep_calibration,
                "confidence": abs(combined - 0.5) * 2.0,
                "quality": "warming_up",
                "reason": "先观察本周期前30秒，不追开盘噪声",
                "reasons": ["observation_window"],
                "seconds_into_round": elapsed,
                "seconds_left": seconds_left,
                "data_ready": bool(snapshot.get("data_ready")),
                "data_age_ms": stale,
                "spread_bps": spread,
                "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
                "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
                "book_imbalance": snapshot.get("book_imbalance", 0.0),
                "momentum_15s": snapshot.get("momentum_15s", 0.0),
            }
        if seconds_left <= max(
            self.settings.prediction_no_trade_last_seconds, 30
        ):
            return {
                "action": "NO_TRADE",
                "direction": "NONE",
                "combined_probability": combined,
                "baseline_probability": baseline,
                "deep_probability": deep_probability,
                "calibrated_probability": deep_probability,
                "ensemble_probability": combined,
                "model_agreement": model_agreement,
                "deep_used_for_decision": deep_used_for_decision,
                "model_version": deep_version,
                "training_samples": deep_samples,
                "calibration_status": deep_calibration,
                "confidence": abs(combined - 0.5) * 2.0,
                "quality": "late_round",
                "reason": "临近结算，禁止新开仓，等待结算或管理已有仓位",
                "reasons": ["late_round_entry_block"],
                "seconds_into_round": elapsed,
                "seconds_left": seconds_left,
                "data_ready": bool(snapshot.get("data_ready")),
                "data_age_ms": stale,
                "spread_bps": spread,
                "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
                "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
                "book_imbalance": snapshot.get("book_imbalance", 0.0),
                "momentum_15s": snapshot.get("momentum_15s", 0.0),
            }
        if (
            not snapshot.get("data_ready")
            or stale is None
            or stale > self.settings.prediction_realtime_stale_ms
            or snapshot.get("trade_count_15s", 0)
            < self.settings.prediction_min_realtime_trades
        ):
            reasons.append("实时成交数据不足或已过期")
        if spread is not None and spread > self.settings.prediction_max_spread_bps:
            reasons.append("买卖价差过大")
        if reasons:
            return {
                "action": "NO_TRADE",
                "direction": "NONE",
                "combined_probability": combined,
                "baseline_probability": baseline,
                "deep_probability": deep_probability,
                "calibrated_probability": deep_probability,
                "ensemble_probability": combined,
                "model_agreement": model_agreement,
                "deep_used_for_decision": deep_used_for_decision,
                "model_version": deep_version,
                "training_samples": deep_samples,
                "calibration_status": deep_calibration,
                "confidence": abs(combined - 0.5) * 2.0,
                "quality": "degraded",
                "reason": "；".join(reasons),
                "reasons": reasons,
                "seconds_into_round": elapsed,
                "seconds_left": seconds_left,
                "data_ready": bool(snapshot.get("data_ready")),
                "data_age_ms": stale,
                "spread_bps": spread,
                "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
                "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
                "book_imbalance": snapshot.get("book_imbalance", 0.0),
                "momentum_15s": snapshot.get("momentum_15s", 0.0),
            }

        direction = "UP" if combined >= 0.5 else "DOWN"
        direction_probability = combined if direction == "UP" else 1.0 - combined
        votes = {
            "model": "UP" if baseline >= 0.5 else "DOWN",
            "trade": (
                "UP"
                if snapshot.get("trade_imbalance_15s", 0.0)
                >= self.settings.prediction_signal_min_imbalance
                else "DOWN"
                if snapshot.get("trade_imbalance_15s", 0.0)
                <= -self.settings.prediction_signal_min_imbalance
                else "NONE"
            ),
            "book": (
                "UP"
                if snapshot.get("book_imbalance", 0.0)
                >= self.settings.prediction_signal_min_imbalance
                else "DOWN"
                if snapshot.get("book_imbalance", 0.0)
                <= -self.settings.prediction_signal_min_imbalance
                else "NONE"
            ),
            "momentum": (
                "UP"
                if snapshot.get("momentum_15s", 0.0)
                >= self.settings.prediction_signal_min_momentum
                else "DOWN"
                if snapshot.get("momentum_15s", 0.0)
                <= -self.settings.prediction_signal_min_momentum
                else "NONE"
            ),
        }
        if deep_used_for_decision:
            votes["deep"] = (
                "UP" if deep_probability >= 0.5 else "DOWN"
            )
        agreement = sum(value == direction for value in votes.values())
        odds = round_data["up_odds"] if direction == "UP" else round_data["down_odds"]
        effective_odds = odds * (1 - self.settings.prediction_slippage_bps / 10_000)
        ev = expected_value(
            direction_probability,
            effective_odds,
            self.settings.prediction_fee_bps / 10_000,
        )
        if (
            direction_probability < self.settings.prediction_entry_probability
            or agreement < 2
            or ev < self.settings.prediction_decision_min_ev
        ):
            return {
                "action": "NO_TRADE",
                "direction": "NONE",
                "combined_probability": combined,
                "baseline_probability": baseline,
                "deep_probability": deep_probability,
                "calibrated_probability": deep_probability,
                "ensemble_probability": combined,
                "model_agreement": model_agreement,
                "deep_used_for_decision": deep_used_for_decision,
                "model_version": deep_version,
                "training_samples": deep_samples,
                "calibration_status": deep_calibration,
                "confidence": abs(combined - 0.5) * 2.0,
                "quality": "no_edge",
                "reason": "优势不足：概率、订单流、盘口未形成足够一致，或成本后期望值不足",
                "reasons": [
                    f"probability={direction_probability:.3f}",
                    f"agreement={agreement}/4",
                    f"ev={ev:.4f}",
                ],
                "seconds_into_round": elapsed,
                "seconds_left": seconds_left,
                "data_ready": True,
                "data_age_ms": stale,
                "spread_bps": spread,
                "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
                "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
                "book_imbalance": snapshot.get("book_imbalance", 0.0),
                "momentum_15s": snapshot.get("momentum_15s", 0.0),
                "votes": votes,
                "agreement": agreement,
                "expected_value": ev,
            }
        return {
            "action": "ENTER_UP" if direction == "UP" else "ENTER_DOWN",
            "direction": direction,
            "combined_probability": combined,
            "baseline_probability": baseline,
            "deep_probability": deep_probability,
            "calibrated_probability": deep_probability,
            "ensemble_probability": combined,
            "model_agreement": model_agreement,
            "deep_used_for_decision": deep_used_for_decision,
            "model_version": deep_version,
            "training_samples": deep_samples,
            "calibration_status": deep_calibration,
            "confidence": abs(combined - 0.5) * 2.0,
            "quality": "actionable",
            "reason": f"{direction}：概率、实时压力至少两项一致，成本后期望值为正",
            "reasons": [f"{name}={value}" for name, value in votes.items() if value == direction],
            "seconds_into_round": elapsed,
            "seconds_left": seconds_left,
            "data_ready": True,
            "data_age_ms": stale,
            "spread_bps": spread,
            "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
            "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
            "book_imbalance": snapshot.get("book_imbalance", 0.0),
            "momentum_15s": snapshot.get("momentum_15s", 0.0),
            "votes": votes,
            "agreement": agreement,
            "expected_value": ev,
        }

    # The definition below intentionally supersedes the legacy decision method
    # above while keeping the old implementation available for comparison.
    def realtime_decision(
        self,
        round_data: dict,
        snapshot: dict | None = None,
        now_ms: int | None = None,
        baseline_p_up: float | None = None,
        deep_probability: float | None = None,
        deep_status: dict | None = None,
        deep_approved: bool = False,
    ) -> dict:
        """Return a strict entry signal plus an independent close forecast."""
        now_ms = now_ms or utc_now_ms()
        snapshot = snapshot or self.realtime.snapshot(now_ms)
        pressure = round_data.get("pressure") or analyze_pressure(snapshot)
        baseline = float(
            baseline_p_up
            if baseline_p_up is not None
            else round_data.get(
                "calibrated_baseline_p_up",
                round_data.get("baseline_p_up", 0.5),
            )
        )
        combined = float(round_data.get("entry_p_up", round_data.get("p_up", baseline)))
        close_forecast = round_data.get("close_forecast") or {}
        close_probability = float(close_forecast.get("p_up", combined))
        close_direction = (
            "UP"
            if close_probability > self.settings.prediction_neutral_upper
            else "DOWN"
            if close_probability < self.settings.prediction_neutral_lower
            else "NEUTRAL"
        )
        deep_status = deep_status or {}
        deep_used = bool(
            self.settings.prediction_deep_enabled
            and self.settings.prediction_deep_use_for_decision
            and deep_approved
            and deep_probability is not None
        )
        model_agreement = "unavailable"
        if deep_probability is not None:
            model_agreement = (
                "agree"
                if (baseline >= 0.5) == (float(deep_probability) >= 0.5)
                else "disagree"
            )
        elapsed = max(0, (now_ms - int(round_data["start_time"])) // 1000)
        seconds_left = max(0, (int(round_data["end_time"]) - now_ms) // 1000)
        stale = snapshot.get("data_age_ms")
        spread = snapshot.get("spread_bps")

        def result(action: str, quality: str, reason: str, reasons: list[str], **extra):
            payload = {
                "action": action,
                "direction": extra.pop("direction", "NONE"),
                "combined_probability": combined,
                "entry_probability": combined,
                "close_probability": close_probability,
                "close_direction": close_direction,
                "baseline_probability": baseline,
                "deep_probability": deep_probability,
                "calibrated_probability": deep_probability,
                "ensemble_probability": close_probability,
                "model_agreement": model_agreement,
                "deep_used_for_decision": deep_used,
                "model_version": deep_status.get("model_version", "not_available"),
                "training_samples": int(deep_status.get("training_samples", 0) or 0),
                "calibration_status": deep_status.get("calibration_status", "not_available"),
                "confidence": abs(close_probability - 0.5) * 2.0,
                "quality": quality,
                "reason": reason,
                "reasons": reasons,
                "seconds_into_round": elapsed,
                "seconds_left": seconds_left,
                "data_ready": bool(snapshot.get("data_ready")),
                "data_age_ms": stale,
                "spread_bps": spread,
                "pressure": pressure,
                "pressure_direction": pressure["direction"],
                "pressure_strength": pressure["strength"],
                "pressure_score": pressure["score"],
                "trade_imbalance_15s": snapshot.get("trade_imbalance_15s", 0.0),
                "trade_imbalance_60s": snapshot.get("trade_imbalance_60s", 0.0),
                "book_imbalance": snapshot.get("book_imbalance", 0.0),
                "momentum_15s": snapshot.get("momentum_15s", 0.0),
            }
            payload.update(extra)
            return payload

        if elapsed < self.settings.prediction_observation_seconds:
            return result(
                "WAIT",
                "warming_up",
                "observe the first part of the round",
                ["observation_window"],
            )
        if seconds_left <= max(self.settings.prediction_no_trade_last_seconds, 30):
            return result(
                "NO_TRADE",
                "late_round",
                "new entries are blocked near settlement",
                ["late_round_entry_block"],
            )

        gate_reasons = []
        if (
            not snapshot.get("data_ready")
            or stale is None
            or stale > self.settings.prediction_realtime_stale_ms
        ):
            gate_reasons.append("realtime_data_not_ready_or_stale (过期)")
        if snapshot.get("trade_count_15s", 0) < self.settings.prediction_min_realtime_trades:
            gate_reasons.append("too_few_recent_trades")
        if spread is not None and spread > self.settings.prediction_max_spread_bps:
            gate_reasons.append("spread_too_wide (价差)")
        if gate_reasons:
            return result(
                "NO_TRADE",
                "degraded",
                "market data quality gate failed: " + ", ".join(gate_reasons),
                gate_reasons,
            )

        if self.settings.prediction_neutral_lower <= combined <= self.settings.prediction_neutral_upper:
            return result(
                "NO_TRADE",
                "neutral",
                "entry probability is inside the neutral zone",
                ["neutral_probability_zone"],
            )

        direction = "UP" if combined > 0.5 else "DOWN"
        direction_probability = combined if direction == "UP" else 1.0 - combined
        votes = {
            "model": "UP" if baseline > 0.5 else "DOWN",
            "pressure": pressure["direction"],
            "trade": pressure["trade_direction"],
            "book": pressure["book_direction"],
            "momentum": pressure["price_direction"],
        }
        if deep_used:
            votes["deep"] = "UP" if float(deep_probability) > 0.5 else "DOWN"
        agreement = sum(value == direction for value in votes.values())
        market_votes = sum(
            value == direction
            for name, value in votes.items()
            if name != "model" and value != "NONE"
        )
        odds = round_data["up_odds"] if direction == "UP" else round_data["down_odds"]
        effective_odds = odds * (1 - self.settings.prediction_slippage_bps / 10_000)
        ev = expected_value(
            direction_probability,
            effective_odds,
            self.settings.prediction_fee_bps / 10_000,
        )
        rejection_reasons = []
        if direction_probability < self.settings.prediction_entry_probability:
            rejection_reasons.append("entry_probability_below_threshold")
        if abs(float(pressure["score"])) < self.settings.prediction_min_pressure_score:
            rejection_reasons.append("pressure_too_weak")
        if pressure["direction"] != direction:
            rejection_reasons.append("pressure_does_not_confirm_model")
        if self.settings.prediction_pressure_conflict_block and pressure["conflict"]:
            rejection_reasons.append("trade_book_pressure_conflict")
        if close_direction not in {"NEUTRAL", direction}:
            rejection_reasons.append("entry_and_close_forecast_conflict")
        if market_votes < 1 or agreement < 2:
            rejection_reasons.append("insufficient_model_market_agreement")
        if ev < self.settings.prediction_decision_min_ev:
            rejection_reasons.append("expected_value_after_cost_below_threshold")
        if rejection_reasons:
            return result(
                "NO_TRADE",
                "no_edge",
                "entry was rejected by probability, pressure or cost filters",
                rejection_reasons,
                votes=votes,
                agreement=agreement,
                market_votes=market_votes,
                expected_value=ev,
            )
        return result(
            "ENTER_UP" if direction == "UP" else "ENTER_DOWN",
            "actionable",
            "model edge confirmed by market pressure after costs",
            [f"{name}={value}" for name, value in votes.items() if value == direction],
            direction=direction,
            votes=votes,
            agreement=agreement,
            market_votes=market_votes,
            expected_value=ev,
        )

    def sync(self) -> list[dict]:
        rows = fetch_klines(
            self.settings.base_url,
            self.settings.symbol,
            self.settings.interval,
            self.settings.sync_limit,
        )
        self.store.upsert_bars(rows)
        return self.store.bars(self.settings.history_limit)

    def backfill(self, limit: int) -> int:
        rows = fetch_historical_klines(
            self.settings.base_url, self.settings.symbol, self.settings.interval, limit
        )
        self.store.upsert_bars(rows)
        return len(rows)

    def rebuild_model(self, bars: list[dict]) -> int:
        self.model = OnlineLogistic(14)
        for index in range(26, len(bars) - 1):
            self.model.update(
                vector(bars, index),
                int(bars[index + 1]["close"] > bars[index]["close"]),
            )
        self.store.save_model(self.model.state())
        return self.model.steps

    def train_deep_model(self, bars: list[dict]) -> dict:
        """Train the optional deep reference with chronological splits."""
        with self._engine_lock:
            return self.deep_model.train(bars)

    def bootstrap(self, bars: list[dict]):
        if self.model.steps:
            return
        for index in range(26, len(bars) - 1):
            self.model.update(vector(bars, index), int(bars[index + 1]["close"] > bars[index]["close"]))
        self.store.save_model(self.model.state())

    def settle(self, bars: list[dict]):
        by_open_time = {bar["open_time"]: bar for bar in bars}
        source_indexes = {bar["open_time"]: index for index, bar in enumerate(bars)}
        for prediction in self.store.unsettled_predictions():
            source_index = source_indexes.get(prediction["source_open_time"])
            source = bars[source_index] if source_index is not None else None
            target = by_open_time.get(prediction["target_open_time"])
            if not source or not target:
                continue
            actual_return = target["close"] / source["close"] - 1.0
            actual = int(actual_return > 0)
            self.store.settle_prediction(
                prediction["id"], actual, actual_return, utc_now_ms()
            )
            if can_compute(source_index):
                self.model.update(vector(bars, source_index), actual)

    def predict_latest(self, bars: list[dict]) -> dict | None:
        if len(bars) < 27:
            return None
        source_index = len(bars) - 1
        source = bars[source_index]
        target_open_time = source["open_time"] + (source["close_time"] - source["open_time"]) + 1
        probability = self.model.probability(vector(bars, source_index))
        is_new = self.store.add_prediction(
            source["open_time"], target_open_time, probability, utc_now_ms()
        )
        self.store.save_model(self.model.state())
        return {
            "source_open_time": source["open_time"],
            "target_open_time": target_open_time,
            "p_up": probability,
            "signal": "UP" if probability >= 0.5 else "DOWN",
            "close": source["close"],
            "is_new": is_new,
        }

    def run_once(self) -> dict:
        bars = self.sync()
        return self.process_bars(bars)

    def process_bars(self, bars: list[dict]) -> dict:
        self.bootstrap(bars)
        self.settle(bars)
        prediction = self.predict_latest(bars)
        execution = None
        if prediction and prediction["is_new"]:
            execution = self.trader.execute(
                self.settings.symbol, prediction["p_up"], prediction["close"]
            )
        mark_price = prediction["close"] if prediction else bars[-1]["close"]
        try:
            equity = self.trader.mark_to_market(self.settings.symbol, mark_price)
        except Exception as error:
            equity = {"error": str(error)}
        return {
            "prediction": prediction,
            "execution": execution,
            "equity": equity,
            "metrics": self.store.metrics(),
            "bars": len(bars),
        }

    def set_prediction_controls(self, payload: dict) -> dict:
        with self._engine_lock:
            for key in ("auto_trading", "paused", "emergency_stop"):
                if key in payload:
                    self.prediction_controls[key] = bool(payload[key])
            return dict(self.prediction_controls)

    @staticmethod
    def _day_start_ms(now_ms: int) -> int:
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        return int(start.timestamp() * 1000)

    def _settle_prediction_rounds(self, bars: list[dict], now_ms: int):
        by_open_time = {bar["open_time"]: bar for bar in bars}
        fee_rate = self.settings.prediction_fee_bps / 10_000
        for round_data in self.store.prediction_rounds(100):
            if round_data["close_price"] is not None:
                continue
            if round_data["end_time"] > now_ms:
                continue
            target = by_open_time.get(round_data["start_time"])
            if not target:
                continue
            close_price = float(target["close"])
            won_direction = "UP" if close_price > round_data["lock_price"] else "DOWN"
            for position in self.store.active_prediction_positions():
                if position["round_id"] != round_data["round_id"]:
                    continue
                won = position["direction"] == won_direction
                payout = (
                    position["stake"] * position["entry_odds"] * (1.0 - fee_rate)
                    if won
                    else 0.0
                )
                pnl = payout - position["stake"]
                self.store.close_prediction_position(
                    position["id"],
                    "settled",
                    now_ms,
                    position["entry_odds"],
                    pnl,
                    position["stake"] * fee_rate if won else 0.0,
                )
                account = self.store.prediction_account()
                self.store.save_prediction_account(
                    account["quote"] + payout,
                    account["realized_pnl"] + pnl,
                )
            updated = dict(round_data)
            updated.update(
                {
                    "close_price": close_price,
                    "status": "ended",
                    "updated_at": now_ms,
                }
            )
            self.store.upsert_prediction_round(updated)

    def refresh_prediction_market(self, bars: list[dict] | None = None) -> dict:
        with self._engine_lock:
            return self._refresh_prediction_market(bars)

    def _refresh_prediction_market(self, bars: list[dict] | None = None) -> dict:
        """Refresh the five-minute paper market from live Binance public data."""
        now_ms = utc_now_ms()
        bars = bars or self.store.bars(self.settings.history_limit)
        current = fetch_current_kline(
            self.settings.base_url, self.settings.symbol, self.settings.interval
        )
        if current:
            model_bars = list(bars)
            if model_bars and model_bars[-1]["open_time"] == current["open_time"]:
                model_bars[-1] = current
            elif not model_bars or model_bars[-1]["open_time"] < current["open_time"]:
                model_bars.append(current)
            current_price = current["close"]
            lock_price = current["open"]
        elif bars:
            model_bars = bars
            current_price = bars[-1]["close"]
            start, _ = round_window(now_ms)
            lock_price = (
                bars[-1]["open"]
                if bars[-1]["open_time"] == start
                else current_price
            )
        else:
            raise RuntimeError("no BTC market data available")

        self.bootstrap(model_bars)
        if len(model_bars) >= 27:
            raw_baseline_p_up = self.model.probability(
                vector(model_bars, len(model_bars) - 1)
            )
        else:
            raw_baseline_p_up = 0.5
        deep_reference = self.deep_model.reference(model_bars)
        realtime = self.realtime.snapshot(now_ms)
        pressure = analyze_pressure(realtime)
        recent_prior = rolling_up_rate(
            model_bars, self.settings.prediction_prior_window
        )
        # Shrink the online model toward the recent empirical base rate. This
        # prevents a positive learned intercept from turning every weak edge
        # into UP.
        baseline_p_up = max(
            0.02,
            min(0.98, 0.55 * raw_baseline_p_up + 0.45 * recent_prior),
        )
        if (
            realtime.get("last_price") is not None
            and realtime.get("data_age_ms") is not None
            and realtime["data_age_ms"] <= self.settings.prediction_realtime_stale_ms
        ):
            current_price = realtime["last_price"]
        start, end = round_window(now_ms)
        close_probability = self._close_probability(
            baseline_p_up=baseline_p_up,
            pressure_probability=pressure["pressure_probability"],
            current_price=current_price,
            lock_price=lock_price,
            seconds_left=max(0, (end - now_ms) // 1000),
            deep_probability=deep_reference.calibrated_probability,
            deep_approved=deep_reference.approved_for_decision,
        )
        p_up = self._combine_realtime_probability(
            baseline_p_up,
            realtime,
            deep_reference.calibrated_probability
            if deep_reference.available
            else None,
            deep_reference.approved_for_decision,
        )
        if current and current["open_time"] == start:
            lock_price = current["open"]
        quote = quote_from_probability(
            p_up,
            self.settings.prediction_market_margin,
            pool_size=max(10_000.0, self.store.prediction_account()["quote"] * 100),
            # Paper liquidity moves more slowly than the model, creating a
            # measurable edge/no-edge decision instead of circular odds.
            market_probability=0.5 + (p_up - 0.5) * 0.45,
        )
        grid = build_grid_plan(
            current_price=current_price,
            bars=model_bars,
            snapshot=realtime,
            settings=self.settings,
            seconds_left=max(0, (end - now_ms) // 1000),
        )
        round_data = {
            "round_id": f"BTCUSDT-{start}",
            "start_time": start,
            "end_time": end,
            "lock_price": float(lock_price),
            "current_price": float(current_price),
            "close_price": None,
            "status": "live" if now_ms < end else "settling",
            "p_up": float(p_up),
            "entry_p_up": float(p_up),
            "raw_baseline_p_up": float(raw_baseline_p_up),
            "baseline_p_up": float(baseline_p_up),
            "calibrated_baseline_p_up": float(baseline_p_up),
            "recent_up_rate": float(recent_prior),
            "deep_p_up": deep_reference.calibrated_probability,
            "deep_raw_p_up": deep_reference.raw_probability,
            "calibrated_p_up": deep_reference.calibrated_probability,
            "ensemble_p_up": float(close_probability),
            "realtime_p_up": float(p_up),
            "deep_model": deep_reference.as_dict(),
            "confidence": abs(float(close_probability) - 0.5) * 2.0,
            "pressure": pressure,
            "grid": grid,
            "close_forecast": {
                "direction": (
                    "UP"
                    if close_probability > self.settings.prediction_neutral_upper
                    else "DOWN"
                    if close_probability < self.settings.prediction_neutral_lower
                    else "NEUTRAL"
                ),
                "p_up": round(float(close_probability), 6),
                "confidence": round(abs(float(close_probability) - 0.5) * 2.0, 6),
                "seconds_left": max(0, (end - now_ms) // 1000),
                "price_change_pct": (
                    float(current_price) / float(lock_price) - 1.0
                    if lock_price
                    else 0.0
                ),
                "status": (
                    "edge"
                    if abs(close_probability - 0.5)
                    >= (self.settings.prediction_neutral_upper - 0.5)
                    else "weak_edge"
                ),
            },
            "up_odds": quote.up_odds,
            "down_odds": quote.down_odds,
            "up_pool": quote.up_pool,
            "down_pool": quote.down_pool,
            "up_ev": expected_value(
                p_up,
                quote.up_odds
                * (1 - self.settings.prediction_slippage_bps / 10_000),
                self.settings.prediction_fee_bps / 10_000,
            ),
            "down_ev": expected_value(
                1 - p_up,
                quote.down_odds
                * (1 - self.settings.prediction_slippage_bps / 10_000),
                self.settings.prediction_fee_bps / 10_000,
            ),
            "up_kelly": kelly_fraction(
                p_up,
                quote.up_odds
                * (1 - self.settings.prediction_slippage_bps / 10_000),
            ),
            "down_kelly": kelly_fraction(
                1 - p_up,
                quote.down_odds
                * (1 - self.settings.prediction_slippage_bps / 10_000),
            ),
            "updated_at": now_ms,
        }
        round_data["decision"] = self.realtime_decision(
            round_data,
            realtime,
            now_ms,
            baseline_p_up,
            deep_reference.calibrated_probability
            if deep_reference.available
            else None,
            deep_reference.as_dict(),
            deep_reference.approved_for_decision,
        )
        active_positions = [
            position
            for position in self.store.active_prediction_positions()
            if position["round_id"] == round_data["round_id"]
        ]
        if active_positions:
            round_data["decision"] = self._position_decision(
                round_data, active_positions[0]
            )
        self._settle_prediction_rounds(bars, now_ms)
        self.store.upsert_prediction_round(round_data)
        self.prediction_state = {
            "error": None,
            "round": round_data,
            "positions": self.prediction_positions(round_data),
            "account": self.store.prediction_account(),
            "realtime": realtime,
        }
        self._manage_prediction_positions(round_data)
        if self.prediction_controls["auto_trading"]:
            self._maybe_auto_trade(round_data)
        self.prediction_state["positions"] = self.prediction_positions(round_data)
        self.prediction_state["account"] = self.store.prediction_account()
        return self.prediction_state

    def _position_decision(self, round_data: dict, position: dict) -> dict:
        """Translate the round signal into a hold/close decision for a position."""
        decision = dict(round_data.get("decision") or {})
        p_up = float(decision.get("combined_probability", round_data["p_up"]))
        direction = position["direction"]
        aligned = (
            direction == "UP" and p_up >= 0.50
        ) or (direction == "DOWN" and p_up < 0.50)
        if not aligned and abs(p_up - 0.5) >= 0.04:
            decision.update(
                {
                    "action": "CLOSE",
                    "direction": direction,
                    "reason": "实时概率已明显反转，退出当前仓位",
                    "reasons": list(decision.get("reasons", []))
                    + ["probability_reversal"],
                }
            )
        else:
            decision.update(
                {
                    "action": "HOLD",
                    "direction": direction,
                    "reason": f"继续持有 {direction}，尚未出现明确反转",
                    "reasons": list(decision.get("reasons", []))
                    + ["position_aligned"],
                }
            )
        return decision

    def _position_decision(self, round_data: dict, position: dict) -> dict:
        """Use the close forecast for HOLD/CLOSE, not a raw 50% split."""
        decision = dict(round_data.get("decision") or {})
        p_up = float(
            decision.get(
                "close_probability",
                round_data.get("close_forecast", {}).get(
                    "p_up", round_data.get("p_up", 0.5)
                ),
            )
        )
        direction = position["direction"]
        reversed_signal = (
            direction == "UP"
            and p_up < self.settings.prediction_neutral_lower
        ) or (
            direction == "DOWN"
            and p_up > self.settings.prediction_neutral_upper
        )
        if reversed_signal:
            decision.update(
                {
                    "action": "CLOSE",
                    "direction": direction,
                    "reason": "close forecast clearly reversed",
                    "reasons": list(decision.get("reasons", []))
                    + ["close_forecast_reversal"],
                }
            )
        else:
            decision.update(
                {
                    "action": "HOLD",
                    "direction": direction,
                    "reason": (
                        f"hold {direction}; close forecast remains aligned or neutral"
                    ),
                    "reasons": list(decision.get("reasons", []))
                    + ["close_forecast_not_reversed"],
                }
            )
        return decision

    def prediction_positions(self, round_data: dict | None = None) -> list[dict]:
        fee_rate = self.settings.prediction_fee_bps / 10_000
        positions = self.store.active_prediction_positions()
        if not round_data:
            return positions
        for position in positions:
            if position["status"] != "active":
                continue
            current_odds = (
                round_data["up_odds"]
                if position["direction"] == "UP"
                else round_data["down_odds"]
            )
            position.update(
                position_mark(
                    position["stake"], position["entry_odds"], current_odds, fee_rate
                )
            )
            position["current_odds"] = current_odds
        return positions

    def _maybe_auto_trade(self, round_data: dict):
        # A closed automatic position must not be reopened on the next
        # dashboard refresh or after the service restarts.
        if self.store.prediction_positions_for_round(round_data["round_id"]):
            return
        if self.prediction_controls["paused"] or self.prediction_controls["emergency_stop"]:
            return
        decision = round_data.get("decision", {})
        if decision.get("action") not in {"ENTER_UP", "ENTER_DOWN"}:
            return
        direction = decision["direction"]
        odds = round_data["up_odds"] if direction == "UP" else round_data["down_odds"]
        self.open_prediction_position(direction, None, round_data, odds)

    def _manage_prediction_positions(self, round_data: dict):
        if self.prediction_controls["paused"] or self.prediction_controls["emergency_stop"]:
            return
        now_ms = utc_now_ms()
        seconds_left = max(0, (round_data["end_time"] - now_ms) // 1000)
        decision = round_data.get("decision", {})
        for position in self.store.active_prediction_positions():
            if position["round_id"] != round_data["round_id"]:
                continue
            position_decision = self._position_decision(round_data, position)
            quote_odds = (
                round_data["up_odds"]
                if position["direction"] == "UP"
                else round_data["down_odds"]
            )
            effective_odds = quote_odds * (
                1 - self.settings.prediction_slippage_bps / 10_000
            )
            mark = position_mark(
                position["stake"],
                position["entry_odds"],
                effective_odds,
                self.settings.prediction_fee_bps / 10_000,
            )
            probability_flipped = (
                position["direction"] == "UP" and round_data["p_up"] < 0.5
            ) or (
                position["direction"] == "DOWN" and round_data["p_up"] >= 0.5
            )
            should_close = (
                mark["return_pct"] >= self.settings.prediction_take_profit_pct
                or mark["return_pct"] <= -self.settings.prediction_stop_loss_pct
                or (
                    seconds_left <= self.settings.prediction_close_last_seconds
                    and mark["pnl"] > 0
                )
                or (probability_flipped and mark["pnl"] > 0)
            )
            if position_decision.get("action") == "CLOSE" or decision.get("action") == "CLOSE":
                should_close = True
            if should_close:
                self._close_prediction_position_at_round(
                    position, round_data, effective_odds, "automatic_risk_close"
                )

    def open_prediction_position(
        self,
        direction: str,
        requested_stake: float | None = None,
        round_data: dict | None = None,
        odds: float | None = None,
    ) -> dict:
        with self._engine_lock:
            return self._open_prediction_position(
                direction, requested_stake, round_data, odds
            )

    def _open_prediction_position(
        self,
        direction: str,
        requested_stake: float | None = None,
        round_data: dict | None = None,
        odds: float | None = None,
    ) -> dict:
        state = round_data or self.refresh_prediction_market()
        if self.prediction_controls["paused"] or self.prediction_controls["emergency_stop"]:
            return {"executed": False, "reason": "trading_controlled_off"}
        round_data = state.get("round") if "round" in state else state
        if not round_data:
            return {"executed": False, "reason": "no_active_round"}
        direction = direction.upper()
        odds = odds or (
            round_data["up_odds"] if direction == "UP" else round_data["down_odds"]
        )
        odds = float(odds) * (
            1 - self.settings.prediction_slippage_bps / 10_000
        )
        account = self.store.prediction_account()
        active_stake = sum(
            p["stake"] for p in self.store.active_prediction_positions()
        )
        stats = self.store.prediction_daily_stats(
            self._day_start_ms(utc_now_ms())
        )
        risk = trade_risk(
            now_ms=utc_now_ms(),
            end_ms=round_data["end_time"],
            direction=direction,
            p_up=round_data["p_up"],
            odds=odds,
            quote_balance=account["quote"],
            equity=account["quote"] + active_stake,
            active_stake=active_stake,
            daily_trades=stats["trades"],
            daily_loss=stats["loss"],
            loss_streak=stats["loss_streak"],
            settings=self.settings,
        )
        if not risk.allowed:
            return {
                "executed": False,
                "reason": risk.reason,
                "risk": risk.__dict__,
            }
        requested = risk.suggested_stake if requested_stake is None else float(requested_stake)
        stake = min(requested, risk.suggested_stake, self.settings.prediction_max_stake)
        if stake < self.settings.prediction_min_stake:
            return {"executed": False, "reason": "stake_below_minimum"}
        fee = stake * self.settings.prediction_fee_bps / 10_000
        position_id = self.store.add_prediction_position(
            {
                "round_id": round_data["round_id"],
                "direction": direction,
                "stake": stake,
                "entry_odds": odds,
                "opened_at": utc_now_ms(),
                "fee": fee,
                "raw": {"source": "auto" if requested_stake is None else "manual"},
            }
        )
        self.store.save_prediction_account(
            account["quote"] - stake, account["realized_pnl"]
        )
        return {
            "executed": True,
            "position_id": position_id,
            "round_id": round_data["round_id"],
            "direction": direction,
            "stake": stake,
            "entry_odds": odds,
            "quoted_odds": odds
            / (1 - self.settings.prediction_slippage_bps / 10_000),
            "expected_value": expected_value(
                round_data["p_up"] if direction == "UP" else 1 - round_data["p_up"],
                odds,
                self.settings.prediction_fee_bps / 10_000,
            ),
            "suggested_stake": risk.suggested_stake,
        }

    def _close_prediction_position_at_round(
        self, position: dict, round_data: dict, current_odds: float, reason: str
    ) -> dict:
        mark = position_mark(
            position["stake"],
            position["entry_odds"],
            current_odds,
            self.settings.prediction_fee_bps / 10_000,
        )
        account = self.store.prediction_account()
        self.store.close_prediction_position(
            position["id"],
            "closed",
            utc_now_ms(),
            current_odds,
            mark["pnl"],
            position["stake"] * self.settings.prediction_fee_bps / 10_000,
        )
        self.store.save_prediction_account(
            account["quote"] + mark["value"],
            account["realized_pnl"] + mark["pnl"],
        )
        return {
            "executed": True,
            "position_id": position["id"],
            "value": mark["value"],
            "pnl": mark["pnl"],
            "reason": reason,
        }

    def close_prediction_position(self, position_id: int) -> dict:
        with self._engine_lock:
            return self._close_prediction_position(position_id)

    def _close_prediction_position(self, position_id: int) -> dict:
        state = self.refresh_prediction_market()
        round_data = state["round"]
        position = next(
            (p for p in self.store.active_prediction_positions() if p["id"] == int(position_id)),
            None,
        )
        if not position:
            return {"executed": False, "reason": "position_not_active"}
        current_odds = (
            round_data["up_odds"]
            if position["direction"] == "UP"
            else round_data["down_odds"]
        )
        current_odds = current_odds * (
            1 - self.settings.prediction_slippage_bps / 10_000
        )
        return self._close_prediction_position_at_round(
            position, round_data, current_odds, "manual_or_risk_close"
        )

    def live(self):
        if self.settings.websocket_enabled:
            try:
                import aiohttp  # noqa: F401

                asyncio.run(self.live_websocket())
                return
            except Exception as error:
                print(f"websocket unavailable, falling back to REST: {error}")
        while True:
            try:
                result = self.run_once()
                prediction = result["prediction"]
                if prediction:
                    print(
                        f'{prediction["signal"]} p_up={prediction["p_up"]:.3f} '
                        f'close={prediction["close"]:.2f} '
                        f'new={prediction["is_new"]} '
                        f'execution={result["execution"]}'
                    )
            except Exception as error:
                print(f"live sync error: {error}")
            time.sleep(self.settings.poll_seconds)

    async def live_websocket(self):
        self.process_bars(self.sync())
        stream = BinanceRealtimeStream(
            self.settings.ws_url,
            self.settings.symbol,
            self.settings.websocket_reconnect_seconds,
        )
        last_refresh = 0.0
        async for event in stream.events():
            self.realtime.update(event)
            event_data = event.get("data", event)
            if event_data.get("e") == "kline":
                bar = event_data.get("k", {})
                if bar.get("x") and bar.get("i") == self.settings.interval:
                    closed = {
                        "open_time": int(bar["t"]),
                        "open": float(bar["o"]),
                        "high": float(bar["h"]),
                        "low": float(bar["l"]),
                        "close": float(bar["c"]),
                        "volume": float(bar["v"]),
                        "close_time": int(bar["T"]),
                        "quote_volume": float(bar["q"]),
                        "trades": int(bar["n"]),
                    }
                    self.store.upsert_bars([closed])
            if time.monotonic() - last_refresh >= 1.0:
                try:
                    state = self.refresh_prediction_market(
                        self.store.bars(self.settings.history_limit)
                    )
                    last_refresh = time.monotonic()
                    decision = state["round"].get("decision", {})
                    if decision.get("action") in {"ENTER_UP", "ENTER_DOWN", "CLOSE"}:
                        print(
                            f'{decision["action"]} p_up={decision["combined_probability"]:.3f} '
                            f'reason={decision["reason"]}'
                        )
                except Exception as error:
                    print(f"realtime decision error: {error}")

    def backtest(self, limit: int) -> BacktestResult:
        bars = self.store.bars(limit)
        if len(bars) < 28:
            bars = fetch_klines(
                self.settings.base_url, self.settings.symbol, self.settings.interval, limit
            )
        if len(bars) < 28:
            return BacktestResult(0, None, 0.0, 0.0)
        model = OnlineLogistic(14)
        correct = 0
        cash = 1.0
        base = 0.0
        position = False
        active_signals = 0
        for index in range(26, len(bars) - 1):
            features = vector(bars, index)
            probability = model.probability(features)
            target = int(bars[index + 1]["close"] > bars[index]["close"])
            if (probability >= 0.5) == bool(target):
                correct += 1
            if not position and probability >= self.settings.trade_threshold:
                active_signals += 1
                entry = self.costs.buy_fill(bars[index]["close"])
                base = cash * (1 - self.costs.fee_rate) / entry
                cash = 0.0
                position = True
            elif position and probability <= 1 - self.settings.trade_threshold:
                active_signals += 1
                exit_price = self.costs.sell_fill(bars[index]["close"])
                cash = base * exit_price * (1 - self.costs.fee_rate)
                base = 0.0
                position = False
            model.update(features, target)
        samples = len(bars) - 27
        if position:
            cash = base * bars[-1]["close"] * (1 - self.costs.fee_rate)
        return BacktestResult(
            samples=samples,
            accuracy=correct / samples if samples else None,
            active_signals=active_signals,
            strategy_return=cash - 1,
            buy_and_hold_return=bars[-1]["close"] / bars[26]["close"] - 1,
            fee_bps=self.settings.fee_bps,
            slippage_bps=self.settings.slippage_bps,
        )
