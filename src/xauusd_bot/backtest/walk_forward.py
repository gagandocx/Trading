"""Strictly time-ordered walk-forward splits with purge/embargo.

Why this matters
----------------
The triple-barrier label at bar ``t`` looks FORWARD up to ``horizon`` bars. If a
test fold starts immediately after the training window, the last training rows'
label windows would overlap the first test bars -> information leakage that
flatters results. To prevent this we insert a PURGE/EMBARGO gap of at least
``horizon`` bars between every train block and the test block that follows it, and
we DROP the final ``horizon`` training rows whose label windows would reach into
that gap (they are unlabelable anyway).

The folds are strictly increasing in time and never shuffled. Two schemes are
supported:

* ``expanding`` (default): train = all bars from the start up to the embargo gap
  before each test block; the train window grows each fold.
* ``rolling``: train = a fixed-width window immediately before the embargo gap.

The guarantee asserted by the unit test:
    for every fold, no train index lies within ``[test_start - horizon, test_end]``.
"""

from __future__ import annotations

from typing import Iterator, List, Tuple

Split = Tuple[List[int], List[int]]


def walk_forward_splits(
    n: int,
    train_size: int,
    test_size: int,
    embargo: int,
    horizon: int = 0,
    mode: str = "expanding",
    min_train: int = None,  # type: ignore[assignment]
) -> List[Split]:
    """Generate ``(train_idx, test_idx)`` folds over ``n`` time-ordered rows.

    Parameters
    ----------
    n:
        Total number of rows (bars).
    train_size:
        Train window length in bars. For ``expanding`` mode this is the MINIMUM
        initial train size; for ``rolling`` it is the fixed window width.
    test_size:
        Test window length in bars.
    embargo:
        Base purge/embargo gap in bars between the train block and the test block.
    horizon:
        The triple-barrier labelling horizon. The effective gap used is
        ``max(embargo, horizon)`` so the gap is ALWAYS >= the label horizon.
    mode:
        ``"expanding"`` (growing train window) or ``"rolling"`` (fixed window).
    min_train:
        Minimum number of train rows required to emit a fold (defaults to
        ``train_size``).

    Returns
    -------
    list of (train_idx, test_idx)
        Each a list of integer row indices. Strictly increasing in time; the
        maximum train index is always ``<= test_start - gap - 1``.
    """
    if n <= 0 or test_size <= 0 or train_size <= 0:
        return []
    gap = max(int(embargo), int(horizon), 0)
    if min_train is None:
        min_train = train_size

    folds: List[Split] = []
    # The first test block starts after an initial train window plus the gap.
    test_start = train_size + gap
    while test_start + test_size <= n:
        test_end = test_start + test_size  # exclusive
        test_idx = list(range(test_start, test_end))

        # Train rows must end at least ``gap`` bars before the test start, so the
        # last train row's forward label window cannot reach into the test set.
        train_end = test_start - gap  # exclusive
        if mode == "rolling":
            train_begin = max(0, train_end - train_size)
        else:  # expanding
            train_begin = 0
        train_idx = list(range(train_begin, train_end))

        if len(train_idx) >= min_train:
            folds.append((train_idx, test_idx))

        test_start += test_size

    return folds


def iter_walk_forward_splits(*args, **kwargs) -> Iterator[Split]:
    """Iterator variant of :func:`walk_forward_splits`."""
    for fold in walk_forward_splits(*args, **kwargs):
        yield fold
