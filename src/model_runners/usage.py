"""Token and optional configured-price accounting."""

from __future__ import annotations

from .protocol import ModelRequestConfig


def estimate_cost(
    *, input_tokens: int, output_tokens: int, config: ModelRequestConfig
) -> float | None:
    if config.input_token_price_per_million is None and config.output_token_price_per_million is None:
        return None
    input_price = config.input_token_price_per_million or 0.0
    output_price = config.output_token_price_per_million or 0.0
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)


def approximate_tokens(text: str) -> int:
    """Conservative fallback when a provider omits usage."""
    return max(1, (len(text.encode("utf-8")) + 3) // 4) if text else 0
