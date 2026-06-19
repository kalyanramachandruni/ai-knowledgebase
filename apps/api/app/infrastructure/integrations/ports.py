from __future__ import annotations

from typing import Protocol


class ExternalSystemIntegrationPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future adapters: copilot_adapter.py (Microsoft Copilot), servicenow_adapter.py.
    Each will implement this port to push/pull Knowledge Products or context
    packages to/from an external platform.
    """

    async def push_context_package(self, context_package: dict) -> None: ...
