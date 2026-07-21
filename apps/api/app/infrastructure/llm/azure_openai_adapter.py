from __future__ import annotations

from openai import AsyncAzureOpenAI

from app.infrastructure.llm.openai_adapter import OpenAIExtractionAdapter


class AzureOpenAIExtractionAdapter(OpenAIExtractionAdapter):
    """LLMExtractionPort backed by Azure AI Foundry (Azure OpenAI Service).

    Identical to OpenAIExtractionAdapter in behaviour — same tool-calling
    protocol, same prompt templates. The only differences are:
      - client is AsyncAzureOpenAI (endpoint + api_version instead of api_key alone)
      - `deployment` is the Azure deployment name, passed as the model parameter
    """

    def __init__(
        self,
        *,
        azure_endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
    ) -> None:
        client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        super().__init__(api_key=api_key, model=deployment, client=client)
