"""Pareto-like optimiser for diagram scoring weights."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import json
import math
import random
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

from .config import (
    DEFAULT_SCORE_WEIGHTS,
    KEY_ITEM_PRIORITY,
    SCORE_CACHE,
    SECTION_CONTENT,
    SECTION_LABELS,
)
from .diagram_generator import DiagramCandidate, generate_candidate


@dataclass
class ScoreWeights:
    coverage: float
    priority: float
    balance: float

    def normalised(self) -> "ScoreWeights":
        total = self.coverage + self.priority + self.balance
        if total <= 0:
            total = 1.0
        return ScoreWeights(
            coverage=self.coverage / total,
            priority=self.priority / total,
            balance=self.balance / total,
        )

    def to_dict(self) -> Dict[str, float]:
        normalised = self.normalised()
        return {
            "coverage": normalised.coverage,
            "priority": normalised.priority,
            "balance": normalised.balance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "ScoreWeights":
        return cls(
            coverage=data.get("coverage", DEFAULT_SCORE_WEIGHTS["coverage"]),
            priority=data.get("priority", DEFAULT_SCORE_WEIGHTS["priority"]),
            balance=data.get("balance", DEFAULT_SCORE_WEIGHTS["balance"]),
        )


def _candidate_metrics(candidate: DiagramCandidate) -> Tuple[float, float, float]:
    """Return coverage, priority, balance metrics for a candidate."""
    child_counts = candidate.child_vector()
    top_level = sum(1 for count in child_counts if count > 0)
    coverage = top_level / len(child_counts)

    # Priority: sum priorities across selected children
    priority_total = 0.0
    max_total = 0.0
    for label, children in candidate.children.items():
        priorities = KEY_ITEM_PRIORITY.get(label, {})
        priority_total += sum(priorities.get(child, 0.6) for child in children)
        max_total += sum(sorted(priorities.values(), reverse=True)[: len(children)])
    priority_score = 0.0
    if max_total > 0:
        priority_score = priority_total / max_total

    # Balance: prefer even distribution (lower std)
    if len(child_counts) > 1:
        std = float(np.std(child_counts))
        # normalise by max possible std (~max children)
        balance = 1.0 / (1.0 + std)
    else:
        balance = 1.0

    return coverage, priority_score, balance


def _evaluate(weights: np.ndarray, sample_size: int = 200) -> float:
    weights = np.maximum(weights, 1e-6)
    weights = weights / weights.sum()

    samples: List[DiagramCandidate] = [generate_candidate() for _ in range(sample_size)]
    scores: List[float] = []
    for candidate in samples:
        coverage, priority_score, balance = _candidate_metrics(candidate)
        score = (
            weights[0] * coverage
            + weights[1] * priority_score
            + weights[2] * balance
        )
        scores.append(score)

    # Try to maximise the worst-case (min) score for robustness
    worst_case = min(scores)
    average = sum(scores) / len(scores)
    combined = (worst_case * 0.6) + (average * 0.4)
    return -combined


def optimise_score_weights() -> ScoreWeights:
    bounds = [(0.1, 2.0)] * 3
    result = differential_evolution(_evaluate, bounds, maxiter=150, tol=1e-6)
    weights = np.maximum(result.x, 1e-6)
    weights = weights / weights.sum()
    optimised = ScoreWeights(
        coverage=float(weights[0]),
        priority=float(weights[1]),
        balance=float(weights[2]),
    )

    # Cache to disk
    SCORE_CACHE.write_text(json.dumps(optimised.to_dict(), indent=2))
    return optimised


def load_score_weights() -> ScoreWeights:
    if SCORE_CACHE.exists():
        data = json.loads(SCORE_CACHE.read_text())
        return ScoreWeights.from_dict(data)
    return ScoreWeights.from_dict(DEFAULT_SCORE_WEIGHTS)
