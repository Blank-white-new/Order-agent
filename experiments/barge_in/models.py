from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | int | list[list[int]]]:
    truth = np.asarray(y_true, dtype=int)
    predicted = np.asarray(y_pred, dtype=int)
    if truth.shape != predicted.shape:
        raise ValueError("truth and prediction shapes differ")
    tp = int(np.sum((truth == 1) & (predicted == 1)))
    fp = int(np.sum((truth == 0) & (predicted == 1)))
    tn = int(np.sum((truth == 0) & (predicted == 0)))
    fn = int(np.sum((truth == 1) & (predicted == 0)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "n": int(truth.size),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "accuracy": (tp + tn) / truth.size if truth.size else 0.0,
        "specificity": specificity,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
        "confusion_matrix": [[tn, fp], [fn, tp]],
    }


def choose_threshold(y_true: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict]:
    candidates = np.linspace(0.10, 0.90, 81)
    scored = []
    for threshold in candidates:
        metrics = classification_metrics(y_true, probabilities >= threshold)
        scored.append((metrics["f1"], -metrics["false_positive_rate"], metrics["recall"], -abs(threshold - 0.5), float(threshold), metrics))
    best = max(scored, key=lambda row: row[:4])
    return best[4], best[5]


@dataclass
class RuleModel:
    threshold: float = 0.5

    name: str = "rule_baseline"

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        # Feature order is fixed in features.FEATURE_NAMES.
        rms = x[:, 0]
        zcr = x[:, 3]
        centroid = x[:, 4]
        flatness = x[:, 6]
        duration = x[:, 9]
        crest = x[:, 10]
        periodicity = x[:, 11]
        speech_like = (
            (rms >= 0.006)
            & (zcr >= 0.001)
            & (zcr <= 0.019)
            & (centroid >= 250)
            & (centroid <= 1500)
            & (flatness <= 0.58)
            & (duration >= 240)
            & (crest <= 14)
            & (periodicity >= 0.008)
        )
        return np.where(speech_like, 0.85, 0.15)

    def serializable(self) -> dict:
        return {"model_type": self.name, "threshold": self.threshold, "rule_version": "acoustic-rule-v1"}


@dataclass
class LogisticModel:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float
    threshold: float = 0.5

    name: str = "logistic_regression"

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, *, seed: int, iterations: int = 2400, learning_rate: float = 0.08, l2: float = 0.02):
        del seed  # Convex full-batch optimization is deliberately deterministic.
        mean = np.mean(x, axis=0)
        scale = np.std(x, axis=0)
        scale[scale < 1e-9] = 1.0
        z = (x - mean) / scale
        weights = np.zeros(z.shape[1], dtype=float)
        prevalence = float(np.clip(np.mean(y), 1e-6, 1 - 1e-6))
        bias = math.log(prevalence / (1 - prevalence))
        for iteration in range(iterations):
            probabilities = sigmoid(z @ weights + bias)
            error = probabilities - y
            rate = learning_rate / math.sqrt(1.0 + iteration / 350)
            weights -= rate * ((z.T @ error) / y.size + l2 * weights)
            bias -= rate * float(np.mean(error))
        return cls(mean=mean, scale=scale, weights=weights, bias=float(bias))

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return sigmoid(((x - self.mean) / self.scale) @ self.weights + self.bias)

    def serializable(self) -> dict:
        return {
            "model_type": self.name,
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "weights": self.weights.tolist(),
            "bias": self.bias,
            "threshold": self.threshold,
            "training": {"optimizer": "full-batch gradient descent", "iterations": 2400, "l2": 0.02},
        }


@dataclass
class GradientBoostingStumps:
    mean: np.ndarray
    scale: np.ndarray
    initial_score: float
    stumps: list[dict]
    learning_rate: float
    threshold: float = 0.5

    name: str = "gradient_boosting_stumps"

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        seed: int,
        estimators: int = 120,
        learning_rate: float = 0.10,
        subsample: float = 0.85,
    ):
        mean = np.mean(x, axis=0)
        scale = np.std(x, axis=0)
        scale[scale < 1e-9] = 1.0
        z = (x - mean) / scale
        prevalence = float(np.clip(np.mean(y), 1e-6, 1 - 1e-6))
        initial = math.log(prevalence / (1 - prevalence))
        score = np.full(y.shape, initial, dtype=float)
        rng = np.random.default_rng(seed)
        stumps: list[dict] = []
        subset_size = max(2, int(y.size * subsample))
        for _ in range(estimators):
            residual = y - sigmoid(score)
            subset = rng.choice(y.size, size=subset_size, replace=False)
            best = None
            feature_order = rng.permutation(z.shape[1])
            for feature in feature_order:
                candidates = np.unique(np.quantile(z[subset, feature], np.linspace(0.08, 0.92, 15)))
                for threshold in candidates:
                    left_mask = z[subset, feature] <= threshold
                    if not np.any(left_mask) or np.all(left_mask):
                        continue
                    left = float(np.mean(residual[subset][left_mask]))
                    right = float(np.mean(residual[subset][~left_mask]))
                    fitted = np.where(left_mask, left, right)
                    loss = float(np.mean((residual[subset] - fitted) ** 2))
                    candidate = (loss, int(feature), float(threshold), left, right)
                    if best is None or candidate < best:
                        best = candidate
            if best is None:
                break
            _, feature, split, left, right = best
            stump = {"feature": feature, "split": split, "left": left, "right": right}
            stumps.append(stump)
            score += learning_rate * np.where(z[:, feature] <= split, left, right)
        return cls(mean=mean, scale=scale, initial_score=initial, stumps=stumps, learning_rate=learning_rate)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        z = (x - self.mean) / self.scale
        score = np.full(z.shape[0], self.initial_score, dtype=float)
        for stump in self.stumps:
            score += self.learning_rate * np.where(
                z[:, stump["feature"]] <= stump["split"], stump["left"], stump["right"]
            )
        return sigmoid(score)

    def serializable(self) -> dict:
        return {
            "model_type": self.name,
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "initial_score": self.initial_score,
            "stumps": self.stumps,
            "learning_rate": self.learning_rate,
            "threshold": self.threshold,
            "training": {"estimators": len(self.stumps), "subsample": 0.85, "base_learner": "decision stump"},
        }


def model_from_dict(payload: dict):
    model_type = payload["model_type"]
    if model_type == "rule_baseline":
        return RuleModel(threshold=float(payload["threshold"]))
    if model_type == "logistic_regression":
        return LogisticModel(
            mean=np.asarray(payload["mean"], dtype=float),
            scale=np.asarray(payload["scale"], dtype=float),
            weights=np.asarray(payload["weights"], dtype=float),
            bias=float(payload["bias"]),
            threshold=float(payload["threshold"]),
        )
    if model_type == "gradient_boosting_stumps":
        return GradientBoostingStumps(
            mean=np.asarray(payload["mean"], dtype=float),
            scale=np.asarray(payload["scale"], dtype=float),
            initial_score=float(payload["initial_score"]),
            stumps=list(payload["stumps"]),
            learning_rate=float(payload["learning_rate"]),
            threshold=float(payload["threshold"]),
        )
    raise ValueError(f"unsupported model type {model_type}")

