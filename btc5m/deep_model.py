"""Small dependency-free deep sequence model for BTC direction references.

The model is intentionally conservative: it predicts the next candle direction,
not an exact price, and it is only an additional reference signal.  The
implementation avoids a mandatory ML runtime so the live dashboard still works
on a clean Python installation.  A future PyTorch backend can use the same
serialized metadata and manager interface.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass

from .features import FEATURE_NAMES, vector


def _clip(value: float, lower: float = 1e-6, upper: float = 1.0 - 1e-6) -> float:
    return max(lower, min(upper, float(value)))


def _logit(probability: float) -> float:
    probability = _clip(probability)
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _tanh(value: float) -> float:
    return math.tanh(max(-12.0, min(12.0, value)))


def _log_loss(probabilities: list[float], targets: list[int]) -> float | None:
    if not targets:
        return None
    return sum(
        -target * math.log(_clip(probability))
        - (1 - target) * math.log(_clip(1.0 - probability))
        for probability, target in zip(probabilities, targets)
    ) / len(targets)


def _metrics(probabilities: list[float], targets: list[int]) -> dict:
    if not targets:
        return {
            "samples": 0,
            "accuracy": None,
            "balanced_accuracy": None,
            "log_loss": None,
            "brier_score": None,
            "high_confidence_precision": None,
            "high_confidence_samples": 0,
        }
    predictions = [int(probability >= 0.5) for probability in probabilities]
    correct = sum(prediction == target for prediction, target in zip(predictions, targets))
    positives = [index for index, target in enumerate(targets) if target == 1]
    negatives = [index for index, target in enumerate(targets) if target == 0]
    recalls = []
    for indexes in (positives, negatives):
        if indexes:
            recalls.append(
                sum(predictions[index] == targets[index] for index in indexes)
                / len(indexes)
            )
    high = [
        index
        for index, probability in enumerate(probabilities)
        if abs(probability - 0.5) >= 0.14
    ]
    return {
        "samples": len(targets),
        "accuracy": correct / len(targets),
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "log_loss": _log_loss(probabilities, targets),
        "brier_score": sum(
            (probability - target) ** 2
            for probability, target in zip(probabilities, targets)
        )
        / len(targets),
        "high_confidence_precision": (
            sum(predictions[index] == targets[index] for index in high) / len(high)
            if high
            else None
        ),
        "high_confidence_samples": len(high),
    }


def _temperature_calibration(
    probabilities: list[float], targets: list[int]
) -> tuple[float, str]:
    if len(targets) < 20:
        return 1.0, "uncalibrated_insufficient_validation_data"
    best_temperature = 1.0
    best_loss = _log_loss(probabilities, targets)
    for step in range(5, 401):
        temperature = step / 100.0
        calibrated = [_sigmoid(_logit(probability) / temperature) for probability in probabilities]
        loss = _log_loss(calibrated, targets)
        if loss is not None and (best_loss is None or loss < best_loss):
            best_temperature = temperature
            best_loss = loss
    return best_temperature, "temperature_scaled"


@dataclass
class DeepReference:
    raw_probability: float | None
    calibrated_probability: float | None
    available: bool
    model_version: str
    training_samples: int
    calibration_status: str
    approved_for_decision: bool
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "raw_probability": self.raw_probability,
            "calibrated_probability": self.calibrated_probability,
            "available": self.available,
            "model_version": self.model_version,
            "training_samples": self.training_samples,
            "calibration_status": self.calibration_status,
            "approved_for_decision": self.approved_for_decision,
            "reason": self.reason,
        }


class DeepSequenceMLP:
    """Two hidden-layer sequence classifier implemented with the standard library."""

    def __init__(
        self,
        input_size: int,
        hidden_one: int = 24,
        hidden_two: int = 12,
        seed: int = 7,
    ):
        self.input_size = input_size
        self.hidden_one = hidden_one
        self.hidden_two = hidden_two
        rng = random.Random(seed)
        self.w1 = [
            [rng.uniform(-limit, limit) for _ in range(input_size)]
            for limit in [math.sqrt(6.0 / (input_size + hidden_one))]
            for _ in range(hidden_one)
        ]
        self.b1 = [0.0] * hidden_one
        self.w2 = [
            [rng.uniform(-math.sqrt(6.0 / (hidden_one + hidden_two)),
                         math.sqrt(6.0 / (hidden_one + hidden_two)))
             for _ in range(hidden_one)]
            for _ in range(hidden_two)
        ]
        self.b2 = [0.0] * hidden_two
        limit = math.sqrt(6.0 / (hidden_two + 1))
        self.w3 = [rng.uniform(-limit, limit) for _ in range(hidden_two)]
        self.b3 = 0.0

    def _forward(self, features: list[float]) -> tuple[list[float], list[float], float]:
        h1 = [
            _tanh(self.b1[row] + sum(weight * value for weight, value in zip(self.w1[row], features)))
            for row in range(self.hidden_one)
        ]
        h2 = [
            _tanh(self.b2[row] + sum(weight * value for weight, value in zip(self.w2[row], h1)))
            for row in range(self.hidden_two)
        ]
        return h1, h2, _sigmoid(self.b3 + sum(weight * value for weight, value in zip(self.w3, h2)))

    def probability(self, features: list[float]) -> float:
        return self._forward(features)[2]

    def train(
        self,
        samples: list[list[float]],
        targets: list[int],
        epochs: int = 6,
        learning_rate: float = 0.003,
        l2: float = 0.0001,
    ):
        if not samples or len(samples) != len(targets):
            raise ValueError("deep model training data is empty or inconsistent")
        for _ in range(max(1, epochs)):
            for features, target in zip(samples, targets):
                h1, h2, probability = self._forward(features)
                output_error = probability - target
                old_w3 = list(self.w3)
                h2_error = [
                    output_error * old_w3[row] * (1.0 - h2[row] * h2[row])
                    for row in range(self.hidden_two)
                ]
                old_w2 = [list(row) for row in self.w2]
                h1_error = [
                    sum(h2_error[row] * old_w2[row][column] for row in range(self.hidden_two))
                    * (1.0 - h1[column] * h1[column])
                    for column in range(self.hidden_one)
                ]
                for row in range(self.hidden_two):
                    for column in range(self.hidden_one):
                        self.w2[row][column] -= learning_rate * (
                            h2_error[row] * h1[column] + l2 * self.w2[row][column]
                        )
                    self.b2[row] -= learning_rate * h2_error[row]
                for row in range(self.hidden_one):
                    for column in range(self.input_size):
                        self.w1[row][column] -= learning_rate * (
                            h1_error[row] * features[column] + l2 * self.w1[row][column]
                        )
                    self.b1[row] -= learning_rate * h1_error[row]
                for row in range(self.hidden_two):
                    self.w3[row] -= learning_rate * (
                        output_error * h2[row] + l2 * self.w3[row]
                    )
                self.b3 -= learning_rate * output_error

    def state(self) -> dict:
        return {
            "input_size": self.input_size,
            "hidden_one": self.hidden_one,
            "hidden_two": self.hidden_two,
            "w1": self.w1,
            "b1": self.b1,
            "w2": self.w2,
            "b2": self.b2,
            "w3": self.w3,
            "b3": self.b3,
        }

    @classmethod
    def from_state(cls, state: dict) -> "DeepSequenceMLP":
        model = cls(
            int(state["input_size"]),
            int(state["hidden_one"]),
            int(state["hidden_two"]),
        )
        for name in ("w1", "b1", "w2", "b2", "w3", "b3"):
            setattr(model, name, state[name])
        return model


class DeepModelManager:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.deep_model_path or f"{settings.db_path}.deep.json"
        self.sequence_length = max(4, settings.prediction_deep_sequence_length)
        self.feature_count = len(FEATURE_NAMES)
        self.model: DeepSequenceMLP | None = None
        self.means: list[float] = []
        self.stds: list[float] = []
        self.temperature = 1.0
        self.metadata = {
            "model_version": "deep-mlp-v1",
            "training_samples": 0,
            "calibration_status": "not_trained",
            "approved_for_decision": False,
            "metrics": {},
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.model = DeepSequenceMLP.from_state(state["model"])
            self.means = list(state["means"])
            self.stds = list(state["stds"])
            self.temperature = float(state.get("temperature", 1.0))
            self.metadata.update(state.get("metadata", {}))
        except (OSError, ValueError, KeyError, TypeError):
            self.model = None

    def _save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "model": self.model.state() if self.model else None,
                    "means": self.means,
                    "stds": self.stds,
                    "temperature": self.temperature,
                    "metadata": self.metadata,
                },
                handle,
            )

    def _approved(self) -> bool:
        metrics = self.metadata.get("metrics", {}).get("test", {})
        accuracy = metrics.get("accuracy")
        brier_score = metrics.get("brier_score")
        return bool(
            self.metadata.get("approved_for_decision", False)
            and self.metadata.get("calibration_status") == "temperature_scaled"
            and int(self.metadata.get("training_samples", 0) or 0)
            >= max(60, self.settings.prediction_deep_min_train_samples)
            and accuracy is not None
            and float(accuracy) >= self.settings.prediction_deep_min_test_accuracy
            and brier_score is not None
            and float(brier_score) <= self.settings.prediction_deep_max_test_brier
        )

    def _raw_sequence(self, bars: list[dict], index: int) -> list[float]:
        rows = []
        start = index - self.sequence_length + 1
        for position in range(start, index + 1):
            rows.extend(vector(bars, position))
        return rows

    def _normalize(self, features: list[float]) -> list[float]:
        return [
            (value - mean) / std
            for value, mean, std in zip(features, self.means, self.stds)
        ]

    def _samples(self, bars: list[dict]) -> tuple[list[list[float]], list[int]]:
        first = max(26, self.sequence_length - 1)
        samples = []
        targets = []
        for index in range(first, len(bars) - 1):
            samples.append(self._raw_sequence(bars, index))
            targets.append(int(bars[index + 1]["close"] > bars[index]["close"]))
        return samples, targets

    @staticmethod
    def _fit_scaler(samples: list[list[float]]) -> tuple[list[float], list[float]]:
        count = len(samples)
        width = len(samples[0])
        means = [sum(row[column] for row in samples) / count for column in range(width)]
        stds = []
        for column, mean in enumerate(means):
            variance = sum((row[column] - mean) ** 2 for row in samples) / max(1, count - 1)
            stds.append(max(math.sqrt(variance), 1e-8))
        return means, stds

    def train(self, bars: list[dict]) -> dict:
        samples, targets = self._samples(bars)
        if len(samples) < max(60, self.settings.prediction_deep_min_train_samples):
            raise ValueError(
                f"need at least {max(60, self.settings.prediction_deep_min_train_samples)} "
                f"deep samples, got {len(samples)}"
            )
        train_end = max(1, int(len(samples) * 0.70))
        validation_end = max(train_end + 1, int(len(samples) * 0.85))
        if validation_end >= len(samples):
            validation_end = len(samples) - 1
        self.means, self.stds = self._fit_scaler(samples[:train_end])
        normalized = [self._normalize(row) for row in samples]
        self.model = DeepSequenceMLP(self.sequence_length * self.feature_count)
        self.model.train(
            normalized[:train_end],
            targets[:train_end],
            epochs=self.settings.prediction_deep_epochs,
            learning_rate=self.settings.prediction_deep_learning_rate,
        )
        validation_probabilities = [
            self.model.probability(row) for row in normalized[train_end:validation_end]
        ]
        validation_targets = targets[train_end:validation_end]
        self.temperature, calibration_status = _temperature_calibration(
            validation_probabilities, validation_targets
        )
        test_probabilities = [
            _sigmoid(_logit(self.model.probability(row)) / self.temperature)
            for row in normalized[validation_end:]
        ]
        test_targets = targets[validation_end:]
        metrics = {
            "train": _metrics(
                [self.model.probability(row) for row in normalized[:train_end]],
                targets[:train_end],
            ),
            "validation": _metrics(
                [
                    _sigmoid(_logit(probability) / self.temperature)
                    for probability in validation_probabilities
                ],
                validation_targets,
            ),
            "test": _metrics(test_probabilities, test_targets),
        }
        approved = bool(
            calibration_status == "temperature_scaled"
            and len(test_targets)
            >= max(60, self.settings.prediction_deep_min_train_samples)
            and metrics["test"]["accuracy"] is not None
            and metrics["test"]["accuracy"]
            >= self.settings.prediction_deep_min_test_accuracy
            and metrics["test"]["brier_score"] is not None
            and metrics["test"]["brier_score"]
            <= self.settings.prediction_deep_max_test_brier
        )
        self.metadata = {
            "model_version": "deep-mlp-v1",
            "trained_at": int(time.time() * 1000),
            "training_samples": len(samples),
            "train_samples": train_end,
            "validation_samples": len(validation_targets),
            "test_samples": len(test_targets),
            "sequence_length": self.sequence_length,
            "feature_names": FEATURE_NAMES,
            "calibration_status": calibration_status,
            "approved_for_decision": approved,
            "metrics": metrics,
        }
        self._save()
        return self.status()

    def reference(self, bars: list[dict]) -> DeepReference:
        if not self.model or len(bars) < max(27, self.sequence_length):
            return DeepReference(
                None,
                None,
                False,
                self.metadata["model_version"],
                int(self.metadata.get("training_samples", 0)),
                self.metadata.get("calibration_status", "not_trained"),
                False,
                "deep_model_not_trained",
            )
        try:
            raw = self.model.probability(self._normalize(self._raw_sequence(bars, len(bars) - 1)))
            calibrated = _sigmoid(_logit(raw) / max(0.1, self.temperature))
            return DeepReference(
                raw,
                calibrated,
                True,
                self.metadata["model_version"],
                int(self.metadata.get("training_samples", 0)),
                self.metadata.get("calibration_status", "uncalibrated"),
                self._approved(),
            )
        except (ValueError, IndexError, ZeroDivisionError):
            return DeepReference(
                None,
                None,
                False,
                self.metadata["model_version"],
                int(self.metadata.get("training_samples", 0)),
                "runtime_error",
                False,
                "deep_model_runtime_error",
            )

    def status(self) -> dict:
        result = dict(self.metadata)
        result["available"] = self.model is not None
        result["approved_for_decision"] = self._approved()
        result["model_path"] = self.path
        result["temperature"] = self.temperature
        result["feature_count"] = self.feature_count
        result["sequence_length"] = self.sequence_length
        return result
