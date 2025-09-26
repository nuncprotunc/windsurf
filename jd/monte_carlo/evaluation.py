"""Scoring utilities for diagram candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from .config import KEY_ITEM_PRIORITY, SECTION_LABELS
from .diagram_generator import DiagramCandidate


@dataclass(frozen=True)
class Metrics:
    coverage: float
    priority: float
    balance: float


def compute_metrics(candidate: DiagramCandidate) -> Metrics:
    child_counts = candidate.child_vector()
    active_sections = sum(1 for count in child_counts if count > 0)
    coverage = active_sections / len(SECTION_LABELS)

    priority_total = 0.0
    max_total = 0.0
    for label, children in candidate.children.items():
        priorities = KEY_ITEM_PRIORITY.get(label, {})
        for child in children:
            priority_total += priorities.get(child, 0.6)
        # assume selecting highest priority items is best possible baseline
        sorted_priorities = sorted(priorities.values(), reverse=True)
        max_total += sum(sorted_priorities[: len(children)])
    priority_score = priority_total / max_total if max_total > 0 else 0.0

    if len(child_counts) > 1:
        std = float(np.std(child_counts))
        balance = 1.0 / (1.0 + std)
    else:
        balance = 1.0

    return Metrics(coverage=coverage, priority=priority_score, balance=balance)


def score_candidate(metrics: Metrics, weights: Dict[str, float]) -> float:
    coverage_weight = weights.get("coverage", 0.4)
    priority_weight = weights.get("priority", 0.4)
    balance_weight = weights.get("balance", 0.2)
    return (
        coverage_weight * metrics.coverage
        + priority_weight * metrics.priority
        + balance_weight * metrics.balance
    )
