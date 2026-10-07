"""Production model wrapper with a calibrated LightGBM path and stdlib fallback.

:class:`Classifier` exposes a single ``fit(X, y)`` / ``predict_proba(X)`` /
``prob_for(X, label)`` interface. At construction it chooses a backend:

* ``lightgbm`` + ``scikit-learn`` installed and ``model_type == "lightgbm"``:
  train a ``LGBMClassifier`` wrapped in ``sklearn.calibration.CalibratedClassifierCV``
  so the probabilities are CALIBRATED (isotonic/sigmoid). LightGBM is the
  RECOMMENDED PRODUCTION MODEL - it handles the non-linear interactions among the
  ICT/iFVG features far better than the linear fallback.
* otherwise: fall back to :class:`xauusd_bot.models.fallback_gbt.FallbackClassifier`
  (pure stdlib, deterministic). This is the path exercised in the sandbox.

Backend selection is done lazily via try/except import so merely importing this
module never requires LightGBM or scikit-learn.

Persistence (``save`` / ``load``) uses the fallback's JSON serialisation when on
the fallback path, and ``pickle`` for the LightGBM/sklearn path.
"""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

from .fallback_gbt import FallbackClassifier

Matrix = Sequence[Sequence[float]]


def _lightgbm_available() -> bool:
    """Lazily probe for LightGBM + scikit-learn without importing at module load."""
    try:  # pragma: no cover - depends on environment
        import lightgbm  # noqa: F401
        import sklearn  # noqa: F401
        from sklearn.calibration import CalibratedClassifierCV  # noqa: F401

        return True
    except Exception:
        return False


class Classifier:
    """Unified classifier wrapper. Selects LightGBM (calibrated) or the fallback.

    Parameters mirror the useful subset of :class:`xauusd_bot.config.ModelConfig`.
    ``backend`` may be forced to ``"fallback"`` for deterministic testing.
    """

    def __init__(
        self,
        model_type: str = "lightgbm",
        n_estimators: int = 300,
        learning_rate: float = 0.05,
        max_depth: int = 6,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
        backend: Optional[str] = None,
        calibration: str = "isotonic",
    ) -> None:
        self.model_type = model_type
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.min_child_samples = min_child_samples
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.random_state = random_state
        self.calibration = calibration

        # Decide backend.
        if backend is None:
            use_lgbm = model_type == "lightgbm" and _lightgbm_available()
            backend = "lightgbm" if use_lgbm else "fallback"
        self.backend = backend

        self._impl = None
        self.classes_: List = []

    # ----------------------------------------------------------- constructors
    @classmethod
    def from_config(cls, cfg, backend: Optional[str] = None) -> "Classifier":
        """Build a classifier from a :class:`xauusd_bot.config.Config`."""
        m = cfg.model
        return cls(
            model_type=m.model_type,
            n_estimators=m.n_estimators,
            learning_rate=m.learning_rate,
            max_depth=m.max_depth,
            num_leaves=m.num_leaves,
            min_child_samples=m.min_child_samples,
            subsample=m.subsample,
            colsample_bytree=m.colsample_bytree,
            random_state=m.random_state,
            backend=backend,
        )

    # --------------------------------------------------------------------- fit
    def fit(self, X: Matrix, y: Sequence) -> "Classifier":
        if self.backend == "lightgbm":
            try:  # pragma: no cover - only runs where LightGBM exists
                self._fit_lightgbm(X, y)
                self.classes_ = list(self._impl.classes_)
                return self
            except Exception:
                # Any failure in the heavy path degrades gracefully to fallback.
                self.backend = "fallback"
                self._impl = None

        impl = FallbackClassifier(
            learning_rate=max(0.05, min(0.5, self.learning_rate * 4)),
            n_iter=400,
            random_state=self.random_state,
        )
        impl.fit(X, y)
        self._impl = impl
        self.classes_ = list(impl.classes_)
        return self

    def _fit_lightgbm(self, X: Matrix, y: Sequence) -> None:  # pragma: no cover
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV

        base = lgb.LGBMClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            num_leaves=self.num_leaves,
            min_child_samples=self.min_child_samples,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            random_state=self.random_state,
            verbosity=-1,
        )
        # Calibrated probabilities. cv=prefit would require a holdout; we let
        # CalibratedClassifierCV cross-fit internally (robust for small folds).
        n = len(list(y))
        method = self.calibration if n >= 50 else "sigmoid"
        try:
            model = CalibratedClassifierCV(base, method=method, cv=3)
            model.fit(X, y)
        except Exception:
            # Not enough data for internal CV -> fit the base estimator alone.
            base.fit(X, y)
            model = base
        self._impl = model

    # ------------------------------------------------------------------- infer
    def predict_proba(self, X: Matrix) -> List[List[float]]:
        if self._impl is None:
            raise RuntimeError("classifier is not fitted")
        proba = self._impl.predict_proba(X)
        # Normalise to list[list[float]] regardless of backend return type.
        return [list(row) for row in proba]

    def predict(self, X: Matrix) -> List:
        if self._impl is None:
            raise RuntimeError("classifier is not fitted")
        return list(self._impl.predict(X))

    def prob_for(self, X: Matrix, label) -> List[float]:
        """Probability of a specific class ``label`` per row (0.0 if unseen)."""
        if self._impl is None:
            raise RuntimeError("classifier is not fitted")
        if hasattr(self._impl, "prob_for"):
            return list(self._impl.prob_for(X, label))
        # LightGBM/sklearn path.
        classes = list(self.classes_)
        proba = self.predict_proba(X)
        if label not in classes:
            return [0.0 for _ in proba]
        k = classes.index(label)
        return [row[k] for row in proba]

    # ------------------------------------------------------------- persistence
    def save(self, path: str) -> str:
        """Persist the fitted model to ``path``."""
        if self._impl is None:
            raise RuntimeError("nothing to save: classifier is not fitted")
        if self.backend == "fallback":
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._impl.to_dict(), fh)
        else:  # pragma: no cover - heavy path
            import pickle

            with open(path, "wb") as fh:
                pickle.dump(self._impl, fh)
        return path

    def load(self, path: str) -> "Classifier":
        """Load a model previously written by :meth:`save`."""
        if self.backend == "fallback":
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            self._impl = FallbackClassifier.from_dict(d)
        else:  # pragma: no cover - heavy path
            import pickle

            with open(path, "rb") as fh:
                self._impl = pickle.load(fh)
        self.classes_ = list(getattr(self._impl, "classes_", []))
        return self


def build_classifier(cfg, backend: Optional[str] = None) -> Classifier:
    """Convenience factory mirroring :meth:`Classifier.from_config`."""
    return Classifier.from_config(cfg, backend=backend)
