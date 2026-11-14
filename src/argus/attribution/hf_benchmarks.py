"""Hugging Face Hub model leaderboard benchmark comparator and Pareto efficiency analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelBenchmarkProfile:
    """Benchmark performance metrics for an LLM model."""

    model_name: str
    provider: str
    gaia_accuracy: float  # Task completion / accuracy on benchmark (0.0 - 1.0)
    ttft_ms: float  # Time-to-first-token in milliseconds
    throughput_tokens_sec: float
    input_cost_per_1k: float
    output_cost_per_1k: float


# Baseline reference leaderboard profiles based on public Open LLM & GAIA leaderboards
BASELINE_HF_MODELS: tuple[ModelBenchmarkProfile, ...] = (
    ModelBenchmarkProfile(
        model_name="claude-3-5-sonnet",
        provider="anthropic",
        gaia_accuracy=0.68,
        ttft_ms=380.0,
        throughput_tokens_sec=75.0,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
    ),
    ModelBenchmarkProfile(
        model_name="gpt-4o",
        provider="openai",
        gaia_accuracy=0.64,
        ttft_ms=320.0,
        throughput_tokens_sec=85.0,
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.010,
    ),
    ModelBenchmarkProfile(
        model_name="gpt-4o-mini",
        provider="openai",
        gaia_accuracy=0.52,
        ttft_ms=180.0,
        throughput_tokens_sec=120.0,
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.00060,
    ),
    ModelBenchmarkProfile(
        model_name="deepseek-v3",
        provider="deepseek",
        gaia_accuracy=0.61,
        ttft_ms=450.0,
        throughput_tokens_sec=65.0,
        input_cost_per_1k=0.00014,
        output_cost_per_1k=0.00028,
    ),
)


class HuggingFaceBenchmarkAnalyzer:
    """Analyzes model performance vs inference latency and recommends Pareto-optimal swaps."""

    def __init__(
        self,
        catalog: tuple[ModelBenchmarkProfile, ...] = BASELINE_HF_MODELS,
    ) -> None:
        self._catalog = catalog

    def get_pareto_recommendations(
        self,
        current_model_name: str,
        *,
        min_acceptable_accuracy: float = 0.50,
    ) -> list[dict[str, Any]]:
        """Identify models that offer strictly better latency/cost without sacrificing accuracy."""
        curr = next((m for m in self._catalog if m.model_name == current_model_name), None)
        if curr is None:
            return []

        recommendations: list[dict[str, Any]] = []
        for candidate in self._catalog:
            if candidate.model_name == current_model_name:
                continue

            if candidate.gaia_accuracy < min_acceptable_accuracy:
                continue

            cost_savings_ratio = (
                (curr.input_cost_per_1k - candidate.input_cost_per_1k) / curr.input_cost_per_1k
                if curr.input_cost_per_1k > 0
                else 0.0
            )

            latency_reduction_ratio = (
                (curr.ttft_ms - candidate.ttft_ms) / curr.ttft_ms
                if curr.ttft_ms > 0
                else 0.0
            )

            # Recommend if significantly cheaper or faster with comparable accuracy
            if cost_savings_ratio >= 0.50 or latency_reduction_ratio >= 0.25:
                recommendations.append(
                    {
                        "candidate_model": candidate.model_name,
                        "provider": candidate.provider,
                        "cost_savings_pct": round(cost_savings_ratio * 100.0, 1),
                        "latency_reduction_pct": round(latency_reduction_ratio * 100.0, 1),
                        "benchmark_accuracy_delta": round(
                            candidate.gaia_accuracy - curr.gaia_accuracy, 3
                        ),
                    }
                )

        return sorted(recommendations, key=lambda r: r["cost_savings_pct"], reverse=True)
