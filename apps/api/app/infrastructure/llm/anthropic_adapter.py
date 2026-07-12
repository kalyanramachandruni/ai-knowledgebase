from __future__ import annotations

from anthropic import AsyncAnthropic

from app.domain.extraction.ports import ExtractionResult, ExtractionSchema
import json
from app.infrastructure.llm.prompts import EXTRACTION_SYSTEM_PROMPT, MERGE_SYSTEM_PROMPT, MERGE_TOOL_DESCRIPTION, TOOL_DESCRIPTION, TOOL_NAME


class AnthropicExtractionAdapter:
    """Implements app.domain.extraction.ports.LLMExtractionPort using Claude's
    tool-use feature to force structured output matching ExtractionSchema."""

    def __init__(self, api_key: str, model: str, *, client: AsyncAnthropic | None = None) -> None:
        self._model = model
        self._client = client or AsyncAnthropic(api_key=api_key)

    async def extract(self, raw_text: str, schema: ExtractionSchema) -> ExtractionResult:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=EXTRACTION_SYSTEM_PROMPT,
            tools=[{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": schema.json_schema}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": raw_text}],
        )

        tool_use_block = next(block for block in response.content if block.type == "tool_use")
        data = tool_use_block.input

        return ExtractionResult(
            process_overview=data.get("process_overview", {}),
            process_steps=data.get("process_steps", []),
            rules=data.get("rules", []),
            policies=data.get("policies", []),
            sla_target=data.get("sla_target"),
            escalations=data.get("escalations", []),
            roles=data.get("roles", []),
            tools=data.get("tools", []),
            raw_model_output=data,
        )

    async def merge(self, existing: ExtractionResult, incoming: ExtractionResult, schema: ExtractionSchema) -> ExtractionResult:
        user_content = (
            "EXISTING KNOWLEDGE PRODUCT:\n"
            + json.dumps({
                "process_steps": existing.process_steps,
                "rules": existing.rules,
                "policies": existing.policies,
                "sla_target": existing.sla_target,
                "escalations": existing.escalations,
                "roles": existing.roles,
                "tools": existing.tools,
            }, indent=2)
            + "\n\nNEW EXTRACTION FROM ADDITIONAL PAGE:\n"
            + json.dumps({
                "process_steps": incoming.process_steps,
                "rules": incoming.rules,
                "policies": incoming.policies,
                "sla_target": incoming.sla_target,
                "escalations": incoming.escalations,
                "roles": incoming.roles,
                "tools": incoming.tools,
            }, indent=2)
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=MERGE_SYSTEM_PROMPT,
            tools=[{"name": TOOL_NAME, "description": MERGE_TOOL_DESCRIPTION, "input_schema": schema.json_schema}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": user_content}],
        )
        tool_use_block = next(block for block in response.content if block.type == "tool_use")
        data = tool_use_block.input
        return ExtractionResult(
            process_overview=data.get("process_overview", {}),
            process_steps=data.get("process_steps", []),
            rules=data.get("rules", []),
            policies=data.get("policies", []),
            sla_target=data.get("sla_target"),
            escalations=data.get("escalations", []),
            roles=data.get("roles", []),
            tools=data.get("tools", []),
            raw_model_output=data,
        )
