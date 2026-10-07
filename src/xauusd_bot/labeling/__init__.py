"""Labeling for xauusd_bot.

The triple-barrier method (Lopez de Prado) is used to turn each candidate entry
into a classification label in ``{-1, 0, +1}``:

* ``+1`` -> the profit target was reached before the stop and before the
  time (vertical) barrier.
* ``-1`` -> the stop was reached first.
* ``0``  -> neither barrier was touched; the vertical (time) barrier expired.

This is the ONLY intentionally forward-looking component in the pipeline. The
forward window actually consumed per row is returned alongside the labels so the
training loop can purge/embargo those bars from the trainable region and avoid
leakage into the walk-forward test set.
"""

from .triple_barrier import triple_barrier_labels

__all__ = ["triple_barrier_labels"]
