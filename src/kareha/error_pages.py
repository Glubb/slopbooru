"""
Catch-all error pages for unhandled WSGI exceptions.

Renders user-friendly HTML instead of exposing tracebacks. Full details are
logged server-side (stderr + optional board error log file).
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment
from werkzeug.wrappers import Request, Response

from .http_helpers import apply_security_headers

logger = logging.getLogger("kareha")

FLASH_ERROR_COOKIE = "flash_error"
FLASH_STATUS_COOKIE = "flash_status"

_WSGIApp = Callable[..., Any]


def user_error_status(message: str) -> int:
    """Pick an HTTP status for a user-facing error message."""
    m = (message or "").lower()
    if "rate limit" in m:
        return 429
    if any(
        phrase in m
        for phrase in (
            "administrator",
            "banned",
            "comments are disabled",
            "not allowed",
            "csrf",
            "forbidden",
        )
    ):
        return 403
    return 400


def user_error_heading(status: int) -> str:
    if status == 403:
        return "Not allowed"
    if status == 429:
        return "Slow down"
    if status == 404:
        return "Not found"
    return "Could not complete request"


def _cookie_path(script_root: str) -> str:
    return (script_root + "/") if script_root else "/"


def redirect_to_error_page(
    script_root: str,
    message: str,
    cfg: Any,
    *,
    status: int | None = None,
) -> Response:
    """Redirect to /error with a short-lived flash cookie (message never in the URL)."""
    status = status if status is not None else user_error_status(message)
    message = (message or "Something went wrong.")[:500]
    loc = (script_root or "") + "/error"
    resp = Response(status=303, headers={"Location": loc})
    path = _cookie_path(script_root)
    resp.set_cookie(FLASH_ERROR_COOKIE, message, max_age=120, httponly=True, samesite="Lax", path=path)
    resp.set_cookie(FLASH_STATUS_COOKIE, str(status), max_age=120, httponly=True, samesite="Lax", path=path)
    return apply_security_headers(resp, cfg)


def render_flash_error_page(
    request: Any,
    jinja_env: Environment,
    cfg: Any,
    script_root: str,
) -> Response:
    """Render /error from flash cookies set by redirect_to_error_page."""
    message = ""
    status = 400
    if hasattr(request, "cookies"):
        message = (request.cookies.get(FLASH_ERROR_COOKIE) or "").strip()
        try:
            status = int(request.cookies.get(FLASH_STATUS_COOKIE, "400"))
        except ValueError:
            status = 400

    if not message:
        message = "No error details are available. You may have followed an outdated link."
        status = 400

    heading = user_error_heading(status)
    resp = render_error_page(
        jinja_env,
        cfg,
        status=status,
        heading=heading,
        message=message,
        script_root=script_root,
    )
    path = _cookie_path(script_root)
    resp.delete_cookie(FLASH_ERROR_COOKIE, path=path)
    resp.delete_cookie(FLASH_STATUS_COOKIE, path=path)
    return resp


def _script_root_from_environ(environ: dict, base_path: str) -> str:
    root = (environ.get("SCRIPT_NAME") or base_path or "").strip()
    if root and not root.startswith("/"):
        root = "/" + root
    return root.rstrip("/")


def render_error_page(
    jinja_env: Environment,
    cfg: Any,
    *,
    status: int,
    heading: str,
    message: str,
    script_root: str = "",
    details: str = "",
) -> Response:
    """Render a styled HTML error page."""
    default_style = getattr(cfg, "DEFAULT_STYLE", "Burichan")
    initial_theme_css = default_style.lower().replace(" ", "_") + ".css"
    try:
        tmpl = jinja_env.get_template("error.html")
        html = tmpl.render(
            status=status,
            title=getattr(cfg, "TITLE", "Board"),
            heading=heading,
            message=message,
            details=details,
            script_root=script_root,
            initial_theme_css=initial_theme_css,
        )
    except Exception:
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{status}</title></head><body>"
            f"<h1>{heading}</h1><p>{message}</p>"
            f"<p><a href='{script_root or '/'}'>Back</a></p></body></html>"
        )
    resp = Response(html, status=status, mimetype="text/html; charset=utf-8")
    return apply_security_headers(resp, cfg)


def log_unhandled_exception(board_dir: Path, cfg: Any, exc: BaseException) -> str:
    """Log traceback; optionally append to board error log. Returns log reference id."""
    tb = traceback.format_exc()
    logger.error("Unhandled exception on board %s:\n%s", board_dir, tb)

    log_file = getattr(cfg, "ERROR_LOG_FILE", "") or ""
    if log_file:
        path = board_dir / log_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n---\n")
        except Exception:
            logger.exception("Failed to write error log at %s", path)

    return type(exc).__name__


def build_error_response(
    environ: dict,
    exc: BaseException,
    *,
    cfg: Any,
    jinja_env: Environment,
    board_dir: Path,
    base_path: str,
) -> Response:
    """Build a safe HTML response for an unhandled exception."""
    script_root = _script_root_from_environ(environ, base_path)
    exc_name = log_unhandled_exception(board_dir, cfg, exc)

    show_details = bool(getattr(cfg, "SHOW_ERROR_DETAILS", False))
    details = ""
    if show_details:
        details = f"{exc_name}: {exc}"

    status = 500
    heading = "Something went wrong"
    message = (
        "The server hit an unexpected error while handling your request. "
        "The problem has been logged. Please try again in a moment."
    )

    if isinstance(exc, PermissionError):
        status = 403
        heading = "Forbidden"
        message = "You do not have permission to perform that action."
    elif isinstance(exc, FileNotFoundError):
        status = 404
        heading = "Not found"
        message = "The requested resource could not be found."

    return render_error_page(
        jinja_env,
        cfg,
        status=status,
        heading=heading,
        message=message,
        script_root=script_root,
        details=details,
    )


def wrap_with_error_pages(
    wsgi_app: _WSGIApp,
    *,
    cfg: Any,
    jinja_env: Environment,
    board_dir: Path,
    base_path: str,
) -> _WSGIApp:
    """Wrap a WSGI app so uncaught exceptions return HTML error pages."""

    def middleware(environ: dict, start_response: Callable) -> Any:
        try:
            return wsgi_app(environ, start_response)
        except Exception as exc:
            resp = build_error_response(
                environ,
                exc,
                cfg=cfg,
                jinja_env=jinja_env,
                board_dir=board_dir,
                base_path=base_path,
            )
            return resp(environ, start_response)

    return middleware