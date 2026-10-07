"""Dependency-free, deterministic probability classifier (stdlib only).

This is the model that runs when LightGBM / scikit-learn are not installed (the
sandbox case). It is a multinomial logistic-regression classifier trained by
full-batch gradient descent on standardised features. Properties:

* Pure Python standard library (``math``, ``random``) - no numpy/pandas/sklearn.
* Deterministic given ``random_state`` (identical inputs -> identical model).
* Trains on a few hundred rows in well under a second.
* Same ``fit(X, y)`` / ``predict_proba(X)`` interface as the production wrapper,
  so the backtest treats either backend identically.

Why logistic regression and not boosted stumps?
------------------------------------------------
For the role the model plays here - a *calibrated probability filter* over a
modest number of ICT/iFVG entry events - a softmax linear model gives smooth,
well-behaved probabilities, is fast, is easy to make deterministic, and avoids
the overfitting a hand-rolled tree ensemble would invite on a few hundred rows.
Feature standardisation (z-scoring) is folded in so raw ATR-scale and ratio-scale
features coexist. L2 regularisation keeps weights bounded.

Label handling
--------------
``fit`` accepts any hashable class labels (e.g. the integers ``-1, 0, 1`` from
triple-barrier labelling, or ``0/1`` for a binary long-vs-flat setup). The sorted
unique labels become ``classes_``; ``predict_proba`` returns one column per class
in that order. ``prob_for(X, label)`` is a convenience that pulls a single class
column (used by the backtest to score the probability of the signalled outcome).
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence

Row = Sequence[float]
Matrix = Sequence[Row]


def _clip(z: float, lo: float = -30.0, hi: float = 30.0) -> float:
    """Clip a logit to keep ``exp`` from overflowing."""
    if z < lo:
        return lo
    if z > hi:
        return hi
    return z


class FallbackClassifier:
    """Deterministic multinomial logistic-regression classifier (stdlib only)."""

    def __init__(
        self,
        learning_rate: float = 0.1,
        n_iter: int = 400,
        l2: float = 1e-3,
        random_state: int = 42,
    ) -> None:
        self.learning_rate = float(learning_rate)
        self.n_iter = int(n_iter)
        self.l2 = float(l2)
        self.random_state = int(random_state)

        # Learned state (set by fit).
        self.classes_: List = []
        self.n_features_: int = 0
        self._mean: List[float] = []
        self._std: List[float] = []
        self._weights: List[List[float]] = []  # [class][feature]
        self._bias: List[float] = []  # [class]
        self._fitted = False

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _to_float(v) -> float:
        try:
            if v is None:
                return 0.0
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return f
        except (TypeError, ValueError):
            return 0.0

    def _as_matrix(self, X: Matrix) -> List[List[float]]:
        return [[self._to_float(v) for v in row] for row in X]

    def _standardise(self, X: List[List[float]]) -> List[List[float]]:
        out: List[List[float]] = []
        for row in X:
            z = []
            for j in range(self.n_features_):
                s = self._std[j] if self._std[j] > 1e-12 else 1.0
                z.append((row[j] - self._mean[j]) / s)
            out.append(z)
        return out

    # -------------------------------------------------------------------- fit
    def fit(self, X: Matrix, y: Sequence) -> "FallbackClassifier":
        """Train on feature matrix ``X`` and label vector ``y`` (deterministic)."""
        Xf = self._as_matrix(X)
        n = len(Xf)
        if n == 0:
            raise ValueError("cannot fit on an empty feature matrix")
        if len(y) != n:
            raise ValueError("X and y length mismatch")

        self.n_features_ = len(Xf[0]) if Xf[0] else 0
        self.classes_ = sorted(set(y), key=lambda v: (str(type(v)), v))
        n_classes = len(self.classes_)
        class_index = {c: k for k, c in enumerate(self.classes_)}

        # --- Feature standardisation stats --------------------------------
        self._mean = [0.0] * self.n_features_
        self._std = [1.0] * self.n_features_
        if self.n_features_ > 0:
            for j in range(self.n_features_):
                col = [Xf[i][j] for i in range(n)]
                m = math.fsum(col) / n
                var = math.fsum((c - m) ** 2 for c in col) / n
                self._mean[j] = m
                self._std[j] = math.sqrt(var) if var > 0 else 1.0

        Xs = self._standardise(Xf)

        # --- Single class degenerate case ---------------------------------
        if n_classes <= 1:
            self._weights = [[0.0] * self.n_features_ for _ in range(max(1, n_classes))]
            self._bias = [0.0] * max(1, n_classes)
            self._fitted = True
            return self

        # --- Deterministic small random init ------------------------------
        rng = random.Random(self.random_state)
        self._weights = [
            [rng.uniform(-0.01, 0.01) for _ in range(self.n_features_)]
            for _ in range(n_classes)
        ]
        self._bias = [0.0 for _ in range(n_classes)]

        y_idx = [class_index[v] for v in y]

        # --- Full-batch gradient descent on cross-entropy -----------------
        lr = self.learning_rate
        inv_n = 1.0 / n
        for _ in range(self.n_iter):
            grad_w = [[0.0] * self.n_features_ for _ in range(n_classes)]
            grad_b = [0.0] * n_classes
            for i in range(n):
                probs = self._softmax_row(Xs[i])
                target = y_idx[i]
                for k in range(n_classes):
                    err = probs[k] - (1.0 if k == target else 0.0)
                    gb = grad_b[k]
                    grad_b[k] = gb + err
                    gw = grad_w[k]
                    xi = Xs[i]
                    for j in range(self.n_features_):
                        gw[j] += err * xi[j]
            for k in range(n_classes):
                self._bias[k] -= lr * (grad_b[k] * inv_n)
                wk = self._weights[k]
                gwk = grad_w[k]
                for j in range(self.n_features_):
                    grad = gwk[j] * inv_n + self.l2 * wk[j]
                    wk[j] -= lr * grad

        self._fitted = True
        return self

    # ----------------------------------------------------------------- infer
    def _softmax_row(self, xs: Sequence[float]) -> List[float]:
        logits = []
        for k in range(len(self._weights)):
            wk = self._weights[k]
            z = self._bias[k]
            for j in range(self.n_features_):
                z += wk[j] * xs[j]
            logits.append(_clip(z))
        m = max(logits)
        exps = [math.exp(z - m) for z in logits]
        s = math.fsum(exps)
        if s <= 0:
            u = 1.0 / len(exps)
            return [u] * len(exps)
        return [e / s for e in exps]

    def predict_proba(self, X: Matrix) -> List[List[float]]:
        """Return per-class probabilities, columns ordered like ``classes_``."""
        if not self._fitted:
            raise RuntimeError("classifier is not fitted")
        Xf = self._as_matrix(X)
        if len(self.classes_) <= 1:
            # Degenerate: all mass on the single class seen in training.
            return [[1.0] for _ in Xf]
        Xs = self._standardise(Xf)
        return [self._softmax_row(row) for row in Xs]

    def predict(self, X: Matrix) -> List:
        """Return the argmax class label for each row."""
        proba = self.predict_proba(X)
        out = []
        for p in proba:
            best = 0
            for k in range(1, len(p)):
                if p[k] > p[best]:
                    best = k
            out.append(self.classes_[best])
        return out

    def prob_for(self, X: Matrix, label) -> List[float]:
        """Probability of a specific class ``label`` for each row.

        Returns ``0.0`` for a label that was not present during training.
        """
        proba = self.predict_proba(X)
        if label not in self.classes_:
            return [0.0 for _ in proba]
        k = self.classes_.index(label)
        return [p[k] for p in proba]

    def to_dict(self) -> Dict:
        """Serialise learned parameters to a plain JSON-able dict."""
        return {
            "backend": "fallback_logreg",
            "learning_rate": self.learning_rate,
            "n_iter": self.n_iter,
            "l2": self.l2,
            "random_state": self.random_state,
            "classes_": list(self.classes_),
            "n_features_": self.n_features_,
            "mean": self._mean,
            "std": self._std,
            "weights": self._weights,
            "bias": self._bias,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "FallbackClassifier":
        """Rebuild a classifier from :meth:`to_dict` output."""
        obj = cls(
            learning_rate=d.get("learning_rate", 0.1),
            n_iter=d.get("n_iter", 400),
            l2=d.get("l2", 1e-3),
            random_state=d.get("random_state", 42),
        )
        obj.classes_ = list(d.get("classes_", []))
        obj.n_features_ = int(d.get("n_features_", 0))
        obj._mean = list(d.get("mean", []))
        obj._std = list(d.get("std", []))
        obj._weights = [list(w) for w in d.get("weights", [])]
        obj._bias = list(d.get("bias", []))
        obj._fitted = bool(obj._weights)
        return obj
