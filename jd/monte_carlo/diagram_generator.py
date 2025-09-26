"""Utilities for generating and evaluating candidate diagrams."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence
import random

from .config import (
    ALLOWED_CHILD_VECTORS,
    MAX_TOTAL_NODES,
    get_card_context,
    get_max_children_per_label,
)

@dataclass
class DiagramCandidate:
    labels: Sequence[str]
    children: Dict[str, List[str]]

    def to_mermaid(self) -> str:
        context = get_card_context()
        lines = ["```mermaid", "mindmap", f"  root(({context.root_label}))"]
        for label in self.labels:
            lines.append(f"    {label}")
            for child in self.children.get(label, []):
                lines.append(f"      {child}")
        lines.append("```")
        return "\n".join(lines)

    @property
    def node_count(self) -> int:
        """Return total leaf nodes only (top-level count fixed by policy)."""
        return sum(len(self.children.get(label, [])) for label in self.labels)

    def child_vector(self) -> List[int]:
        return [len(self.children.get(label, [])) for label in self.labels]


def _weighted_vector_choice(weight_map: Optional[Mapping[str, float]]) -> Sequence[int]:
    context = get_card_context()
    section_labels = context.section_labels
    max_children_map = get_max_children_per_label()
    if not weight_map:
        return random.choice(ALLOWED_CHILD_VECTORS)

    # Normalise weights and derive a simple target profile per label (0..1)
    total = sum(weight_map.get(label, 1.0) for label in section_labels)
    targets = [weight_map.get(label, 1.0) / total for label in section_labels]

    def vector_distance(vector: Sequence[int]) -> float:
        distances: List[float] = []
        for idx, label in enumerate(section_labels):
            max_children = max_children_map[label] or 1
            ratio = vector[idx] / max_children
            distances.append(abs(ratio - targets[idx]))
        # smaller is better
        return sum(distances)

    best_vector = min(ALLOWED_CHILD_VECTORS, key=vector_distance)
    return best_vector


def sample_children(label: str, count: int) -> List[str]:
    context = get_card_context()
    pool = context.section_content.get(label, [])
    if count <= 0:
        return []
    if not pool:
        return []
    if len(pool) >= count:
        return random.sample(pool, count)
    # Repeat pool items to satisfy required count while preserving order variety
    repeats: List[str] = []
    while len(repeats) < count:
        repeats.extend(random.sample(pool, len(pool)) if len(pool) > 1 else pool)
    return repeats[:count]


def generate_candidate(
    weight_map: Optional[Mapping[str, float]] = None,
) -> DiagramCandidate:
    vector = _weighted_vector_choice(weight_map)
    context = get_card_context()
    section_labels = context.section_labels
    children: Dict[str, List[str]] = {}
    for label, child_count in zip(section_labels, vector):
        children[label] = sample_children(label, child_count)
    candidate = DiagramCandidate(labels=section_labels, children=children)
    # basic safety check
    if candidate.node_count > MAX_TOTAL_NODES:
        return generate_candidate(weight_map)
    return candidate
