"""Password hashing, access tokens and brute-force protection."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings
from app.db import utcnow
from app.models import UserRole

_hasher = PasswordHasher()
# Verified against when the user does not exist, so response time doesn't reveal valid emails.
_DUMMY_HASH = _hasher.hash("timing-equaliser")

TOKEN_AUDIENCE = "invoice-intelligence"  # noqa: S105 - JWT audience claim


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID, role: UserRole, settings: Settings) -> tuple[str, int]:
    ttl = timedelta(minutes=settings.jwt_ttl_minutes)
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "role": role.value,
        "aud": TOKEN_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises `jwt.PyJWTError` if the token is invalid or expired."""
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=TOKEN_AUDIENCE,
        options={"require": ["sub", "exp", "iat", "aud"]},
    )


class LoginThrottle:
    """Locks an account out after repeated failed logins.

    In-process only: with several API replicas each keeps its own counter, which still bounds the
    attempt rate. Put a shared store (Redis) or the edge WAF in front for stricter guarantees.
    """

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()
        return attempts

    def is_locked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key.lower(), time.monotonic())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key.lower(), now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key.lower(), None)
