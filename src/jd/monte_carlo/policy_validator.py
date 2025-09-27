"""Validate mindmap diagrams against cards policy constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List
import re

from .config import (
    ALLOWED_CHILD_VECTORS,
    MAX_TOTAL_NODES,
    SECTION_LABELS,
    TOP_LEVEL_BRANCHES,
)


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]


MERMAID_HEADER_RE = re.compile(r"^```mermaid\s*$", re.IGNORECASE)


def _extract_lines(diagram: str) -> List[str]:
    return [line.rstrip() for line in diagram.strip().splitlines() if line.strip()]


def validate_diagram(diagram: str) -> ValidationResult:
    errors: List[str] = []
    lines = _extract_lines(diagram)
    if not lines:
        errors.append("Diagram is empty")
        return ValidationResult(False, errors)

    if not MERMAID_HEADER_RE.match(lines[0]):
        errors.append("Diagram must start with ```mermaid")

    # Identify top-level and child lines by indentation
    top_level = [
        line
        for line in lines
        if line.startswith("    ") and not line.startswith("      ")
    ]
    if len(top_level) != TOP_LEVEL_BRANCHES:
        errors.append(
            f"Top level branches {len(top_level)} does not match required {TOP_LEVEL_BRANCHES}"
        )

    # Ensure top-level labels match SECTION_LABELS order
    if len(top_level) == TOP_LEVEL_BRANCHES:
        for expected, actual in zip(SECTION_LABELS, top_level):
            label = actual.strip()
            if label != expected:
                errors.append(f"Top-level branch '{label}' should be '{expected}'")

    child_lines = [line for line in lines if line.startswith("      ")]
    node_count = len(child_lines)
    if node_count > MAX_TOTAL_NODES:
        errors.append(f"Leaf node count {node_count} exceeds maximum {MAX_TOTAL_NODES}")

    # Check distribution matches allowed vectors
    if len(top_level) == TOP_LEVEL_BRANCHES:
        counts = []
        for top in top_level:
            prefix = top
            # gather child lines following this label until next top-level
        index_lookup = {label.strip(): idx for idx, label in enumerate(top_level)}
        child_vector: List[int] = [0] * TOP_LEVEL_BRANCHES
        current_label: str | None = None
        for line in lines:
            if line in top_level:
                current_label = line.strip()
            elif line.startswith("      ") and current_label is not None:
                idx = index_lookup[current_label]
                child_vector[idx] += 1

        if child_vector and child_vector not in ALLOWED_CHILD_VECTORS:
            errors.append(
                f"Child vector {child_vector} not in allowed sets {ALLOWED_CHILD_VECTORS}"
            )

    return ValidationResult(valid=not errors, errors=errors)
