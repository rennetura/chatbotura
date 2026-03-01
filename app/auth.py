"""Authentication module for ChatBotura - API key based tenant authentication."""
import time
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .db import get_tenant_by_api_key, get_tenant

# Rate limit: 100 requests per minute per tenant
RATE_LIMIT_REQUESTS = 100
RATE_LIMIT_WINDOW = 60  # seconds


class RateLimiter:
    """Simple in-memory sliding window rate limiter per tenant."""

    def __init__(self):
        # Structure: {tenant_id: deque([timestamp1, timestamp2, ...])}
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, tenant_id: str) -> tuple[bool, int]:
        """
        Check if a request is allowed for the tenant.

        Args:
            tenant_id: The tenant identifier

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW

        if tenant_id not in self._requests:
            self._requests[tenant_id] = []

        # Remove old timestamps outside the window
        timestamps = self._requests[tenant_id]
        while timestamps and timestamps[0] < window_start:
            timestamps.pop(0)

        # Check if under limit
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            return False, 0

        # Add current timestamp
        timestamps.append(now)
        return True, RATE_LIMIT_REQUESTS - len(timestamps)

    def get_remaining(self, tenant_id: str) -> int:
        """Get remaining requests for a tenant in the current window."""
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW

        if tenant_id not in self._requests:
            return RATE_LIMIT_REQUESTS

        timestamps = self._requests[tenant_id]
        # Count timestamps within window
        recent = [t for t in timestamps if t >= window_start]
        # Update the deque to remove stale entries
        self._requests[tenant_id] = recent
        return max(0, RATE_LIMIT_REQUESTS - len(recent))


# Global rate limiter instance
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to authenticate API requests using API keys."""

    # Paths that don't require authentication
    EXCLUDED_PATHS = {
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get("x-api-key")
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "API key required. Include x-api-key header."
                }
            )

        # Verify API key and fetch tenant
        tenant = get_tenant_by_api_key(api_key)
        if not tenant:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "Invalid API key."
                }
            )

        # Attach tenant to request state
        request.state.tenant = tenant

        # Proceed with request
        response = await call_next(request)
        return response


def get_current_tenant(request: Request) -> dict:
    """
    FastAPI dependency to get the authenticated tenant.

    Should be used after AuthMiddleware has run.
    """
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    return tenant


def verify_tenant_access(tenant_id: str, request: Request) -> dict:
    """
    Verify that the authenticated tenant has access to the requested tenant_id.
    For multi-tenant operations, ensure the API key belongs to the requested tenant
    or is an admin key (if admin concept is added later).
    """
    tenant = get_current_tenant(request)
    if tenant["tenant_id"] != tenant_id:
        # In the future, allow admin keys to access any tenant
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions to access this tenant"
        )
    return tenant


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce per-tenant rate limiting."""

    # Paths that are excluded from rate limiting
    EXCLUDED_PATHS = {
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    def __init__(self, app):
        super().__init__(app)
        self.rate_limiter = _rate_limiter

    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Rate limit only if tenant is attached (by AuthMiddleware)
        tenant = getattr(request.state, "tenant", None)
        if tenant:
            tenant_id = tenant["tenant_id"]
            allowed, remaining = self.rate_limiter.is_allowed(tenant_id)

            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": "Rate limit exceeded. Please try again later."
                    },
                    headers={
                        "X-RateLimit-Limit": str(RATE_LIMIT_REQUESTS),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": str(RATE_LIMIT_WINDOW)
                    }
                )

            # Add rate limit headers to response
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_REQUESTS)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

        # No tenant attached (shouldn't happen if auth middleware is before), allow
        return await call_next(request)
