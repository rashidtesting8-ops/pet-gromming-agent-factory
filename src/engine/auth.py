"""Shared HTTP origin, host, and constant-time bearer token middleware helpers."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from fastapi.responses import JSONResponse

MUTATING_METHODS: tuple[str, ...] = ("POST", "PUT", "DELETE", "PATCH")
DEFAULT_HEALTH_PATHS: tuple[str, ...] = ("/health", "/api/health")


async def enforce_api_security(
    request: Any,
    call_next: Any,
    *,
    configured_token: str,
    allowed_hosts: Iterable[str],
    health_paths: Iterable[str] = DEFAULT_HEALTH_PATHS,
    unauthorized_detail: str = "Unauthorized: valid API token required",
) -> Any:
    """Enforce same-host origin, non-loopback token requirement, and constant-time bearer auth."""
    allowed = {h.lower() for h in allowed_hosts}
    path = getattr(getattr(request, "url", None), "path", "") or ""
    if path in set(health_paths):
        return await call_next(request)

    if request.method in MUTATING_METHODS:
        origin = request.headers.get("origin", "").strip()
        if origin:
            parsed_host = (urlparse(origin).hostname or "").lower()
            if parsed_host not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin state-changing request forbidden"},
                )

        req_host = (request.headers.get("host", "").split(":")[0] or "").strip().lower()
        if req_host and req_host not in allowed and not configured_token:
            return JSONResponse(
                status_code=403,
                content={"detail": "Non-loopback requests require EDITVISTA_API_TOKEN"},
            )

    auth_hdr = request.headers.get("authorization", "").strip()
    api_key_hdr = request.headers.get("x-api-key", "").strip()
    require_auth_hdr = request.headers.get("x-require-auth", "").strip()

    if configured_token or auth_hdr or api_key_hdr or require_auth_hdr:
        bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
        supplied = bearer or api_key_hdr
        if not configured_token or not hmac.compare_digest(supplied, configured_token):
            return JSONResponse(
                status_code=401,
                content={"detail": unauthorized_detail},
            )

    return await call_next(request)
