"""Domain errors. The API layer renders them as RFC 9457 problem details."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InvalidStateError(ConflictError):
    code = "invalid_state"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "forbidden"


class UnsupportedDocumentError(DomainError):
    status_code = 415
    code = "unsupported_media_type"


class DocumentTooLargeError(DomainError):
    status_code = 413
    code = "payload_too_large"


class AuthenticationError(DomainError):
    status_code = 401
    code = "unauthenticated"


class RateLimitedError(DomainError):
    status_code = 429
    code = "too_many_requests"
