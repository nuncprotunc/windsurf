"""Optimise the diagram for 0004-causation-s51-factual-vs-scope.yml."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

import yaml

from .config import CARD_PATH
from .diagram_generator import DiagramCandidate, generate_candidate
from .evaluation import compute_metrics, score_candidate
from .policy_validator import validate_diagram
from .score_optimizer import load_score_weights, optimise_score_weights
from .weight_optimizer import default_weights, load_weights, optimise_weights


def _maybe_optimise_section_weights(force: bool, max_iterations: int) -> Dict[str, float]:
    if force:
        return optimise_weights(max_iterations=max_iterations)
    try:
        return load_weights(force_recalculate=False)
    except Exception:
        return optimise_weights(max_iterations=max_iterations)


def _maybe_optimise_score_weights(force: bool) -> Dict[str, float]:
    score_weights_obj = load_score_weights() if not force else optimise_score_weights()
    return score_weights_obj.to_dict()


def _candidate_to_dict(candidate: DiagramCandidate) -> Dict[str, object]:
    metrics = compute_metrics(candidate)
    return {
        "child_vector": candidate.child_vector(),
        "node_count": candidate.node_count,
        "metrics": {
            "coverage": metrics.coverage,
            "priority": metrics.priority,
            "balance": metrics.balance,
        },
    }


def optimise_diagram(
    iterations: int,
    section_weights: Dict[str, float],
    score_weights: Dict[str, float],
    seed: Optional[int] = None,
) -> DiagramCandidate:
    if seed is not None:
        import random

        random.seed(seed)

    best_candidate: Optional[DiagramCandidate] = None
    best_score = float("-inf")
    for _ in range(iterations):
        candidate = generate_candidate(section_weights)
        diagram = candidate.to_mermaid()
        validation = validate_diagram(diagram)
        if not validation.valid:
            continue
        metrics = compute_metrics(candidate)
        score = score_candidate(metrics, score_weights)
        if score > best_score:
            best_candidate = candidate
            best_score = score
    if best_candidate is None:
        raise RuntimeError("No valid diagram generated within constraints")
    return best_candidate


def update_card(diagram_text: str) -> None:
    data = yaml.safe_load(CARD_PATH.read_text(encoding="utf-8"))
    data["diagram"] = diagram_text
    CARD_PATH.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimise the causation diagram")
    parser.add_argument("--iterations", type=int, default=2000, help="Monte Carlo iterations")
    parser.add_argument("--force-section-weights", action="store_true", help="Re-optimise section weights")
    parser.add_argument("--force-score-weights", action="store_true", help="Re-optimise scoring weights")
    parser.add_argument("--seed", type=int, help="Deterministic random seed")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to card; just print diagram")
    parser.add_argument("--max-weight-iters", type=int, default=150, help="Iterations for weight optimisation")
    args = parser.parse_args()

    section_weights = _maybe_optimise_section_weights(
        args.force_section_weights,
        args.max_weight_iters,
    )
    score_weights = _maybe_optimise_score_weights(args.force_score_weights)

    candidate = optimise_diagram(
        iterations=args.iterations,
        section_weights=section_weights,
        score_weights=score_weights,
        seed=args.seed,
    )

    diagram_text = candidate.to_mermaid()

    if args.dry_run:
        print(diagram_text)
        return

    update_card(diagram_text)

    debug_info = {
        "section_weights": section_weights,
        "score_weights": score_weights,
        "candidate": _candidate_to_dict(candidate),
    }
    print(json.dumps(debug_info, indent=2))

if __name__ == "__main__":
    main()
