from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SyncSpaceInput:
    space_key: str
    space_name: str
    base_url: str


@dataclass(frozen=True)
class SyncSpaceResult:
    space_key: str
    pages_created: int
    pages_updated: int
    pages_skipped_unchanged: int
