from __future__ import annotations

from dataclasses import dataclass

from app.domain.shared.base import ValueObject


@dataclass(frozen=True)
class AttachmentRef(ValueObject):
    file_name: str
    media_type: str
    download_url: str
    size_bytes: int
