from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AuthenticationError, PermissionDeniedError
from app.models import User, UserRole
from app.runtime import get_document_store
from app.security import decode_access_token
from app.services.storage import DocumentStore

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Store = Annotated[DocumentStore, Depends(get_document_store)]


def get_current_user(
    session: DbSession, settings: AppSettings, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    try:
        claims = decode_access_token(token, settings)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User is inactive or no longer exists")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("Your role does not allow this action")
        return user

    return dependency


Uploader = Annotated[User, Depends(require_roles(UserRole.CLERK, UserRole.APPROVER, UserRole.ADMIN))]
Approver = Annotated[User, Depends(require_roles(UserRole.APPROVER, UserRole.ADMIN))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
