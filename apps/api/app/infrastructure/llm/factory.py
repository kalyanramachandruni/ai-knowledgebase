from __future__ import annotations

from app.core.config import settings
from app.domain.extraction.ports import LLMExtractionPort


def get_llm_extraction_port() -> LLMExtractionPort:
    """Single switch point for the LLM provider abstraction (docs/architecture.md §5).
    Everything upstream of this depends only on LLMExtractionPort."""

    if settings.llm_provider == "anthropic":
        from app.infrastructure.llm.anthropic_adapter import AnthropicExtractionAdapter

        return AnthropicExtractionAdapter(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if settings.llm_provider == "openai":
        from app.infrastructure.llm.openai_adapter import OpenAIExtractionAdapter

        return OpenAIExtractionAdapter(api_key=settings.openai_api_key, model=settings.openai_model)

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")
