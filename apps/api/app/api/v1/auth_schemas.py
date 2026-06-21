from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.domain.governance.value_objects import Role


class DevTokenRequest(BaseModel):
    user_id: uuid.UUID
    display_name: str
    roles: list[Role]


class DevTokenResponse(BaseModel):
    access_token: str
    user_id: uuid.UUID
    roles: list[Role]
