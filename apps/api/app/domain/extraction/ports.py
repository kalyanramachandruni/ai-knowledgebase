from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractionSchema:
    """Describes the structured components an LLM call should return.
    Passed to the port so the prompt/tool-schema can be built generically
    across providers without domain code knowing provider-specific formats."""

    json_schema: dict


@dataclass(frozen=True)
class ExtractionResult:
    # process_steps: list of dicts with at minimum {"name": str, "description": str}
    # plus optional: responsible_role, inputs, outputs, decision, tools_used
    process_steps: list[dict]
    # rules/policies: [{"condition": str, "action": str, "rationale"?: str}]
    rules: list[dict]
    policies: list[dict]
    sla_target: str | None
    # escalations: [{"trigger": str, "escalate_to": str, "action"?: str}]
    # "trigger" is the canonical field; older data may use "after"
    escalations: list[dict]
    # roles: list of dicts {"name": str, "responsibilities"?: [str]}
    roles: list[dict]
    # tools: list of dicts {"name": str, "purpose"?: str}
    tools: list[dict]
    # process_overview: {"summary": str, "trigger": str, "outcome": str}
    process_overview: dict
    raw_model_output: dict


class LLMExtractionPort(Protocol):
    """Port implemented per-provider in app/infrastructure/llm/.
    Domain/application code calls this and never imports a provider SDK directly."""

    async def extract(self, raw_text: str, schema: ExtractionSchema) -> ExtractionResult: ...

    async def merge(self, existing: ExtractionResult, incoming: ExtractionResult, schema: ExtractionSchema) -> ExtractionResult: ...
