"""Monte Carlo simulation for optimising OpenAI Assistant configuration.

This script samples assistant configuration parameters (model, prompting,
retrieval stack, safety settings) and scores them against the criteria for a
"quality assistant" in the JD assessor domain. It aggregates results over many
iterations to surface Pareto-favourable configurations and feature patterns.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

MODEL_PROFILES: Dict[str, Dict[str, float]] = {
    "gpt-4.1": {
        "domain_strength": 0.95,
        "cost_per_million": 30.0,
        "context": 128_000,
        "latency": 0.65,
    },
    "gpt-4.1-mini": {
        "domain_strength": 0.78,
        "cost_per_million": 3.0,
        "context": 64_000,
        "latency": 0.4,
    },
    "gpt-4o": {
        "domain_strength": 0.92,
        "cost_per_million": 15.0,
        "context": 128_000,
        "latency": 0.55,
    },
    "gpt-4o-mini": {
        "domain_strength": 0.80,
        "cost_per_million": 6.0,
        "context": 100_000,
        "latency": 0.45,
    },
    "gpt-4.1-nano": {
        "domain_strength": 0.60,
        "cost_per_million": 1.5,
        "context": 32_000,
        "latency": 0.35,
    },
}

SYSTEM_PROMPTS: Tuple[str, ...] = (
    "minimal",
    "assessor_persona",
    "assessor_with_rubric",
    "assessor_plus_operational_policies",
)

RETRIEVAL_OPTIONS: Tuple[str, ...] = (
    "none",
    "local_vector",
    "cloud_vector",
    "hybrid",
)

TOOLS_POOL: Tuple[str, ...] = (
    "case_search",
    "statute_lookup",
    "notes_lookup",
    "citation_verifier",
    "grading_scoring",
    "hypo_generator",
)

GUARDRAIL_POOL: Tuple[str, ...] = (
    "confidence_gate",
    "hallucination_check",
    "citation_validation",
    "fallback_to_human",
)

CACHE_STRATEGIES: Tuple[str, ...] = (
    "none",
    "request_level",
    "embedding_level",
    "hybrid",
)

RESPONSE_FORMATS: Tuple[str, ...] = (
    "text",
    "json_schema",
    "markdown_sections",
)

PARETO_HEAP_SIZE = 1500


@dataclass(frozen=True)
class Configuration:
    model: str
    temperature: float
    top_p: float
    presence_penalty: float
    frequency_penalty: float
    retrieval: str
    tools: Tuple[str, ...]
    system_prompt: str
    chain_of_thought: bool
    self_reflection: bool
    rubric_embedding: bool
    guardrails: Tuple[str, ...]
    confidence_threshold: float
    response_format: str
    max_context_tokens: int
    caching_strategy: str
    streaming: bool

    def to_signature(self) -> str:
        tool_set = ", ".join(self.tools) if self.tools else "no tools"
        guardrail_set = ", ".join(self.guardrails) if self.guardrails else "no guardrails"
        return (
            f"model={self.model} | temp={self.temperature:.2f} | top_p={self.top_p:.2f} | "
            f"retrieval={self.retrieval} | tools=[{tool_set}] | system={self.system_prompt} | "
            f"cot={self.chain_of_thought} | self_reflect={self.self_reflection} | "
            f"rubric={self.rubric_embedding} | guardrails=[{guardrail_set}] | "
            f"conf_thresh={self.confidence_threshold:.2f} | format={self.response_format} | "
            f"ctx={self.max_context_tokens} | cache={self.caching_strategy} | streaming={self.streaming}"
        )


@dataclass
class ScoreBreakdown:
    domain_alignment: float
    retrieval_strength: float
    alignment_fidelity: float
    reliability_cost: float
    efficiency: float

    @property
    def total(self) -> float:
        return (
            0.32 * self.domain_alignment
            + 0.24 * self.retrieval_strength
            + 0.20 * self.alignment_fidelity
            + 0.14 * self.reliability_cost
            + 0.10 * self.efficiency
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monte Carlo optimiser for OpenAI Assistant configurations",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=150_000,
        help="Number of Monte Carlo iterations (default: 150000)",
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
        default=0.02,
        help="Fraction of top-scoring configurations to aggregate (default: 0.02)",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        default=None,
        help="Optional CSV path for top template summary",
    )
    parser.add_argument(
        "--export-json",
        type=Path,
        default=None,
        help="Optional JSON path for top template summary",
    )
    return parser.parse_args()


def simulate_configuration(rng: random.Random) -> Tuple[Configuration, ScoreBreakdown]:
    model = rng.choices(tuple(MODEL_PROFILES), weights=(4, 5, 3, 6, 2), k=1)[0]
    temperature = rng.uniform(0.05, 0.85)
    top_p = rng.uniform(0.75, 1.0)
    presence_penalty = rng.uniform(-0.2, 0.6)
    frequency_penalty = rng.uniform(-0.2, 0.6)
    retrieval = rng.choices(RETRIEVAL_OPTIONS, weights=(1, 3, 3, 6), k=1)[0]
    tools = sample_subset(rng, TOOLS_POOL, min_items=2, max_items=5)
    system_prompt = rng.choices(
        SYSTEM_PROMPTS,
        weights=(1, 4, 5, 3),
        k=1,
    )[0]
    chain_of_thought = rng.random() < 0.55
    self_reflection = rng.random() < 0.65
    rubric_embedding = rng.random() < 0.72
    guardrails = sample_subset(rng, GUARDRAIL_POOL, min_items=1, max_items=4)
    confidence_threshold = rng.uniform(0.6, 0.95)
    response_format = rng.choices(
        RESPONSE_FORMATS,
        weights=(2, 1, 3),
        k=1,
    )[0]
    max_context_tokens = rng.choice([24_000, 32_000, 48_000, 64_000, 96_000])
    caching_strategy = rng.choices(
        CACHE_STRATEGIES,
        weights=(1, 3, 3, 2),
        k=1,
    )[0]
    streaming = rng.random() < 0.5

    config = Configuration(
        model=model,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        retrieval=retrieval,
        tools=tools,
        system_prompt=system_prompt,
        chain_of_thought=chain_of_thought,
        self_reflection=self_reflection,
        rubric_embedding=rubric_embedding,
        guardrails=guardrails,
        confidence_threshold=confidence_threshold,
        response_format=response_format,
        max_context_tokens=max_context_tokens,
        caching_strategy=caching_strategy,
        streaming=streaming,
    )

    breakdown = score_configuration(config)
    return config, breakdown


def sample_subset(
    rng: random.Random,
    population: Sequence[str],
    *,
    min_items: int,
    max_items: int,
) -> Tuple[str, ...]:
    size = rng.randint(min_items, min(max_items, len(population)))
    return tuple(sorted(rng.sample(population, size)))


def score_configuration(config: Configuration) -> ScoreBreakdown:
    return ScoreBreakdown(
        domain_alignment=score_domain_alignment(config),
        retrieval_strength=score_retrieval(config),
        alignment_fidelity=score_alignment(config),
        reliability_cost=score_reliability_cost(config),
        efficiency=score_efficiency(config),
    )


def score_domain_alignment(config: Configuration) -> float:
    profile = MODEL_PROFILES[config.model]
    base = profile["domain_strength"]
    prompt_bonus = {
        "minimal": -0.15,
        "assessor_persona": 0.05,
        "assessor_with_rubric": 0.12,
        "assessor_plus_operational_policies": 0.16,
    }[config.system_prompt]
    rubric_bonus = 0.08 if config.rubric_embedding else -0.05
    cot_bonus = 0.04 if config.chain_of_thought else 0.0
    self_reflect_bonus = 0.05 if config.self_reflection else -0.03
    retrieval_bonus = {
        "none": -0.2,
        "local_vector": 0.05,
        "cloud_vector": 0.06,
        "hybrid": 0.1,
    }[config.retrieval]
    raw = base + prompt_bonus + rubric_bonus + cot_bonus + self_reflect_bonus + retrieval_bonus
    return clamp(raw, 0.0, 1.0)


def score_retrieval(config: Configuration) -> float:
    retrieval_base = {
        "none": 0.05,
        "local_vector": 0.55,
        "cloud_vector": 0.60,
        "hybrid": 0.78,
    }[config.retrieval]
    tool_bonus = 0.0
    if "case_search" in config.tools:
        tool_bonus += 0.08
    if "statute_lookup" in config.tools:
        tool_bonus += 0.07
    if "notes_lookup" in config.tools:
        tool_bonus += 0.04
    if "citation_verifier" in config.tools:
        tool_bonus += 0.06
    redundancy_penalty = 0.04 if len(config.tools) <= 2 else 0.0
    guardrail_bonus = 0.03 if "citation_validation" in config.guardrails else 0.0
    raw = retrieval_base + tool_bonus + guardrail_bonus - redundancy_penalty
    return clamp(raw, 0.0, 1.0)


def score_alignment(config: Configuration) -> float:
    base = 0.5 if config.rubric_embedding else 0.32
    if config.system_prompt in {"assessor_with_rubric", "assessor_plus_operational_policies"}:
        base += 0.12
    if config.chain_of_thought:
        base += 0.05
    if config.self_reflection:
        base += 0.07
    guardrail_bonus = 0.03 * len(config.guardrails)
    format_bonus = 0.05 if config.response_format != "text" else 0.0
    raw = base + guardrail_bonus + format_bonus
    return clamp(raw, 0.0, 1.0)


def score_reliability_cost(config: Configuration) -> float:
    profile = MODEL_PROFILES[config.model]
    cost = profile["cost_per_million"]
    latency = profile["latency"]
    temperature_penalty = abs(config.temperature - 0.25) * 0.4
    top_p_penalty = max(0.0, (config.top_p - 0.9)) * 0.6
    penalty = temperature_penalty + top_p_penalty

    guardrail_bonus = 0.04 * len(config.guardrails)
    confidence_bonus = 0.1 * (config.confidence_threshold - 0.6)
    streaming_bonus = 0.05 if config.streaming else 0.0
    caching_bonus = {
        "none": -0.05,
        "request_level": 0.05,
        "embedding_level": 0.06,
        "hybrid": 0.08,
    }[config.caching_strategy]

    cost_factor = 1.0 - clamp(cost / 35.0, 0.0, 1.0)
    latency_factor = 1.0 - clamp(latency, 0.0, 1.0)

    raw = 0.35 * cost_factor + 0.25 * latency_factor + guardrail_bonus + confidence_bonus + streaming_bonus + caching_bonus - penalty
    return clamp(raw, 0.0, 1.0)


def score_efficiency(config: Configuration) -> float:
    context_score = 1.0 - clamp((config.max_context_tokens - 24_000) / 100_000, 0.0, 1.0)
    if config.retrieval == "none":
        context_score -= 0.1
    tool_count_penalty = 0.03 * max(0, len(config.tools) - 4)
    format_bonus = 0.04 if config.response_format == "json_schema" else 0.02 if config.response_format == "markdown_sections" else 0.0
    raw = context_score + format_bonus - tool_count_penalty
    return clamp(raw, 0.0, 1.0)


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def run_simulation(
    iterations: int,
    rng: random.Random,
    top_fraction: float,
) -> Dict[str, object]:
    scores: List[float] = []
    configs: List[Configuration] = []
    breakdowns: List[ScoreBreakdown] = []
    top_heap: List[Tuple[float, Configuration, ScoreBreakdown]] = []

    for _ in range(iterations):
        config, breakdown = simulate_configuration(rng)
        total_score = breakdown.total
        scores.append(total_score)
        configs.append(config)
        breakdowns.append(breakdown)
        if len(top_heap) < PARETO_HEAP_SIZE:
            heapq.heappush(top_heap, (total_score, config, breakdown))
        else:
            if total_score > top_heap[0][0]:
                heapq.heapreplace(top_heap, (total_score, config, breakdown))

    mean_score = statistics.mean(scores)
    best_score, best_config, best_breakdown = max(
        zip(scores, configs, breakdowns),
        key=lambda item: item[0],
    )

    threshold_index = max(1, int(len(scores) * (1.0 - top_fraction)))
    threshold = sorted(scores)[threshold_index]

    top_templates = aggregate_top_templates(scores, configs, breakdowns, threshold)
    feature_summary = aggregate_feature_preferences(top_heap)

    return {
        "mean_score": mean_score,
        "best_score": best_score,
        "best_config": best_config,
        "best_breakdown": best_breakdown,
        "scores": scores,
        "top_heap": sorted(top_heap, key=lambda item: item[0], reverse=True),
        "top_templates": top_templates,
        "feature_summary": feature_summary,
    }


def aggregate_top_templates(
    scores: Sequence[float],
    configs: Sequence[Configuration],
    breakdowns: Sequence[ScoreBreakdown],
    threshold: float,
) -> List[Tuple[str, Dict[str, float]]]:
    template_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "count": 0,
        "mean_score": 0.0,
        "mean_domain": 0.0,
        "mean_retrieval": 0.0,
        "mean_alignment": 0.0,
        "mean_reliability": 0.0,
        "mean_efficiency": 0.0,
    })

    for score, cfg, brk in zip(scores, configs, breakdowns):
        if score < threshold:
            continue
        signature = cfg.to_signature()
        stats = template_stats[signature]
        stats["count"] += 1
        stats["mean_score"] += score
        stats["mean_domain"] += brk.domain_alignment
        stats["mean_retrieval"] += brk.retrieval_strength
        stats["mean_alignment"] += brk.alignment_fidelity
        stats["mean_reliability"] += brk.reliability_cost
        stats["mean_efficiency"] += brk.efficiency

    for stats in template_stats.values():
        count = stats["count"]
        if count:
            stats["mean_score"] /= count
            stats["mean_domain"] /= count
            stats["mean_retrieval"] /= count
            stats["mean_alignment"] /= count
            stats["mean_reliability"] /= count
            stats["mean_efficiency"] /= count

    return sorted(
        template_stats.items(),
        key=lambda item: (item[1]["mean_score"], item[1]["count"]),
        reverse=True,
    )[:12]


def aggregate_feature_preferences(
    top_heap: Sequence[Tuple[float, Configuration, ScoreBreakdown]],
) -> Dict[str, List[Tuple[str, int]]]:
    model_counts: Counter[str] = Counter()
    system_counts: Counter[str] = Counter()
    retrieval_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    guardrail_counts: Counter[str] = Counter()

    for _, cfg, _ in top_heap:
        model_counts[cfg.model] += 1
        system_counts[cfg.system_prompt] += 1
        retrieval_counts[cfg.retrieval] += 1
        for tool in cfg.tools:
            tool_counts[tool] += 1
        for guardrail in cfg.guardrails:
            guardrail_counts[guardrail] += 1

    return {
        "models": model_counts.most_common(5),
        "system_prompts": system_counts.most_common(5),
        "retrieval": retrieval_counts.most_common(5),
        "tools": tool_counts.most_common(6),
        "guardrails": guardrail_counts.most_common(6),
    }


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
                    "signature",
                    "count",
                    "mean_score",
                    "mean_domain",
                    "mean_retrieval",
                    "mean_alignment",
                    "mean_reliability",
                    "mean_efficiency",
                ]
            )
            for idx, (signature, stats) in enumerate(templates, start=1):
                writer.writerow(
                    [
                        idx,
                        signature,
                        stats["count"],
                        f"{stats['mean_score']:.6f}",
                        f"{stats['mean_domain']:.6f}",
                        f"{stats['mean_retrieval']:.6f}",
                        f"{stats['mean_alignment']:.6f}",
                        f"{stats['mean_reliability']:.6f}",
                        f"{stats['mean_efficiency']:.6f}",
                    ]
                )

    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for idx, (signature, stats) in enumerate(templates, start=1):
            payload.append(
                {
                    "rank": idx,
                    "signature": signature,
                    **stats,
                }
            )
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def describe_distribution(scores: Sequence[float]) -> str:
    percentiles = [5, 25, 50, 75, 90, 95, 99]
    values = statistics.quantiles(scores, n=100)
    percentile_map = {i + 1: values[i] for i in range(99)}
    lines = []
    for pct in percentiles:
        lines.append(f"  {pct:>3}th percentile: {percentile_map[pct]:.4f}")
    return "\n".join(lines)


def format_breakdown(label: str, breakdown: ScoreBreakdown) -> str:
    return (
        f"{label}: {breakdown.total:.4f} (Domain: {breakdown.domain_alignment:.4f}, "
        f"Retrieval: {breakdown.retrieval_strength:.4f}, Alignment: {breakdown.alignment_fidelity:.4f}, "
        f"Reliability/Cost: {breakdown.reliability_cost:.4f}, Efficiency: {breakdown.efficiency:.4f})"
    )


def print_summary(summary: Dict[str, object]) -> None:
    scores: List[float] = summary["scores"]  # type: ignore[assignment]
    best_config: Configuration = summary["best_config"]  # type: ignore[assignment]
    best_breakdown: ScoreBreakdown = summary["best_breakdown"]  # type: ignore[assignment]
    top_heap: List[Tuple[float, Configuration, ScoreBreakdown]] = summary["top_heap"]  # type: ignore[assignment]
    top_templates = cast(List[Tuple[str, Dict[str, float]]], summary["top_templates"])
    feature_summary = cast(Dict[str, List[Tuple[str, int]]], summary["feature_summary"])

    print("OpenAI Assistant Configuration Monte Carlo Optimisation")
    print("=====================================================")
    print(f"Iterations: {len(scores):,}")
    print(f"Mean score: {summary['mean_score']:.4f}")
    print(format_breakdown("Best score", best_breakdown))
    print(f"Best configuration: {best_config.to_signature()}")

    print("\nScore distribution (percentiles):")
    print(describe_distribution(scores))

    print("\nTop-performing samples:")
    for idx, (score, cfg, breakdown) in enumerate(top_heap[:5], start=1):
        print(f"[{idx}] {score:.4f} :: {cfg.to_signature()}")
        print(f"      {format_breakdown('Components', breakdown)}")

    print("\nRepeated high-performing templates:")
    for signature, stats in top_templates:
        print(f"- {signature}")
        print(
            f"  Count: {stats['count']}, Mean score: {stats['mean_score']:.4f}, Domain: {stats['mean_domain']:.4f}, "
            f"Retrieval: {stats['mean_retrieval']:.4f}, Alignment: {stats['mean_alignment']:.4f}, "
            f"Reliability: {stats['mean_reliability']:.4f}, Efficiency: {stats['mean_efficiency']:.4f}"
        )

    print("\nFeature prevalence within Pareto set:")
    for label, items in feature_summary.items():
        print(f"  {label}:")
        for name, count in items:  # type: ignore[assignment]
            print(f"    - {name}: {count}")


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    summary = run_simulation(args.iterations, rng, args.top_fraction)
    print_summary(summary)
    top_templates = cast(List[Tuple[str, Dict[str, float]]], summary["top_templates"])
    export_top_templates(top_templates, args.export_csv, args.export_json)


if __name__ == "__main__":
    main()
