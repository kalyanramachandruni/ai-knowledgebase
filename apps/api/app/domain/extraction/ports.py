from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractionSchema:
    """Describes the structured components an LLM call should return.
    Passed to the port so the prompt/tool-schema can be built generically
    across providers without domain code knowing provider-specific formats."""

    json_schema: dict


@dataclass(frozen=True)
class ExtractionResult:
    process_steps: list[str]
    rules: list[dict]          # [{"condition": ..., "action": ...}]
    policies: list[dict]       # [{"condition": ..., "action": ...}]
    sla_target: str | None
    escalations: list[dict]    # [{"after": ..., "escalate_to": ...}]
    roles: list[str]
    tools: list[str]
    raw_model_output: dict


class LLMExtractionPort(Protocol):
    """Port implemented per-provider in app/infrastructure/llm/.
    Domain/application code calls this and never imports a provider SDK directly."""

    async def extract(self, raw_text: str, schema: ExtractionSchema) -> ExtractionResult: ...
