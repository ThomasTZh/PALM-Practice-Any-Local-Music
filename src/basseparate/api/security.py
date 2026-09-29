"""Loopback authentication and request protection (M0.7).

- Bearer token authentication for all protected routes.
- Host and Origin validation.
- Rate limiting on failed authentication attempts.
- Security headers for static responses.

The health route remains unauthenticated.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger(__name__)

AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

# Paths that do not require authentication.
PUBLIC_PATHS: frozenset[str] = frozenset({"/api/v1/health"})

# Allowed host patterns for loopback.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "127.0.0.1:8765",
        "localhost:8765",
        "[::1]:8765",
    }
)

# Rate limiting: max failed attempts per window before lockout.
RATE_LIMIT_MAX_FAILURES = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0


class AuthRateLimiter:
    """Conservative rate limiter for failed authentication attempts."""

    def __init__(
        self,
        max_failures: int = RATE_LIMIT_MAX_FAILURES,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        entries = [t for t in self._failures[key] if now - t < self._window]
        self._failures[key] = entries
        return len(entries) >= self._max_failures

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforces bearer auth, Host/Origin checks, and rate limiting."""

    def __init__(self, app: Any, session_token: str) -> None:
        super().__init__(app)
        self._token = session_token
        self._rate_limiter = AuthRateLimiter()

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path

        # Public paths skip authentication.
        if path not in PUBLIC_PATHS:
            # Host validation.
            host = request.headers.get("host", "")
            if not self._is_allowed_host(host):
                return self._forbidden("Unexpected Host header")

            # Origin validation (for browser requests).
            origin = request.headers.get("origin")
            if origin is not None and not self._is_allowed_origin(origin):
                return self._forbidden("Hostile Origin rejected")

            # Rate limit check.
            client_key = request.client.host if request.client else "unknown"
            if self._rate_limiter.is_blocked(client_key):
                return self._too_many_requests()

            # Bearer token authentication.
            auth = request.headers.get(AUTH_HEADER, "")
            if not auth.startswith(BEARER_PREFIX):
                self._rate_limiter.record_failure(client_key)
                return self._unauthorized("Missing bearer token")
            token = auth[len(BEARER_PREFIX) :]
            if not hmac.compare_digest(token, self._token):
                self._rate_limiter.record_failure(client_key)
                return self._unauthorized("Invalid bearer token")
            self._rate_limiter.record_success(client_key)

        response: Response = await call_next(request)

        # Add security headers to all responses.
        self._add_security_headers(response)
        return response

    def _is_allowed_host(self, host: str) -> bool:
        if not host:
            return False
        if host in ALLOWED_HOSTS:
            return True
        return any(host.startswith(prefix) for prefix in ("127.0.0.1:", "localhost:", "[::1]:"))

    def _is_allowed_origin(self, origin: str) -> bool:
        if not origin:
            return True
        for prefix in (
            "http://127.0.0.1:",
            "http://localhost:",
            "http://[::1]:",
        ):
            if origin.startswith(prefix):
                return True
        return False

    def _add_security_headers(self, response: Response) -> None:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")

    def _unauthorized(self, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": message,
                    "request_id": "",
                    "details": {},
                }
            },
        )

    def _forbidden(self, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "FORBIDDEN",
                    "message": message,
                    "request_id": "",
                    "details": {},
                }
            },
        )

    def _too_many_requests(self) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many failed authentication attempts; try again later",
                    "request_id": "",
                    "details": {},
                }
            },
        )
