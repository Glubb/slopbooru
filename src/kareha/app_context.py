"""Shared app/request context for WSGI handlers."""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment
from werkzeug.wrappers import Request, Response

from .core.admin import is_admin_cookie_authenticated
from .http_helpers import apply_security_headers, get_client_ip


@dataclass
class AppContext:
    board_dir: Path
    cfg: Any
    jinja_env: Environment
    board_mode: str
    base_path: str
    default_style_name: str
    initial_theme_css: str


@dataclass
class RequestState:
    ctx: AppContext
    request: Request
    script_root: str
    effective_path: str
    candidates: list[str]
    client_ip: str
    is_admin: bool
    public_csrf: str
    default_delpass: str
    newly_created_delpass: bool
    error: str | None = None


def resolve_script_root(request: Request, base_path: str) -> str:
    script_root = request.environ.get("SCRIPT_NAME", "") or base_path or ""
    if script_root and not script_root.startswith("/"):
        script_root = "/" + script_root
    return script_root.rstrip("/")


def resolve_effective_path(
    request: Request, base_path: str, script_root: str
) -> tuple[str, list[str]]:
    req_path = request.path or "/"
    candidates: list[str] = []
    for cand in (request.environ.get("SCRIPT_NAME", ""), base_path, script_root):
        if cand:
            c = cand.rstrip("/")
            if c and c not in candidates:
                candidates.append(c)
    effective_path = req_path
    for pfx in candidates:
        if pfx and effective_path.startswith(pfx):
            effective_path = effective_path[len(pfx):] or "/"
            break
    if base_path:
        bp = base_path.rstrip("/")
        if bp and bp in effective_path and not effective_path.startswith("/"):
            idx = effective_path.find(bp)
            if idx != -1:
                after = effective_path[idx + len(bp):]
                if after.startswith("/") or after == "":
                    effective_path = after or "/"
    effective_path = "/" + (effective_path or "").lstrip("/")
    while "//" in effective_path:
        effective_path = effective_path.replace("//", "/")
    return effective_path, candidates


def cookie_path(script_root: str) -> str:
    return script_root + "/" if script_root else "/"


def public_tokens(request: Request) -> tuple[str, str, bool]:
    public_csrf = ""
    if hasattr(request, "cookies"):
        public_csrf = request.cookies.get("csrf_token", "")
    if not public_csrf:
        public_csrf = secrets.token_urlsafe(16)

    default_delpass = ""
    newly_created = False
    if hasattr(request, "cookies"):
        default_delpass = request.cookies.get("delpass", "")[:8]
    if not default_delpass:
        alphabet = string.ascii_letters + string.digits
        default_delpass = "".join(secrets.choice(alphabet) for _ in range(8))
        newly_created = True
    return public_csrf, default_delpass, newly_created


def build_request_state(request: Request, ctx: AppContext) -> RequestState:
    script_root = resolve_script_root(request, ctx.base_path)
    effective_path, candidates = resolve_effective_path(request, ctx.base_path, script_root)
    public_csrf, default_delpass, newly = public_tokens(request)
    return RequestState(
        ctx=ctx,
        request=request,
        script_root=script_root,
        effective_path=effective_path,
        candidates=candidates,
        client_ip=get_client_ip(request, ctx.cfg),
        is_admin=is_admin_cookie_authenticated(request, ctx.cfg),
        public_csrf=public_csrf,
        default_delpass=default_delpass,
        newly_created_delpass=newly,
    )


def looks_like_admin_path(state: RequestState) -> bool:
    effective_path = state.effective_path
    raw_path = state.request.path or "/"
    if effective_path.startswith("/admin"):
        return True
    for pfx in state.candidates + [state.ctx.base_path]:
        if pfx:
            p = pfx.rstrip("/")
            if (
                raw_path.startswith(p + "/admin")
                or raw_path == (p + "/admin")
                or raw_path.startswith(p + "/admin/")
            ):
                return True
    if "/admin" in raw_path and (state.ctx.base_path or state.script_root):
        return True
    return False


def canonicalize_admin_path(state: RequestState) -> str:
    effective_path = state.effective_path
    for pfx in state.candidates + [state.ctx.base_path, state.script_root]:
        if pfx:
            p = pfx.rstrip("/")
            if effective_path.startswith(p):
                effective_path = effective_path[len(p):] or "/"
    effective_path = "/" + (effective_path or "").lstrip("/")
    while "//" in effective_path:
        effective_path = effective_path.replace("//", "/")
    return effective_path


def attach_public_cookies(resp: Response, state: RequestState) -> Response:
    cfg = state.ctx.cfg
    path = cookie_path(state.script_root)
    if not state.request.cookies.get("csrf_token"):
        resp.set_cookie(
            "csrf_token", state.public_csrf,
            httponly=True, samesite="Lax", max_age=86400 * 30, path=path,
        )
    if state.newly_created_delpass:
        resp.set_cookie(
            "delpass", state.default_delpass,
            httponly=True, samesite="Lax", max_age=86400 * 365, path=path,
        )
    return apply_security_headers(resp, cfg)


def secure(resp: Response, cfg: Any) -> Response:
    return apply_security_headers(resp, cfg)
