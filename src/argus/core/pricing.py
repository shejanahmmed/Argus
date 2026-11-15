"""Deterministic LLM model token pricing catalog and cost estimation engine."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPriceRate:
    """Pricing rates per 1,000,000 (1M) tokens in USD."""

    input_usd_per_1m: float
    output_usd_per_1m: float


# Baseline reference rates per 1M tokens across popular providers (as of 2025/2026)
MODEL_PRICING_CATALOG: dict[str, ModelPriceRate] = {
    # Anthropic Claude
    "claude-3-5-sonnet": ModelPriceRate(input_usd_per_1m=3.00, output_usd_per_1m=15.00),
    "claude-3-5-haiku": ModelPriceRate(input_usd_per_1m=0.80, output_usd_per_1m=4.00),
    "claude-3-opus": ModelPriceRate(input_usd_per_1m=15.00, output_usd_per_1m=75.00),
    # OpenAI GPT
    "gpt-4o": ModelPriceRate(input_usd_per_1m=2.50, output_usd_per_1m=10.00),
    "gpt-4o-mini": ModelPriceRate(input_usd_per_1m=0.15, output_usd_per_1m=0.60),
    "o1": ModelPriceRate(input_usd_per_1m=15.00, output_usd_per_1m=60.00),
    "o3-mini": ModelPriceRate(input_usd_per_1m=1.10, output_usd_per_1m=4.40),
    # DeepSeek
    "deepseek-v3": ModelPriceRate(input_usd_per_1m=0.14, output_usd_per_1m=0.28),
    "deepseek-chat": ModelPriceRate(input_usd_per_1m=0.14, output_usd_per_1m=0.28),
    "deepseek-r1": ModelPriceRate(input_usd_per_1m=0.55, output_usd_per_1m=2.19),
    "deepseek-reasoner": ModelPriceRate(input_usd_per_1m=0.55, output_usd_per_1m=2.19),
    # Open-weights / Self-hosted (proxy equivalent rate)
    "llama-3.3-70b": ModelPriceRate(input_usd_per_1m=0.40, output_usd_per_1m=0.40),
    "llama-3.1-8b": ModelPriceRate(input_usd_per_1m=0.08, output_usd_per_1m=0.08),
    "mixtral-8x7b": ModelPriceRate(input_usd_per_1m=0.24, output_usd_per_1m=0.24),
    "qwen-2.5-72b": ModelPriceRate(input_usd_per_1m=0.35, output_usd_per_1m=0.40),
}

# Conservative default estimate when model name is unrecognized ($1.00 / $3.00 per 1M)
_DEFAULT_FALLBACK_RATE = ModelPriceRate(input_usd_per_1m=1.00, output_usd_per_1m=3.00)


def normalize_model_name(raw_name: str | None) -> str:
    """Normalize model string by stripping vendor prefixes, dates, and version tags."""
    if not raw_name:
        return "unknown"
    clean = raw_name.strip().lower()
    # Strip common provider prefixes like "openai/", "anthropic/", "deepseek/"
    if "/" in clean:
        clean = clean.split("/")[-1]
    # Strip snapshot date suffixes like "-20241022", "-2024-08-06"
    clean = re.sub(r"-\d{4}-?\d{2}-?\d{2}$", "", clean)
    return clean


def estimate_token_cost_usd(
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Estimate USD token inference spend from prompt and completion token counts."""
    p_tok = max(0, prompt_tokens)
    c_tok = max(0, completion_tokens)
    if p_tok == 0 and c_tok == 0:
        return 0.0

    normalized = normalize_model_name(model_name)
    rate = MODEL_PRICING_CATALOG.get(normalized)

    # Partial prefix match fallback (e.g. "claude-3-5-sonnet-latest" -> "claude-3-5-sonnet")
    if rate is None:
        for catalog_key, catalog_rate in MODEL_PRICING_CATALOG.items():
            if normalized.startswith(catalog_key):
                rate = catalog_rate
                break

    if rate is None:
        rate = _DEFAULT_FALLBACK_RATE

    cost = (p_tok * (rate.input_usd_per_1m / 1_000_000.0)) + (
        c_tok * (rate.output_usd_per_1m / 1_000_000.0)
    )
    return round(cost, 8)
