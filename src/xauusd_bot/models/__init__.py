"""Model package: the probability filter over ICT/iFVG entry events.

The model does NOT generate trades. The entry trigger is the iFVG retest signal
from :mod:`xauusd_bot.features.signals`. For each signalled entry the model scores
the probability that the trade reaches its target before its stop; the backtest
then only takes signalled entries whose probability clears a configured
threshold.

Two backends share one interface (``fit``/``predict_proba``):

* :class:`xauusd_bot.models.model.Classifier` - the production wrapper. When
  LightGBM + scikit-learn are installed it trains a calibrated LightGBM model
  (``CalibratedClassifierCV``). Otherwise it transparently falls back to the
  pure-stdlib classifier below.
* :class:`xauusd_bot.models.fallback_gbt.FallbackClassifier` - a dependency-free,
  deterministic classifier (multinomial logistic regression trained by gradient
  descent). This is the path the sandbox smoke test exercises.
"""

from .fallback_gbt import FallbackClassifier  # noqa: F401
from .model import Classifier, build_classifier  # noqa: F401
