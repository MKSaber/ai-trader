"""Train-period baselines that must not peek at the test fold."""

from __future__ import annotations

import numpy as np


def train_majority_class(y_clf_train: np.ndarray) -> int:
    """Majority direction in the training fold only (0=down, 1=up)."""
    if len(y_clf_train) == 0:
        return 1
    up_rate = float(np.mean(y_clf_train))
    return 1 if up_rate >= 0.5 else 0


def train_constant_probability(y_clf_train: np.ndarray) -> float:
    """Empirical P(up) on the training fold only."""
    if len(y_clf_train) == 0:
        return 0.5
    return float(np.mean(y_clf_train))


def naive_test_scores(
    y_clf_train: np.ndarray,
    n_test: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Majority-class direction + constant train probability for test rows.

    Accuracy of the majority baseline uses class labels predicted as the
    training majority — never the test-period up-rate.
    """
    majority = train_majority_class(y_clf_train)
    p_const = train_constant_probability(y_clf_train)
    # Point prediction: always the train majority class
    prob = np.full(n_test, float(majority), dtype=float)
    # Regression: predict 0 expected return (no edge claim)
    reg = np.zeros(n_test, dtype=float)
    meta = {
        "train_majority_class": float(majority),
        "train_up_rate": p_const,
        "note": (
            "Naive direction = train-fold majority class; "
            "not derived from the test fold."
        ),
    }
    return reg, prob, meta
