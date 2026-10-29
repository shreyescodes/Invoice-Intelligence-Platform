from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app import __version__
from app.api.deps import AppSettings, CurrentUser, DbSession
from app.db import utcnow
from app.demo.accounts import DEMO_ACCOUNTS
from app.errors import AuthenticationError, RateLimitedError
from app.models import User
from app.observability import get_logger
from app.schemas import MetaOut, Problem, TokenOut, UserOut
from app.security import LoginThrottle, create_access_token, hash_password, needs_rehash, verify_password
from app.services.anomaly import read_metadata

router = APIRouter(tags=["auth"])
log = get_logger(__name__)


def _get_throttle(request: Request) -> LoginThrottle:
    throttle: LoginThrottle = request.app.state.login_throttle
    return throttle


@router.post(
    "/auth/token",
    response_model=TokenOut,
    responses={401: {"model": Problem}, 429: {"model": Problem}},
    summary="Exchange email and password for a bearer token",
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
    settings: AppSettings,
    throttle: Annotated[LoginThrottle, Depends(_get_throttle)],
) -> TokenOut:
    email = form.username.strip().lower()
    if throttle.is_locked(email):
        raise RateLimitedError("Too many failed sign-in attempts. Try again in a few minutes.")
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(user.password_hash, form.password) or not user.is_active:
        throttle.record_failure(email)
        log.warning("login_failed", email=email)
        raise AuthenticationError("Incorrect email or password")
    throttle.reset(email)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(form.password)
    user.last_login_at = utcnow()
    session.commit()
    token, expires_in = create_access_token(user.id, user.role, settings)
    log.info("login_succeeded", user_id=str(user.id))
    return TokenOut(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/meta", response_model=MetaOut, tags=["meta"], summary="Public configuration for the web client")
def meta(settings: AppSettings) -> MetaOut:
    return MetaOut(
        version=__version__,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        demo_accounts=[dict(a) for a in DEMO_ACCOUNTS] if settings.demo_mode else [],
        llm_enabled=settings.llm_enabled,
        llm_model=settings.llm_model if settings.llm_enabled else None,
        extractor=settings.extractor,
        auto_approve_limit=settings.auto_approve_limit,
        approver_limit=settings.approver_limit,
        anomaly_review_threshold=settings.anomaly_review_threshold,
        anomaly_model=read_metadata(settings.model_dir),
    )
