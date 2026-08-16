"""Admin login, dashboard, thread mod, and mass actions."""
from __future__ import annotations

import logging
import time
from html import escape as html_escape

from werkzeug.wrappers import Response

from ..admin_actions import process_admin_action, process_mass_action
from ..app_context import RequestState, canonicalize_admin_path, cookie_path, secure
from ..core.admin import (
    check_admin_pass,
    check_admin_login_form,
    create_admin_token,
    get_all_threads_for_admin,
    is_admin_cookie_authenticated,
)
from ..core.reports import get_open_reports
from ..core.storage import load_thread

logger = logging.getLogger("kareha")


def handle_admin(state: RequestState) -> Response:
    ctx = state.ctx
    cfg = ctx.cfg
    request = state.request
    script_root = state.script_root
    effective_path = canonicalize_admin_path(state)
    state.effective_path = effective_path

    if request.method == "POST" and check_admin_login_form(request, cfg):
        provided = (request.form.get("admin") or "").strip()
        if check_admin_pass(provided, cfg):
            token = create_admin_token(cfg)
            import secrets
            csrf_token = secrets.token_urlsafe(16)
            resp = Response(status=303, headers={"Location": script_root + "/admin"})
            admin_secure = getattr(cfg, "ADMIN_COOKIE_SECURE", False)
            if not admin_secure:
                scheme = getattr(request, "environ", {}).get("wsgi.url_scheme", "")
                xfp = request.headers.get("X-Forwarded-Proto", "") if hasattr(request, "headers") else ""
                if scheme == "https" or xfp == "https":
                    admin_secure = True
            path = cookie_path(script_root)
            resp.set_cookie(
                "admin_auth", token, httponly=True, secure=admin_secure,
                samesite="Lax", max_age=86400, path=path,
            )
            resp.set_cookie(
                "admin_csrf", csrf_token, httponly=True,
                samesite="Lax", max_age=86400, path=path,
            )
            return secure(resp, cfg)

    is_admin = is_admin_cookie_authenticated(request, cfg)
    state.is_admin = is_admin

    if effective_path == "/admin/logout":
        resp = Response(status=303, headers={"Location": script_root + "/"})
        path = cookie_path(script_root)
        resp.set_cookie("admin_auth", "", expires=0, path=path)
        resp.set_cookie("admin_csrf", "", expires=0, path=path)
        return secure(resp, cfg)

    if not is_admin:
        login_html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Admin Login - {html_escape(getattr(cfg, 'TITLE', 'Board'))}</title>"
            "</head><body>"
            "<h1>Admin Login</h1>"
            f'<form method="post" action="{script_root}/admin">'
            'Admin Pass: <input type="password" name="admin" autocomplete="current-password">'
            '<button type="submit">Login</button>'
            "</form>"
            "<p><small>Authenticated via HttpOnly cookie after login. "
            "Use the same password you configured as ADMIN_PASS.</small></p>"
            "</body></html>"
        )
        return secure(Response(login_html, mimetype="text/html"), cfg)

    csrf = request.cookies.get("admin_csrf", "")

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action:
            submitted_csrf = request.form.get("csrf", "")
            if submitted_csrf != csrf:
                return secure(Response("CSRF validation failed", status=403), cfg)
            ok, err = process_admin_action(
                ctx.board_dir,
                cfg,
                action=action,
                thread_id_str=request.form.get("thread", ""),
                post_num_str=request.form.get("post", ""),
                state_str=request.form.get("state", "1"),
                report_index_str=request.form.get("index", ""),
            )
            if not ok:
                return secure(Response(err or "Action failed", status=400), cfg)
            redirect_thread = request.form.get("thread", "")
            if redirect_thread and action in (
                "close", "permasage", "pin", "delete", "deletefile", "banmd5",
            ):
                loc = f"{script_root}/admin/thread/{redirect_thread}"
            else:
                loc = script_root + "/admin"
            return secure(Response(status=303, headers={"Location": loc}), cfg)

    if effective_path in ("/admin", "/admin/"):
        return _dashboard(state, csrf)

    if effective_path.startswith("/admin/thread/"):
        return _mod_thread(state, csrf)

    return secure(Response("Not found", status=404), cfg)


def _dashboard(state: RequestState, csrf: str) -> Response:
    ctx = state.ctx
    threads = get_all_threads_for_admin(ctx.board_dir, ctx.cfg)
    open_reports = get_open_reports(ctx.board_dir)
    for r in open_reports:
        r["time_str"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("timestamp", 0)))
    try:
        tmpl = ctx.jinja_env.get_template("admin/dashboard.html")
        html = tmpl.render(
            title=ctx.cfg.TITLE,
            initial_theme_css=ctx.initial_theme_css,
            open_reports=open_reports,
            threads=threads,
            csrf=csrf,
            enumerate=enumerate,
            script_root=state.script_root,
        )
    except Exception:
        logger.exception("Admin dashboard template error")
        html = "<h1>Admin Dashboard</h1><p>Admin template error.</p>"
    return secure(Response(html, mimetype="text/html"), ctx.cfg)


def _mod_thread(state: RequestState, csrf: str) -> Response:
    ctx = state.ctx
    request = state.request
    try:
        thread_id = int(state.effective_path.split("/admin/thread/")[1].split("?")[0])
    except Exception:
        return secure(Response("Bad thread id", status=400), ctx.cfg)

    res_dir = ctx.board_dir / getattr(ctx.cfg, "RES_DIR", "res/")
    thread = load_thread(res_dir, thread_id)
    if not thread:
        return secure(Response("Thread not found", status=404), ctx.cfg)

    if request.method == "POST":
        mass_action = request.form.get("mass_action")
        selected = request.form.getlist("selected_posts")
        csrf_sub = request.form.get("csrf", "")
        if mass_action and selected:
            if csrf_sub != csrf:
                return secure(Response("CSRF validation failed", status=403), ctx.cfg)
            selected_nums = [int(s) for s in selected if s.isdigit()]
            ok, err = process_mass_action(
                ctx.board_dir, ctx.cfg, thread_id, mass_action, selected_nums,
            )
            if not ok:
                return secure(Response(err or "Action failed", status=400), ctx.cfg)
            return secure(
                Response(
                    status=303,
                    headers={"Location": f"{state.script_root}/admin/thread/{thread_id}"},
                ),
                ctx.cfg,
            )

    try:
        tmpl = ctx.jinja_env.get_template("admin/thread.html")
        html = tmpl.render(
            title=ctx.cfg.TITLE,
            initial_theme_css=ctx.initial_theme_css,
            thread_id=thread_id,
            thread=thread,
            posts=thread.posts,
            closed=thread.closed,
            permasage=thread.permasage,
            pinned=thread.pinned,
            post_count=len(thread.posts),
            csrf=csrf,
            enumerate=enumerate,
            script_root=state.script_root,
        )
    except Exception:
        logger.exception("Admin thread template error")
        html = f"<h1>Mod #{thread_id}</h1><p>Admin thread template error.</p>"
    return secure(Response(html, mimetype="text/html"), ctx.cfg)
