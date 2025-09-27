import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Tuple

TOKEN_PRICE_PER_1K_IN = 0.12  # USD
TOKEN_PRICE_PER_1K_OUT = 0.12  # USD


def _clamp_positive(value: float) -> float:
    return max(0.0, value)


def _draw_gaussian(mean: float, stdev: float) -> float:
    if stdev <= 0:
        return mean
    return _clamp_positive(random.gauss(mean, stdev))


@dataclass
class Strategy:
    """Configuration for a single-pass or multi-pass prompting strategy."""

    name: str
    cases: int
    prompt_tokens_mean: float
    prompt_tokens_sd: float
    completion_tokens_mean: float
    completion_tokens_sd: float
    failure_rate: float = 0.05
    max_retries: int = 1
    coverage_mean: float = 0.85
    coverage_sd: float = 0.05
    verifier_calls_per_case: float = 0.0
    verifier_prompt_tokens: float = 0.0
    verifier_prompt_sd: float = 0.0
    verifier_completion_tokens: float = 0.0
    verifier_completion_sd: float = 0.0

    def draw_case_tokens(self) -> Tuple[float, float]:
        prompt = _draw_gaussian(self.prompt_tokens_mean, self.prompt_tokens_sd)
        completion = _draw_gaussian(self.completion_tokens_mean, self.completion_tokens_sd)
        return prompt, completion

    def draw_verifier_tokens(self) -> Tuple[float, float]:
        prompt = _draw_gaussian(self.verifier_prompt_tokens, self.verifier_prompt_sd)
        completion = _draw_gaussian(self.verifier_completion_tokens, self.verifier_completion_sd)
        return prompt, completion

    def draw_coverage(self) -> float:
        return min(1.0, max(0.0, random.gauss(self.coverage_mean, self.coverage_sd)))


@dataclass
class SimulationResult:
    name: str
    mean_cost: float
    p05_cost: float
    p95_cost: float
    budget_hit_rate: float
    mean_coverage: float
    p05_coverage: float
    p95_coverage: float
    mean_json_failures: float


def simulate(strategy: Strategy, runs: int = 5000, budget: float = 4.0) -> SimulationResult:
    costs: List[float] = []
    coverages: List[float] = []
    json_failures: List[float] = []

    for _ in range(runs):
        total_prompt_tokens = 0.0
        total_completion_tokens = 0.0
        verifier_prompt_tokens = 0.0
        verifier_completion_tokens = 0.0
        failures_this_run = 0

        for _case in range(strategy.cases):
            prompt_tokens, completion_tokens = strategy.draw_case_tokens()
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens

            retry_count = 0
            while random.random() < strategy.failure_rate and retry_count < strategy.max_retries:
                failures_this_run += 1
                retry_count += 1
                r_prompt, r_completion = strategy.draw_case_tokens()
                total_prompt_tokens += r_prompt
                total_completion_tokens += r_completion

            # verifier / secondary calls
            verifier_calls = strategy.verifier_calls_per_case
            whole_calls = int(verifier_calls)
            fractional_call = verifier_calls - whole_calls
            if fractional_call > 0 and random.random() < fractional_call:
                whole_calls += 1

            for _ in range(whole_calls):
                v_prompt, v_completion = strategy.draw_verifier_tokens()
                verifier_prompt_tokens += v_prompt
                verifier_completion_tokens += v_completion

        total_cost = (
            (total_prompt_tokens / 1000.0) * TOKEN_PRICE_PER_1K_IN
            + (total_completion_tokens / 1000.0) * TOKEN_PRICE_PER_1K_OUT
            + (verifier_prompt_tokens / 1000.0) * TOKEN_PRICE_PER_1K_IN
            + (verifier_completion_tokens / 1000.0) * TOKEN_PRICE_PER_1K_OUT
        )

        coverage = strategy.draw_coverage()
        costs.append(total_cost)
        coverages.append(coverage)
        json_failures.append(failures_this_run)

    costs_sorted = sorted(costs)
    coverages_sorted = sorted(coverages)

    def percentile(data: List[float], pct: float) -> float:
        if not data:
            return 0.0
        k = (len(data) - 1) * pct
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return data[int(k)]
        return data[f] * (c - k) + data[c] * (k - f)

    budget_hit_rate = sum(1 for v in costs if v <= budget) / len(costs) if costs else 0.0

    return SimulationResult(
        name=strategy.name,
        mean_cost=statistics.mean(costs) if costs else 0.0,
        p05_cost=percentile(costs_sorted, 0.05),
        p95_cost=percentile(costs_sorted, 0.95),
        budget_hit_rate=budget_hit_rate,
        mean_coverage=statistics.mean(coverages) if coverages else 0.0,
        p05_coverage=percentile(coverages_sorted, 0.05),
        p95_coverage=percentile(coverages_sorted, 0.95),
        mean_json_failures=statistics.mean(json_failures) if json_failures else 0.0,
    )


def run_default_scenarios(runs: int = 5000, budget: float = 4.0) -> List[SimulationResult]:
    strategies = [
        Strategy(
            name="Compact single-pass (current prompt)",
            cases=70,
            prompt_tokens_mean=1800,
            prompt_tokens_sd=250,
            completion_tokens_mean=190,
            completion_tokens_sd=30,
            failure_rate=0.08,
            max_retries=1,
            coverage_mean=0.78,
            coverage_sd=0.07,
        ),
        Strategy(
            name="Two-pass (Option A + verifier on 15 cases)",
            cases=70,
            prompt_tokens_mean=1500,
            prompt_tokens_sd=280,
            completion_tokens_mean=170,
            completion_tokens_sd=30,
            failure_rate=0.06,
            max_retries=1,
            coverage_mean=0.82,
            coverage_sd=0.05,
            verifier_calls_per_case=15 / 70,
            verifier_prompt_tokens=420,
            verifier_prompt_sd=80,
            verifier_completion_tokens=120,
            verifier_completion_sd=25,
        ),
        Strategy(
            name="Quality subset (20 cases Option B)",
            cases=20,
            prompt_tokens_mean=2600,
            prompt_tokens_sd=300,
            completion_tokens_mean=320,
            completion_tokens_sd=45,
            failure_rate=0.04,
            max_retries=1,
            coverage_mean=0.9,
            coverage_sd=0.03,
        ),
    ]

    return [simulate(strategy, runs=runs, budget=budget) for strategy in strategies]


def pretty_print(results: Iterable[SimulationResult]) -> None:
    for res in results:
        print(f"\n=== {res.name} ===")
        print(f"Mean cost: ${res.mean_cost:0.2f}")
        print(f"Cost 5th–95th percentile: ${res.p05_cost:0.2f} – ${res.p95_cost:0.2f}")
        print(f"Budget ≤$4 hit rate: {res.budget_hit_rate*100:0.1f}%")
        print(f"Mean coverage: {res.mean_coverage*100:0.1f}% (P5 {res.p05_coverage*100:0.1f}%, P95 {res.p95_coverage*100:0.1f}%)")
        print(f"Mean JSON retries per run: {res.mean_json_failures:0.2f}")


if __name__ == "__main__":
    random.seed(7)
    results = run_default_scenarios()
    pretty_print(results)
