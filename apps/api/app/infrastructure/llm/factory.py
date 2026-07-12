from __future__ import annotations

import logging

from app.core.config import settings
from app.domain.extraction.ports import LLMExtractionPort

logger = logging.getLogger(__name__)


def get_llm_extraction_port() -> LLMExtractionPort:
    """Single switch point for the LLM provider abstraction (docs/architecture.md §5).
    Everything upstream of this depends only on LLMExtractionPort."""

    logger.info("LLM factory: provider=%r anthropic_key_set=%s openai_key_set=%s",
                settings.llm_provider, bool(settings.anthropic_api_key), bool(settings.openai_api_key))

    if settings.llm_provider == "anthropic":
        from app.infrastructure.llm.anthropic_adapter import AnthropicExtractionAdapter

        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set — check your .env file")
        return AnthropicExtractionAdapter(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if settings.llm_provider == "openai":
        from app.infrastructure.llm.openai_adapter import OpenAIExtractionAdapter

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set — check your .env file")
        return OpenAIExtractionAdapter(api_key=settings.openai_api_key, model=settings.openai_model)

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")
