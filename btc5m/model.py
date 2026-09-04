import math


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


class OnlineLogistic:
    def __init__(self, feature_count: int, learning_rate: float = 0.08, l2: float = 0.0005):
        self.weights = [0.0] * (feature_count + 1)
        self.learning_rate = learning_rate
        self.l2 = l2
        self.steps = 0

    def probability(self, features: list[float]) -> float:
        score = self.weights[0] + sum(weight * value for weight, value in zip(self.weights[1:], features))
        return _sigmoid(score)

    def update(self, features: list[float], target: int):
        probability = self.probability(features)
        error = target - probability
        self.weights[0] += self.learning_rate * error
        for i, value in enumerate(features, start=1):
            self.weights[i] = (1 - self.learning_rate * self.l2) * self.weights[i]
            self.weights[i] += self.learning_rate * error * value
        self.steps += 1

    def state(self) -> dict:
        return {
            "weights": self.weights,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "steps": self.steps,
        }

    @classmethod
    def from_state(cls, state: dict) -> "OnlineLogistic":
        model = cls(
            feature_count=len(state["weights"]) - 1,
            learning_rate=state.get("learning_rate", 0.08),
            l2=state.get("l2", 0.0005),
        )
        model.weights = list(state["weights"])
        model.steps = state.get("steps", 0)
        return model
