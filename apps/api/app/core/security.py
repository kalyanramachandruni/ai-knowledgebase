from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.domain.governance.value_objects import Role

_ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Identity + roles resolved from the JWT bearer token. Roles are sourced
    from the token's `roles` claim — in production this token is issued by
    the configured OIDC provider (settings.oidc_issuer_url), which maps its
    own groups/roles to this claim; locally it's signed with JWT_SECRET via
    create_access_token below. The user_role DB table is reserved for a
    future local-admin override flow and isn't consulted here yet."""

    user_id: uuid.UUID
    roles: frozenset[Role]

    def has_any_role(self, *roles: Role) -> bool:
        return bool(self.roles & set(roles))


def create_access_token(user_id: uuid.UUID, roles: list[Role], *, expires_minutes: int = 60) -> str:
    """Issues a locally-signed token. Exists for local dev/testing and for
    any deployment that hasn't yet wired up OIDC — not used when SSO is
    configured, where tokens come from the IdP instead."""

    payload = {
        "sub": str(user_id),
        "roles": [r.value for r in roles],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
        roles = frozenset(Role(r) for r in payload.get("roles", []))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims") from exc

    return CurrentUser(user_id=user_id, roles=roles)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return decode_access_token(credentials.credentials)


def require_roles(*allowed: Role):
    """FastAPI dependency factory: 403s unless the caller holds at least
    one of the given roles. Use as Depends(require_roles(Role.ADMIN, ...))."""

    async def _check(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not current_user.has_any_role(*allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in allowed]}",
            )
        return current_user

    return _check
