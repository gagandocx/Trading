"""Feature-matrix backend-parity tests.

Guards the stdlib-vs-pandas divergence that previously broke the pandas path:

* ``build_feature_matrix`` must return the ordered feature-name list EXPLICITLY
  (pandas silently drops attributes assigned to a DataFrame, so the list must
  not be smuggled on the matrix object).
* positional row access must go through :func:`get_row`, which uses ``.iloc``
  for a pandas DataFrame (``df[i]`` selects the column labelled ``i``, not row
  ``i``) and plain indexing for the stdlib ``FeatureMatrix``.

The DataFrame-specific checks run only when pandas is installed; the rest run
on the pure-stdlib path too, so this test is meaningful in both environments.
"""

import unittest

import _util  # noqa: F401
from xauusd_bot import compat
from xauusd_bot.config import load_config
from xauusd_bot.data.sample_data import generate_sample
from xauusd_bot.features.engineering import (
    FeatureMatrix,
    build_feature_matrix,
    get_row,
)


def _cfg():
    return load_config("configs/default.yaml")


class TestFeatureMatrixBackendParity(unittest.TestCase):
    def test_returns_matrix_and_feature_names_tuple(self):
        cfg = _cfg()
        rows = generate_sample(120, seed=11)
        result = build_feature_matrix(rows, cfg)

        # Explicit (matrix, feature_names) contract - names are NOT stashed on
        # the matrix (that is exactly what pandas discards).
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        matrix, feature_names = result

        self.assertTrue(feature_names, "feature_names must be a non-empty list")
        self.assertEqual(len(feature_names), len(set(feature_names)))
        self.assertEqual(len(matrix), len(rows))

    def test_get_row_is_positional_and_backend_correct(self):
        cfg = _cfg()
        rows = generate_sample(120, seed=11)
        matrix, feature_names = build_feature_matrix(rows, cfg)

        # Row 0 by position, regardless of backend, is a dict carrying the
        # engineered columns + the bookkeeping fields.
        row0 = get_row(matrix, 0)
        self.assertIsInstance(row0, dict)
        self.assertIn("index", row0)
        self.assertIn("warmup", row0)
        for name in feature_names:
            self.assertIn(name, row0)

        # Positional access tracks the "index" bookkeeping column, proving we
        # select ROW i (not the column labelled i).
        for i in (0, 1, 5, len(rows) - 1):
            self.assertEqual(int(get_row(matrix, i)["index"]), i)

    def test_stdlib_matrix_is_list_backed(self):
        if compat.HAS_PANDAS:
            self.skipTest("pandas installed: stdlib FeatureMatrix path not taken")
        cfg = _cfg()
        rows = generate_sample(60, seed=3)
        matrix, _ = build_feature_matrix(rows, cfg)
        self.assertIsInstance(matrix, FeatureMatrix)
        # Plain list indexing is row access on the stdlib backend.
        self.assertEqual(matrix[2]["index"], 2)

    def test_get_row_uses_iloc_for_dataframe(self):
        if not compat.HAS_PANDAS:
            self.skipTest("pandas not installed")
        import pandas as pd

        cfg = _cfg()
        rows = generate_sample(60, seed=3)
        matrix, feature_names = build_feature_matrix(rows, cfg)
        self.assertIsInstance(matrix, pd.DataFrame)

        # The pre-fix bug: df[i] raised KeyError (column lookup). get_row must
        # return row i via .iloc instead.
        row3 = get_row(matrix, 3)
        self.assertEqual(int(row3["index"]), 3)
        for name in feature_names:
            self.assertIn(name, row3)

        # Column labelled by an integer position does NOT exist, which is why
        # the old positional df[i] indexing blew up.
        self.assertNotIn(3, matrix.columns)


if __name__ == "__main__":
    unittest.main()
