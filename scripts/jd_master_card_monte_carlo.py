"""Monte Carlo simulation to identify Pareto-optimal JD Master Card structures.

This script varies structural parameters for JD Master Cards across 500,000
iterations, scoring each configuration across three strategic dimensions:
exam utility, doctrinal compliance, and cognitive efficiency.

The simulation focuses on the sections and constraints required by the v2a
policy and synthesises findings aligned with high-yield JD exam preparation.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

SECTIONS: Tuple[str, ...] = (
    "Issue",
    "Rule",
    "Application scaffold",
    "Authorities map",
    "Statutory hook",
    "Tripwires",
    "Conclusion",
)

IDEAL_ORDER: Tuple[str, ...] = SECTIONS

TARGET_WORD_SHARE: Dict[str, float] = {
    "Issue": 0.12,
    "Rule": 0.18,
    "Application scaffold": 0.26,
    "Authorities map": 0.18,
    "Statutory hook": 0.10,
    "Tripwires": 0.08,
    "Conclusion": 0.08,
}

AUTHORITY_TYPES: Tuple[str, ...] = (
    "HCA",
    "State CA",
    "Other Aus",
    "UK/PC",
)

MAX_TOTAL_ORDER_DISTANCE = sum(abs(len(SECTIONS) - 1 - i) for i in range(len(SECTIONS)))
MIN_WORDS = 160
MAX_WORDS = 280
MIN_TRIPWIRES = 3
MAX_TRIPWIRES = 6
MIN_AUTHORITIES = 2
MAX_AUTHORITIES = 8
MIN_TOP_BRANCHES = 4
MAX_TOP_BRANCHES = 5
MAX_MINDMAP_NODES = 12
MIN_SECTION_WORDS = 18
PARETO_HEAP_SIZE = 2000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monte Carlo optimiser for JD Master Card structures",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=500_000,
        help="Number of Monte Carlo iterations (default: 500000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--top-fraction",
        type=float,
        default=0.01,
        help="Fraction of top-scoring configurations to analyse (default: 0.01)",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        default=None,
        help="Optional path to write top-template summary as CSV",
    )
    parser.add_argument(
        "--export-json",
        type=Path,
        default=None,
        help="Optional path to write top-template summary as JSON",
    )
    return parser.parse_args()


@dataclass(frozen=True)
class Configuration:
    order: Tuple[str, ...]
    allocations: Tuple[int, ...]
    total_words: int
    authority_mix: Tuple[int, int, int, int]
    tripwires: int
    top_branches: int
    branch_nodes: Tuple[int, ...]

    def to_template_signature(self) -> str:
        branch_descriptor = "/".join(str(n) for n in self.branch_nodes)
        authority_summary = ", ".join(
            f"{count} {atype}" for count, atype in zip(self.authority_mix, AUTHORITY_TYPES) if count
        )
        if not authority_summary:
            authority_summary = "0 authorities"
        return (
            f"{' → '.join(self.order)} | {self.total_words} words | "
            f"Tripwires: {self.tripwires} | Authorities: {authority_summary} | "
            f"Mindmap branches: {self.top_branches} ({branch_descriptor})"
        )


@dataclass
class ScoreBreakdown:
    exam_utility: float
    doctrinal_compliance: float
    cognitive_efficiency: float

    @property
    def total(self) -> float:
        return (
            0.45 * self.exam_utility
            + 0.35 * self.doctrinal_compliance
            + 0.20 * self.cognitive_efficiency
        )


def simulate_configuration(rng: random.Random) -> Tuple[Configuration, ScoreBreakdown]:
    order = tuple(rng.sample(SECTIONS, len(SECTIONS)))
    total_words = rng.randint(MIN_WORDS, MAX_WORDS)
    allocations = allocate_words(order, total_words, rng)
    authority_mix = sample_authority_mix(rng)
    tripwires = rng.randint(MIN_TRIPWIRES, MAX_TRIPWIRES)
    top_branches, branch_nodes = sample_mindmap_structure(rng)
    config = Configuration(
        order=order,
        allocations=allocations,
        total_words=total_words,
        authority_mix=authority_mix,
        tripwires=tripwires,
        top_branches=top_branches,
        branch_nodes=branch_nodes,
    )
    breakdown = score_configuration(config)
    return config, breakdown


def allocate_words(order: Sequence[str], total_words: int, rng: random.Random) -> Tuple[int, ...]:
    weights = [rng.gammavariate(2.4, 1.0) for _ in order]
    sum_weights = sum(weights)
    raw_allocations = [max(MIN_SECTION_WORDS, int(round(total_words * w / sum_weights))) for w in weights]
    difference = total_words - sum(raw_allocations)
    if difference != 0:
        adjust_allocations(raw_allocations, difference, rng)
    return tuple(raw_allocations)


def adjust_allocations(allocations: List[int], difference: int, rng: random.Random) -> None:
    indexes = list(range(len(allocations)))
    rng.shuffle(indexes)
    step = 1 if difference > 0 else -1
    remaining = abs(difference)
    idx_pos = 0
    while remaining > 0:
        idx = indexes[idx_pos]
        if step < 0 and allocations[idx] <= MIN_SECTION_WORDS:
            idx_pos = (idx_pos + 1) % len(indexes)
            continue
        allocations[idx] += step
        remaining -= 1
        idx_pos = (idx_pos + 1) % len(indexes)
        if idx_pos == 0:
            rng.shuffle(indexes)


def sample_authority_mix(rng: random.Random) -> Tuple[int, int, int, int]:
    total_authorities = rng.randint(MIN_AUTHORITIES, MAX_AUTHORITIES)
    base_probs = [0.5, 0.25, 0.15, 0.10]
    weights = [rng.gammavariate(1 + p * 4, 1.0) for p in base_probs]
    total_weight = sum(weights)
    shares = [w / total_weight for w in weights]
    counts = [0, 0, 0, 0]
    for _ in range(total_authorities):
        choice = rng.random()
        cumulative = 0.0
        for idx, share in enumerate(shares):
            cumulative += share
            if choice <= cumulative:
                counts[idx] += 1
                break
    # Ensure at least one HCA authority to reflect high-yield discipline
    if counts[0] == 0:
        weakest_idx = max(range(1, len(counts)), key=lambda i: counts[i])
        if counts[weakest_idx] > 0:
            counts[weakest_idx] -= 1
            counts[0] += 1
    return cast(Tuple[int, int, int, int], tuple(counts))


def sample_mindmap_structure(rng: random.Random) -> Tuple[int, Tuple[int, ...]]:
    top_branches = rng.randint(MIN_TOP_BRANCHES, MAX_TOP_BRANCHES)
    remaining_nodes = MAX_MINDMAP_NODES - 1  # subtract root node
    allocations = [1] * top_branches  # each branch at least one child node
    remaining_nodes -= top_branches
    if remaining_nodes > 0:
        branch_indexes = list(range(top_branches))
        for _ in range(remaining_nodes):
            idx = rng.choice(branch_indexes)
            allocations[idx] += 1
    return top_branches, tuple(allocations)


def score_configuration(config: Configuration) -> ScoreBreakdown:
    exam_score = score_exam_utility(config)
    doctrinal_score = score_doctrinal_compliance(config)
    cognitive_score = score_cognitive_efficiency(config)
    return ScoreBreakdown(exam_score, doctrinal_score, cognitive_score)


def score_exam_utility(config: Configuration) -> float:
    word_target = 230
    word_band = (MAX_WORDS - MIN_WORDS) / 2
    word_score = 1.0 - min(abs(config.total_words - word_target) / word_band, 1.0)
    tripwire_target = 4.5
    tripwire_score = 1.0 - min(abs(config.tripwires - tripwire_target) / 2.5, 1.0)
    authority_count = sum(config.authority_mix)
    authority_target = 5
    authority_score = 1.0 - min(abs(authority_count - authority_target) / authority_target, 1.0)
    balance_weight = 0.5
    composite = (
        0.45 * word_score
        + 0.30 * authority_score
        + 0.25 * tripwire_score
    )
    return balance_weight + (1 - balance_weight) * composite


def score_doctrinal_compliance(config: Configuration) -> float:
    order_positions = {name: idx for idx, name in enumerate(config.order)}
    order_distance = sum(abs(order_positions[name] - idx) for idx, name in enumerate(IDEAL_ORDER))
    order_score = 1.0 - min(order_distance / MAX_TOTAL_ORDER_DISTANCE, 1.0)

    authority_count = sum(config.authority_mix)
    density_score = 1.0 - min(abs(authority_count - 5) / 4.0, 1.0)

    mix_weights = [0.5, 0.3, 0.15, 0.05]
    mix_score = 0.0
    for count, weight in zip(config.authority_mix, mix_weights):
        mix_score += min(count / max(1, authority_count), weight * 2)
    mix_score = min(mix_score, 1.0)

    uk_penalty = 0.0
    if config.authority_mix[3] > 0:
        uk_penalty = min(config.authority_mix[3] / authority_count, 0.25)

    statutory_weight = 0.2 + 0.05 * (config.total_words > 210)
    doctrinal = (
        0.55 * order_score
        + 0.25 * density_score
        + 0.15 * mix_score
        + 0.05 * statutory_weight
    )
    doctrinal = max(0.0, doctrinal - uk_penalty)
    return doctrinal


def score_cognitive_efficiency(config: Configuration) -> float:
    shares = [alloc / config.total_words for alloc in config.allocations]
    target_vector = [TARGET_WORD_SHARE[name] for name in config.order]
    divergence = sum(abs(a - b) for a, b in zip(shares, target_vector))
    distribution_score = 1.0 - min(divergence / 2.0, 1.0)

    branch_evenness = statistics.pstdev(config.branch_nodes) if len(config.branch_nodes) > 1 else 0.0
    branch_score = 1.0 - min(branch_evenness / 3.0, 1.0)

    tripwire_penalty = 0.0
    if config.tripwires == MIN_TRIPWIRES or config.tripwires == MAX_TRIPWIRES:
        tripwire_penalty = 0.1

    cognitive = max(0.0, 0.6 * distribution_score + 0.4 * branch_score - tripwire_penalty)
    return cognitive


def run_simulation(iterations: int, rng: random.Random, top_fraction: float) -> Dict[str, object]:
    scores: List[float] = []
    breakdowns: List[ScoreBreakdown] = []
    configurations: List[Configuration] = []
    top_heap: List[Tuple[float, Configuration, ScoreBreakdown]] = []

    for _ in range(iterations):
        config, breakdown = simulate_configuration(rng)
        total_score = breakdown.total
        scores.append(total_score)
        breakdowns.append(breakdown)
        configurations.append(config)
        if len(top_heap) < PARETO_HEAP_SIZE:
            heapq.heappush(top_heap, (total_score, config, breakdown))
        else:
            if total_score > top_heap[0][0]:
                heapq.heapreplace(top_heap, (total_score, config, breakdown))

    mean_score = statistics.mean(scores)
    best_score, best_config, best_breakdown = max(
        zip(scores, configurations, breakdowns), key=lambda item: item[0]
    )

    top_cutoff_index = max(1, int(len(scores) * (1.0 - top_fraction)))
    threshold = sorted(scores)[top_cutoff_index]

    top_templates = aggregate_top_templates(
        scores,
        configurations,
        breakdowns,
        threshold,
    )

    summary = {
        "mean_score": mean_score,
        "best_score": best_score,
        "best_configuration": best_config,
        "best_breakdown": best_breakdown,
        "scores": scores,
        "top_heap": sorted(top_heap, key=lambda item: item[0], reverse=True),
        "top_templates": top_templates,
    }
    return summary


def aggregate_top_templates(
    scores: Sequence[float],
    configs: Sequence[Configuration],
    breakdowns: Sequence[ScoreBreakdown],
    threshold: float,
) -> List[Tuple[str, Dict[str, float]]]:
    template_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "count": 0,
        "mean_score": 0.0,
        "mean_exam": 0.0,
        "mean_doctrinal": 0.0,
        "mean_cognitive": 0.0,
    })

    for score, config, breakdown in zip(scores, configs, breakdowns):
        if score < threshold:
            continue
        signature = config.to_template_signature()
        stats = template_stats[signature]
        stats["count"] += 1
        stats["mean_score"] += score
        stats["mean_exam"] += breakdown.exam_utility
        stats["mean_doctrinal"] += breakdown.doctrinal_compliance
        stats["mean_cognitive"] += breakdown.cognitive_efficiency

    for stats in template_stats.values():
        count = stats["count"]
        if count:
            stats["mean_score"] /= count
            stats["mean_exam"] /= count
            stats["mean_doctrinal"] /= count
            stats["mean_cognitive"] /= count
    ranked = sorted(
        template_stats.items(),
        key=lambda item: (item[1]["mean_score"], item[1]["count"]),
        reverse=True,
    )
    return ranked[:10]


def export_top_templates(
    templates: Sequence[Tuple[str, Dict[str, float]]],
    csv_path: Path | None,
    json_path: Path | None,
) -> None:
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "rank",
                    "template_signature",
                    "count",
                    "mean_score",
                    "mean_exam",
                    "mean_doctrinal",
                    "mean_cognitive",
                ]
            )
            for idx, (signature, stats) in enumerate(templates, start=1):
                writer.writerow(
                    [
                        idx,
                        signature,
                        stats["count"],
                        f"{stats['mean_score']:.6f}",
                        f"{stats['mean_exam']:.6f}",
                        f"{stats['mean_doctrinal']:.6f}",
                        f"{stats['mean_cognitive']:.6f}",
                    ]
                )

    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_payload = []
        for idx, (signature, stats) in enumerate(templates, start=1):
            json_payload.append(
                {
                    "rank": idx,
                    "template_signature": signature,
                    "count": stats["count"],
                    "mean_score": stats["mean_score"],
                    "mean_exam": stats["mean_exam"],
                    "mean_doctrinal": stats["mean_doctrinal"],
                    "mean_cognitive": stats["mean_cognitive"],
                }
            )
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(json_payload, handle, indent=2)


def describe_distribution(scores: Sequence[float]) -> str:
    percentiles = [5, 25, 50, 75, 90, 95, 99]
    values = statistics.quantiles(scores, n=100)
    percentile_map = {p: values[p - 1] for p in range(1, 100)}
    lines = []
    for pct in percentiles:
        lines.append(f"  {pct:>3}th percentile: {percentile_map[pct]:.4f}")
    return "\n".join(lines)


def format_breakdown(label: str, breakdown: ScoreBreakdown) -> str:
    return (
        f"{label}: {breakdown.total:.4f} (Exam: {breakdown.exam_utility:.4f}, "
        f"Doctrinal: {breakdown.doctrinal_compliance:.4f}, "
        f"Cognitive: {breakdown.cognitive_efficiency:.4f})"
    )


def print_summary(summary: Dict[str, object]) -> None:
    scores: List[float] = summary["scores"]  # type: ignore[assignment]
    best_config: Configuration = summary["best_configuration"]  # type: ignore[assignment]
    best_breakdown: ScoreBreakdown = summary["best_breakdown"]  # type: ignore[assignment]
    top_heap: List[Tuple[float, Configuration, ScoreBreakdown]] = summary["top_heap"]  # type: ignore[assignment]
    top_templates: List[Tuple[str, Dict[str, float]]] = summary["top_templates"]  # type: ignore[assignment]

    print("JD Master Card Monte Carlo Optimisation")
    print("======================================")
    print(f"Iterations: {len(scores):,}")
    print(f"Mean score: {summary['mean_score']:.4f}")
    print(format_breakdown("Best score", best_breakdown))
    print(f"Best template: {best_config.to_template_signature()}")
    print("\nScore distribution (percentiles):")
    print(describe_distribution(scores))

    print("\nTop-performing configurations (sample):")
    for rank, (score, config, breakdown) in enumerate(top_heap[:5], start=1):
        print(f"[{rank}] {score:.4f} :: {config.to_template_signature()}")
        print(f"      {format_breakdown('Components', breakdown)}")

    print("\nRepeated high-performing templates:")
    for signature, stats in top_templates:
        print(f"- {signature}")
        print(
            f"  Count: {stats['count']}, Mean score: {stats['mean_score']:.4f}, "
            f"Exam: {stats['mean_exam']:.4f}, Doctrinal: {stats['mean_doctrinal']:.4f}, "
            f"Cognitive: {stats['mean_cognitive']:.4f}"
        )


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    summary = run_simulation(args.iterations, rng, args.top_fraction)
    print_summary(summary)
    templates: List[Tuple[str, Dict[str, float]]] = summary["top_templates"]  # type: ignore[assignment]
    export_top_templates(templates, args.export_csv, args.export_json)


if __name__ == "__main__":
    main()
