from __future__ import annotations

from typing import Protocol


class BpmnPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future: import/export a Knowledge Product's process steps as BPMN XML
    for visual process design tools.
    """

    def to_bpmn_xml(self, process_steps: list[str]) -> str: ...

    def from_bpmn_xml(self, bpmn_xml: str) -> list[str]: ...
