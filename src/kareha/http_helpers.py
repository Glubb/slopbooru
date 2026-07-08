"""
HTTP helpers: trusted client IP, security headers, safe error messages.
"""
from __future__ import annotations

from typing import Any

from werkzeug.wrappers import Response

from .core.posting import PostError


def get_client_ip(request: Any, cfg: Any) -> str:
    """
    Return the client IP, honoring X-Forwarded-For only when TRUSTED_PROXY_COUNT > 0.

    Set TRUSTED_PROXY_COUNT=1 when behind Caddy/nginx (one reverse proxy hop).
    """
    trusted = int(getattr(cfg, "TRUSTED_PROXY_COUNT", 0) or 0)
    if trusted > 0:
        xff = ""
        if hasattr(request, "headers"):
            xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            # Caddy/nginx typically set the original client as the leftmost entry.
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[0]
        xri = ""
        if hasattr(request, "headers"):
            xri = (request.headers.get("X-Real-IP") or "").strip()
        if xri:
            return xri
    return (getattr(request, "remote_addr", None) or "127.0.0.1").strip() or "127.0.0.1"


def safe_user_error(exc: Exception, *, context: str = "post") -> str:
    """Return a user-safe message; only PostError / ValueError with known text pass through."""
    if isinstance(exc, PostError):
        return str(exc)
    msg = str(exc).lower()
    if context == "delete" and "password" in msg:
        return "Incorrect deletion password."
    if context == "delete":
        return "Delete failed."
    return "Something went wrong. Please try again."


def apply_security_headers(resp: Response, cfg: Any, *, script_root: str = "") -> Response:
    """Attach baseline security headers (CSP tuned for Kareha inline styles/scripts)."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")

    csp = getattr(cfg, "CONTENT_SECURITY_POLICY", None)
    if csp is None:
        # Inline script/style blocks in templates; captcha uses data: images
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    if csp:
        resp.headers.setdefault("Content-Security-Policy", csp)

    return resp