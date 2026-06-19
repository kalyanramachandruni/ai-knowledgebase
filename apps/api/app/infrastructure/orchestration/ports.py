from __future__ import annotations

from typing import Protocol


class AgentOrchestrationPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future adapters: langgraph_adapter.py, openai_agents_adapter.py.
    Each will implement this port to hand a compiled Agent Context Package
    to a multi-agent orchestration framework.
    """

    async def dispatch(self, context_package: dict, agent_name: str) -> dict: ...
