"""
security.py — Production-grade security middleware, rate limiting, and request sanitization.
"""

import time
import logging
from collections import defaultdict
from typing import Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# ─── Security Headers Middleware ──────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies defense-in-depth HTTP security headers to all responses:
      - Content-Security-Policy (CSP)
      - Strict-Transport-Security (HSTS)
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: DENY (anti-clickjacking)
      - Referrer-Policy: strict-origin-when-cross-origin
      - Permissions-Policy: restricts browser hardware features
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # 1. Anti-MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 2. Anti-clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # 3. Referrer protection
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 4. Restrict sensitive client features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        # 5. HTTP Strict Transport Security (HSTS) — 1 year + subdomains
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # 6. Content Security Policy (CSP)
        # Allows self, plus fonts/scripts required for Swagger UI / API documentation in dev
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers["Content-Security-Policy"] = csp

        return response


# ─── Sliding-Window In-Memory Rate Limiter ────────────────────────────────────

class RateLimiter:
    """
    Thread-safe sliding-window rate limiter per client IP.
    Doesn't require external Redis for small-to-medium deployment footprints,
    preventing brute-force attacks on sensitive endpoints.
    """

    def __init__(self):
        # ip -> list of request timestamps
        self.requests: Dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Returns (is_allowed, remaining_seconds_to_wait)
        """
        now = time.time()
        window_start = now - window_seconds

        # Clean old timestamps
        history = [ts for ts in self.requests[client_ip] if ts > window_start]
        self.requests[client_ip] = history

        if len(history) >= max_requests:
            retry_after = int(window_seconds - (now - history[0])) + 1
            return False, max(1, retry_after)

        self.requests[client_ip].append(now)
        return True, 0


rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extracts client IP, honoring X-Forwarded-For if behind a reverse proxy (Railway/Vercel)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def rate_limit_endpoint(max_requests: int = 5, window_seconds: int = 60):
    """
    FastAPI dependency factory for strict rate limiting.
    Default: 5 requests per 60 seconds (ideal for login / sensitive operations).
    """
    async def dependency(request: Request):
        ip = get_client_ip(request)
        allowed, retry_after = rate_limiter.is_allowed(ip, max_requests, window_seconds)
        if not allowed:
            logger.warning("Rate limit exceeded for IP %s on path %s (retry after %ds)", ip, request.url.path, retry_after)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
    return dependency
