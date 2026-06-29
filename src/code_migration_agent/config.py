"""Configuration defaults and optional LLM credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass

TARGET_PYTHON = "3.12"

# Illustrative fallback prices, not a statement about any provider's current
# rates. Set CMA_PRICE_IN_PER_MTOK / CMA_PRICE_OUT_PER_MTOK to the real values.
DEFAULT_PRICE_IN_PER_MTOK = 3.0
DEFAULT_PRICE_OUT_PER_MTOK = 15.0


class LLMConfigurationError(RuntimeError):
    """Raised when a live LLM policy is requested without configuration."""


@dataclass(frozen=True)
class PriceTable:
    input_per_mtok: float = DEFAULT_PRICE_IN_PER_MTOK
    output_per_mtok: float = DEFAULT_PRICE_OUT_PER_MTOK

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_mtok
            + completion_tokens * self.output_per_mtok
        ) / 1_000_000.0


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    prices: PriceTable
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        base_url = os.environ.get("CMA_LLM_BASE_URL", "").strip()
        api_key = os.environ.get("CMA_LLM_API_KEY", "").strip()
        model = os.environ.get("CMA_LLM_MODEL", "").strip()
        missing = [
            name
            for name, value in (
                ("CMA_LLM_BASE_URL", base_url),
                ("CMA_LLM_API_KEY", api_key),
                ("CMA_LLM_MODEL", model),
            )
            if not value
        ]
        if missing:
            raise LLMConfigurationError(
                "LLM policy requires " + ", ".join(missing)
            )
        prices = PriceTable(
            input_per_mtok=_env_float(
                "CMA_PRICE_IN_PER_MTOK", DEFAULT_PRICE_IN_PER_MTOK
            ),
            output_per_mtok=_env_float(
                "CMA_PRICE_OUT_PER_MTOK", DEFAULT_PRICE_OUT_PER_MTOK
            ),
        )
        return cls(base_url=base_url.rstrip("/"), api_key=api_key, model=model, prices=prices)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be a number, got {raw!r}") from exc
