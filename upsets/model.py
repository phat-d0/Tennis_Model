"""L2-regularized logistic regression (Newton's method), numpy only."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Logit:
    coef: np.ndarray
    mean: np.ndarray
    scale: np.ndarray

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (np.asarray(X, float) - self.mean) / self.scale
        z = self.coef[0] + Z @ self.coef[1:]
        return 1.0 / (1.0 + np.exp(-z))


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> Logit:
    """Fit P(y=1) = sigmoid(b0 + b·z) on standardized X; the intercept isn't penalized."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mean) / scale])
    beta = np.zeros(Z.shape[1])
    pen = np.full(Z.shape[1], l2)
    pen[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(Z @ beta)))
        grad = Z.T @ (p - y) + pen * beta
        H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(pen)
        step = np.linalg.solve(H, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return Logit(beta, mean, scale)


def log_loss(y, p) -> float:
    p = np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
