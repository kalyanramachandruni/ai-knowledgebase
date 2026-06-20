from __future__ import annotations

import json

from openai import AsyncOpenAI

from app.domain.extraction.ports import ExtractionResult, ExtractionSchema
from app.infrastructure.llm.prompts import EXTRACTION_SYSTEM_PROMPT, TOOL_DESCRIPTION, TOOL_NAME


class OpenAIExtractionAdapter:
    """Implements app.domain.extraction.ports.LLMExtractionPort using OpenAI
    function calling to force structured output matching ExtractionSchema.
    Same port as AnthropicExtractionAdapter — swapping providers is a config
    change (LLM_PROVIDER env var), not a code change anywhere else."""

    def __init__(self, api_key: str, model: str, *, client: AsyncOpenAI | None = None) -> None:
        self._model = model
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def extract(self, raw_text: str, schema: ExtractionSchema) -> ExtractionResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": TOOL_DESCRIPTION,
                        "parameters": schema.json_schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        )

        tool_call = response.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments)

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
