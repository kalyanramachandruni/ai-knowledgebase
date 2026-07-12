from __future__ import annotations


from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.api.v1.auth_schemas import DevTokenRequest, DevTokenResponse
from app.core.config import settings
from app.core.security import create_access_token
from app.infrastructure.db.models import AppUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-token", response_model=DevTokenResponse)
async def issue_dev_token(payload: DevTokenRequest, session: SessionDep) -> DevTokenResponse:
    """Dev/test-only: mints a JWT for any user_id/roles with no credential
    check, and upserts a matching app_user row so the id satisfies FK
    constraints elsewhere (created_by, actor_id, etc). Disabled via
    ENABLE_DEV_LOGIN=false once a real OIDC provider is wired up."""

    if not settings.enable_dev_login:
        raise HTTPException(status_code=404, detail="Dev login is disabled")

    user_row = await session.get(AppUser, payload.user_id)
    if user_row is None:
        session.add(AppUser(id=payload.user_id, email=f"{payload.user_id}@dev.local", display_name=payload.display_name))
    else:
        user_row.display_name = payload.display_name
    await session.commit()

    token = create_access_token(payload.user_id, payload.roles, expires_minutes=8 * 60)
    return DevTokenResponse(access_token=token, user_id=payload.user_id, roles=payload.roles)
