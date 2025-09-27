"""Differential evolution optimiser for section weighting."""

from __future__ import annotations

from typing import Dict, List
import json

import numpy as np
from scipy.optimize import differential_evolution

from .config import (
    DEFAULT_SECTION_WEIGHTS,
    SECTION_CONTENT,
    SECTION_LABELS,
    WEIGHT_CACHE,
)


def _evaluate(weights: np.ndarray) -> float:
    """Return negative fitness (differential_evolution minimises)."""
    weights = np.maximum(weights, 1e-6)
    weights = weights / weights.sum()

    # Encourage coverage by rewarding inclusion of richer sections
    richness: List[int] = [len(SECTION_CONTENT[label]) for label in SECTION_LABELS]
    coverage_score = float(np.dot(weights, richness))

    # Encourage balance (penalise high variance)
    balance_penalty = np.var(weights)

    # Multi-objective combination: higher is better so subtract penalty
    fitness = coverage_score - (balance_penalty * 2.5)
    return -fitness


def optimise_weights(max_iterations: int = 150) -> Dict[str, float]:
    bounds = [(0.1, 1.0)] * len(SECTION_LABELS)
    result = differential_evolution(_evaluate, bounds, maxiter=max_iterations, tol=1e-6)
    raw = np.maximum(result.x, 1e-6)
    raw /= raw.sum()
    weights = {label: float(weight) for label, weight in zip(SECTION_LABELS, raw)}
    WEIGHT_CACHE.write_text(json.dumps(weights, indent=2))
    return weights


def load_weights(force_recalculate: bool = False) -> Dict[str, float]:
    if not force_recalculate and WEIGHT_CACHE.exists():
        try:
            return json.loads(WEIGHT_CACHE.read_text())
        except json.JSONDecodeError:
            pass
    return optimise_weights()


def default_weights() -> Dict[str, float]:
    return dict(DEFAULT_SECTION_WEIGHTS)
