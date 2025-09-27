"""Shared configuration for Monte Carlo diagram optimisation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class CardContext:
    """Runtime configuration derived from a specific flashcard."""

    root_label: str
    section_labels: List[str]
    section_content: Dict[str, List[str]]
    key_item_priority: Dict[str, Dict[str, float]]


# Base paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CARDS_DIR = PROJECT_ROOT / "windsurf" / "jd" / "cards_yaml"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Card specific configuration for 0004-causation-s51-factual-vs-scope.yml
DEFAULT_CARD_FILENAME = "0004-causation-s51-factual-vs-scope.yml"
DEFAULT_CARD_PATH = CARDS_DIR / DEFAULT_CARD_FILENAME

# Diagram policy parameters
MAX_TOTAL_NODES = 12
ALLOWED_CHILD_VECTORS = [
    [1, 3, 3, 2, 2],
    [2, 2, 2, 1, 4],
    [2, 3, 3, 3, 1],
]

DEFAULT_SECTION_LABELS = [
    "Legal Test",
    "Case Law",
    "Application",
    "Statute",
    "Core Principle",
]

DEFAULT_SECTION_CONTENT = {
    "Legal Test": [
        "s 51(1)(a) but-for",
        "s 51(2) exceptional",
        "s 51(3)-(4) counterfactuals",
        "s 52 normative scope",
    ],
    "Case Law": [
        "Strong v Woolworths",
        "Amaca v Booth",
        "Wallace v Kam",
        "Seltsam v McGuiness",
    ],
    "Application": [
        "Define harm",
        "Prove but-for",
        "Exclude speculation",
        "Test s 52 scope",
    ],
    "Statute": [
        "Wrongs Act s 51",
        "Wrongs Act s 52",
        "Part VBA interaction",
        "Counterfactual scrutiny",
    ],
    "Core Principle": [
        "Sequence s51(1)(a) → s51(2) → s52",
        "Keep scope separate",
        "Exceptional cases are narrow",
        "Robust inference ≠ speculation",
    ],
}

DEFAULT_KEY_PRIORITY = {
    "Legal Test": {
        "s 51(1)(a) but-for": 1.0,
        "s 51(2) exceptional": 0.9,
        "s 52 normative scope": 0.8,
    },
    "Case Law": {
        "Strong v Woolworths": 1.0,
        "Amaca v Booth": 0.9,
        "Wallace v Kam": 0.8,
    },
    "Application": {
        "Define harm": 0.8,
        "Prove but-for": 1.0,
        "Test s 52 scope": 0.9,
    },
    "Statute": {
        "Wrongs Act s 51": 1.0,
        "Wrongs Act s 52": 0.9,
    },
    "Core Principle": {
        "Sequence s51(1)(a) → s51(2) → s52": 1.0,
        "Keep scope separate": 0.7,
        "Exceptional cases are narrow": 0.75,
        "Robust inference ≠ speculation": 0.8,
    },
}

DEFAULT_CARD_CONTEXT = CardContext(
    root_label="Causation Analysis",
    section_labels=DEFAULT_SECTION_LABELS,
    section_content=DEFAULT_SECTION_CONTENT,
    key_item_priority=DEFAULT_KEY_PRIORITY,
)

DEFAULT_SECTION_WEIGHTS = {
    "Legal Test": 0.25,
    "Case Law": 0.25,
    "Application": 0.25,
    "Statute": 0.15,
    "Core Principle": 0.10,
}

DEFAULT_SCORE_WEIGHTS = {
    "coverage": 0.45,
    "priority": 0.40,
    "balance": 0.15,
}

# Cache files
WEIGHT_CACHE = CACHE_DIR / "weights.json"
SCORE_CACHE = CACHE_DIR / "score_weights.json"


def max_children_per_label(section_labels: List[str]) -> Dict[str, int]:
    """Return the maximum children count per label using allowed vectors."""

    return {
        label: max(vector[idx] for vector in ALLOWED_CHILD_VECTORS)
        for idx, label in enumerate(section_labels)
    }
