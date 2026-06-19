from __future__ import annotations

from typing import Protocol


class PolicyAuthoringPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future: author/edit policies directly via a DSL or UI, independent of
    Confluence as the source, feeding the same Knowledge Product compiler.
    """

    async def validate_policy_expression(self, expression: str) -> bool: ...
