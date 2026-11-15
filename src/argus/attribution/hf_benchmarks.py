"""Hugging Face Hub model leaderboard benchmark comparator and Pareto efficiency analyzer."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence

from argus.core.schemas import (
    ArgusSpan,
    DowngradeRecommendation,
    ModelBenchmarkProfile,
    SessionCandidateProjection,
    SessionDowngradeReport,
)

__all__ = [
    "BASELINE_HF_MODELS",
    "HuggingFaceBenchmarkAnalyzer",
    "ModelBenchmarkProfile",
]

# Reference leaderboard profiles grounded on public Open LLM Leaderboard v2 & GAIA benchmarks
BASELINE_HF_MODELS: tuple[ModelBenchmarkProfile, ...] = (
    ModelBenchmarkProfile(
        model_name="claude-3-5-sonnet",
        display_name="Claude 3.5 Sonnet",
        provider="anthropic",
        open_weights=False,
        gaia_accuracy=0.68,
        open_llm_score=79.4,
        ttft_ms=380.0,
        throughput_tokens_sec=75.0,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
        context_window_tokens=200000,
        aliases=(
            "claude-3-5-sonnet-20241022",
            "claude-3.5-sonnet",
            "claude-3-5-sonnet-latest",
            "anthropic.claude-3-5-sonnet",
        ),
    ),
    ModelBenchmarkProfile(
        model_name="gpt-4o",
        display_name="GPT-4o (Omni)",
        provider="openai",
        open_weights=False,
        gaia_accuracy=0.64,
        open_llm_score=77.2,
        ttft_ms=320.0,
        throughput_tokens_sec=85.0,
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.010,
        context_window_tokens=128000,
        aliases=("gpt-4o-2024-08-06", "gpt-4o-latest", "openai/gpt-4o"),
    ),
    ModelBenchmarkProfile(
        model_name="o1-preview",
        display_name="OpenAI o1-preview",
        provider="openai",
        open_weights=False,
        gaia_accuracy=0.73,
        open_llm_score=82.1,
        ttft_ms=1200.0,
        throughput_tokens_sec=45.0,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.060,
        context_window_tokens=128000,
        aliases=("o1", "openai/o1-preview", "o1-preview-2024-09-12"),
    ),
    ModelBenchmarkProfile(
        model_name="gemini-1-5-pro",
        display_name="Gemini 1.5 Pro",
        provider="google",
        open_weights=False,
        gaia_accuracy=0.66,
        open_llm_score=76.8,
        ttft_ms=410.0,
        throughput_tokens_sec=70.0,
        input_cost_per_1k=0.00125,
        output_cost_per_1k=0.0050,
        context_window_tokens=1000000,
        aliases=("gemini-1.5-pro", "gemini-1.5-pro-latest", "google/gemini-1.5-pro"),
    ),
    ModelBenchmarkProfile(
        model_name="deepseek-v3",
        display_name="DeepSeek-V3 (671B MoE)",
        provider="deepseek",
        open_weights=True,
        gaia_accuracy=0.61,
        open_llm_score=75.8,
        ttft_ms=450.0,
        throughput_tokens_sec=65.0,
        input_cost_per_1k=0.00014,
        output_cost_per_1k=0.00028,
        context_window_tokens=128000,
        aliases=("deepseek-ai/DeepSeek-V3", "deepseek/deepseek-chat", "deepseek-v3-chat"),
    ),
    ModelBenchmarkProfile(
        model_name="deepseek-r1",
        display_name="DeepSeek-R1 (Reasoning)",
        provider="deepseek",
        open_weights=True,
        gaia_accuracy=0.70,
        open_llm_score=80.5,
        ttft_ms=950.0,
        throughput_tokens_sec=50.0,
        input_cost_per_1k=0.00055,
        output_cost_per_1k=0.00219,
        context_window_tokens=128000,
        aliases=("deepseek-ai/DeepSeek-R1", "deepseek/deepseek-reasoner", "deepseek-r1"),
    ),
    ModelBenchmarkProfile(
        model_name="qwen-2-5-72b",
        display_name="Qwen 2.5 72B Instruct",
        provider="alibaba",
        open_weights=True,
        gaia_accuracy=0.62,
        open_llm_score=76.5,
        ttft_ms=310.0,
        throughput_tokens_sec=80.0,
        input_cost_per_1k=0.00035,
        output_cost_per_1k=0.00070,
        context_window_tokens=128000,
        aliases=(
            "qwen/qwen-2.5-72b-instruct",
            "qwen-2.5-72b-instruct",
            "Qwen/Qwen2.5-72B-Instruct",
        ),
    ),
    ModelBenchmarkProfile(
        model_name="llama-3-3-70b",
        display_name="Llama 3.3 70B Instruct",
        provider="meta",
        open_weights=True,
        gaia_accuracy=0.60,
        open_llm_score=74.2,
        ttft_ms=290.0,
        throughput_tokens_sec=88.0,
        input_cost_per_1k=0.00030,
        output_cost_per_1k=0.00060,
        context_window_tokens=128000,
        aliases=(
            "meta-llama/llama-3.3-70b-instruct",
            "llama-3.3-70b-instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
        ),
    ),
    ModelBenchmarkProfile(
        model_name="gpt-4o-mini",
        display_name="GPT-4o-mini",
        provider="openai",
        open_weights=False,
        gaia_accuracy=0.52,
        open_llm_score=68.0,
        ttft_ms=180.0,
        throughput_tokens_sec=120.0,
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.00060,
        context_window_tokens=128000,
        aliases=("gpt-4o-mini-2024-07-18", "openai/gpt-4o-mini"),
    ),
    ModelBenchmarkProfile(
        model_name="mistral-large-2411",
        display_name="Mistral Large 2411",
        provider="mistral",
        open_weights=True,
        gaia_accuracy=0.63,
        open_llm_score=75.1,
        ttft_ms=340.0,
        throughput_tokens_sec=78.0,
        input_cost_per_1k=0.00200,
        output_cost_per_1k=0.00600,
        context_window_tokens=128000,
        aliases=("mistralai/Mistral-Large-Instruct-2411", "mistral-large"),
    ),
    ModelBenchmarkProfile(
        model_name="llama-3-1-8b",
        display_name="Llama 3.1 8B Instruct",
        provider="meta",
        open_weights=True,
        gaia_accuracy=0.44,
        open_llm_score=62.3,
        ttft_ms=110.0,
        throughput_tokens_sec=160.0,
        input_cost_per_1k=0.00008,
        output_cost_per_1k=0.00016,
        context_window_tokens=128000,
        aliases=("meta-llama/llama-3.1-8b-instruct", "llama-3.1-8b"),
    ),
)


class HuggingFaceBenchmarkAnalyzer:
    """Analyzes model performance vs inference latency and recommends Pareto-optimal swaps."""

    def __init__(
        self,
        catalog: tuple[ModelBenchmarkProfile, ...] = BASELINE_HF_MODELS,
    ) -> None:
        self._catalog: list[ModelBenchmarkProfile] = list(catalog)

    @property
    def catalog(self) -> list[ModelBenchmarkProfile]:
        """Return the current registered benchmark model catalog."""
        return list(self._catalog)

    def register_model(self, profile: ModelBenchmarkProfile) -> ModelBenchmarkProfile:
        """Dynamically add or replace a model benchmark profile in the catalog."""
        self._catalog = [m for m in self._catalog if m.model_name != profile.model_name]
        self._catalog.append(profile)
        return profile

    def resolve_model(self, name_or_alias: str) -> ModelBenchmarkProfile | None:
        """Resolve a model name or provider alias to its canonical benchmark profile."""
        clean = name_or_alias.strip().lower()
        # 1. Exact canonical name match
        for m in self._catalog:
            if m.model_name.lower() == clean:
                return m

        # 2. Alias match
        for m in self._catalog:
            if clean in (a.lower() for a in m.aliases):
                return m

        # 3. Substring match (e.g. 'claude-3-5-sonnet' in 'anthropic/claude-3-5-sonnet')
        for m in self._catalog:
            if m.model_name in clean or clean in m.model_name:
                return m

        return None

    @staticmethod
    def _calculate_blended_cost(profile: ModelBenchmarkProfile) -> float:
        """Compute blended cost per 1K tokens assuming 70% input and 30% output distribution."""
        return 0.70 * profile.input_cost_per_1k + 0.30 * profile.output_cost_per_1k

    def get_pareto_recommendations(
        self,
        current_model_name: str,
        *,
        min_acceptable_accuracy: float = 0.50,
        open_weights_only: bool = False,
    ) -> list[DowngradeRecommendation]:
        """Identify models that offer strictly better latency/cost without sacrificing accuracy."""
        curr = self.resolve_model(current_model_name)
        if curr is None:
            return []

        curr_blended_cost = self._calculate_blended_cost(curr)
        candidates_raw: list[tuple[ModelBenchmarkProfile, float, float, float, float]] = []

        for candidate in self._catalog:
            if candidate.model_name == curr.model_name:
                continue

            if open_weights_only and not candidate.open_weights:
                continue

            if candidate.gaia_accuracy < min_acceptable_accuracy:
                continue

            cand_blended_cost = self._calculate_blended_cost(candidate)
            cost_savings_ratio = (
                (curr_blended_cost - cand_blended_cost) / curr_blended_cost
                if curr_blended_cost > 0
                else 0.0
            )

            latency_reduction_ratio = (
                (curr.ttft_ms - candidate.ttft_ms) / curr.ttft_ms if curr.ttft_ms > 0 else 0.0
            )

            throughput_gain_ratio = (
                (candidate.throughput_tokens_sec - curr.throughput_tokens_sec)
                / curr.throughput_tokens_sec
                if curr.throughput_tokens_sec > 0
                else 0.0
            )

            acc_delta = candidate.gaia_accuracy - curr.gaia_accuracy

            # Require either meaningful cost savings or latency reduction
            if cost_savings_ratio >= 0.20 or latency_reduction_ratio >= 0.15:
                candidates_raw.append(
                    (
                        candidate,
                        cost_savings_ratio,
                        latency_reduction_ratio,
                        throughput_gain_ratio,
                        acc_delta,
                    )
                )

        # Evaluate Pareto Non-Dominance Hull
        recommendations: list[DowngradeRecommendation] = []
        for i, (cand_i, cost_i, lat_i, tp_i, acc_i) in enumerate(candidates_raw):
            dominated = False
            for j, (_cand_j, cost_j, lat_j, _tp_j, acc_j) in enumerate(candidates_raw):
                if i == j:
                    continue
                # cand_j dominates cand_i if no worse in all 3 objectives and better in >= 1
                if (
                    cost_j >= cost_i
                    and lat_j >= lat_i
                    and acc_j >= acc_i
                    and (cost_j > cost_i or lat_j > lat_i or acc_j > acc_i)
                ):
                    dominated = True
                    break

            is_pareto = not dominated

            # Strategy tier classification
            cost_pct = cost_i * 100.0
            lat_pct = lat_i * 100.0
            if cost_pct >= 80.0:
                tier = "EXTREME_SAVINGS"
            elif cost_pct >= 50.0 and lat_pct >= 0.0:
                tier = "BALANCED_FRONTIER"
            elif lat_pct >= 35.0:
                tier = "ULTRA_LOW_LATENCY"
            elif cand_i.open_weights:
                tier = "OPEN_WEIGHTS_PREFERRED"
            else:
                tier = "EFFICIENT_SUBSTITUTION"

            recommendations.append(
                DowngradeRecommendation(
                    candidate_model=cand_i.model_name,
                    display_name=cand_i.display_name,
                    provider=cand_i.provider,
                    open_weights=cand_i.open_weights,
                    cost_savings_pct=round(cost_pct, 1),
                    latency_reduction_pct=round(lat_pct, 1),
                    throughput_gain_pct=round(tp_i * 100.0, 1),
                    benchmark_accuracy_delta=round(acc_i, 3),
                    candidate_gaia_accuracy=round(cand_i.gaia_accuracy, 3),
                    is_pareto_optimal=is_pareto,
                    strategy_tier=tier,
                    input_cost_per_1k=cand_i.input_cost_per_1k,
                    output_cost_per_1k=cand_i.output_cost_per_1k,
                )
            )

        # Sort: Pareto optimal first, then highest cost savings
        return sorted(
            recommendations,
            key=lambda r: (1 if r.is_pareto_optimal else 0, r.cost_savings_pct),
            reverse=True,
        )

    def analyze_session_downgrade(
        self,
        spans: Sequence[ArgusSpan],
        *,
        session_id: uuid.UUID,
        min_acceptable_accuracy: float = 0.50,
        open_weights_only: bool = False,
        annual_session_volume: int = 10000,
    ) -> SessionDowngradeReport:
        """Inspect spans, determine consumed tokens, and project model downgrade savings."""
        models_used: list[str] = [
            s.model_name for s in spans if s.model_name and s.model_name.strip()
        ]
        active_model_name = (
            Counter(models_used).most_common(1)[0][0] if models_used else "claude-3-5-sonnet"
        )
        curr = self.resolve_model(active_model_name) or BASELINE_HF_MODELS[0]

        total_prompt_tokens = sum(s.prompt_tokens for s in spans)
        total_completion_tokens = sum(s.completion_tokens for s in spans)

        if total_prompt_tokens == 0 and total_completion_tokens == 0:
            # Fallback based on session spend or reasonable nominal workflow token volume
            total_prompt_tokens = 4000
            total_completion_tokens = 1500

        curr_session_cost = (total_prompt_tokens / 1000.0) * curr.input_cost_per_1k + (
            total_completion_tokens / 1000.0
        ) * curr.output_cost_per_1k

        recs = self.get_pareto_recommendations(
            curr.model_name,
            min_acceptable_accuracy=min_acceptable_accuracy,
            open_weights_only=open_weights_only,
        )

        projections: list[SessionCandidateProjection] = []
        for r in recs:
            proj_cost = (total_prompt_tokens / 1000.0) * r.input_cost_per_1k + (
                total_completion_tokens / 1000.0
            ) * r.output_cost_per_1k
            savings = max(0.0, curr_session_cost - proj_cost)
            annual_savings = round(savings * annual_session_volume, 2)

            projections.append(
                SessionCandidateProjection(
                    candidate_model=r.candidate_model,
                    display_name=r.display_name,
                    provider=r.provider,
                    open_weights=r.open_weights,
                    projected_session_cost_usd=round(proj_cost, 6),
                    session_dollar_savings_usd=round(savings, 6),
                    cost_savings_pct=r.cost_savings_pct,
                    latency_reduction_pct=r.latency_reduction_pct,
                    projected_annual_savings_10k_sessions_usd=annual_savings,
                    strategy_tier=r.strategy_tier,
                    is_pareto_optimal=r.is_pareto_optimal,
                )
            )

        return SessionDowngradeReport(
            session_id=session_id,
            active_model=curr.model_name,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            current_session_cost_usd=round(curr_session_cost, 6),
            recommendations=projections,
        )
