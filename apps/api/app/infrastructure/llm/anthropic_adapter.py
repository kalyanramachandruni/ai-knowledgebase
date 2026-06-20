from __future__ import annotations

from anthropic import AsyncAnthropic

from app.domain.extraction.ports import ExtractionResult, ExtractionSchema
from app.infrastructure.llm.prompts import EXTRACTION_SYSTEM_PROMPT, TOOL_DESCRIPTION, TOOL_NAME


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
            process_steps=data.get("process_steps", []),
            rules=data.get("rules", []),
            policies=data.get("policies", []),
            sla_target=data.get("sla_target"),
            escalations=data.get("escalations", []),
            roles=data.get("roles", []),
            tools=data.get("tools", []),
            raw_model_output=data,
        )
