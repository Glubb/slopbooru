"""
WSGI entry point for Kareha Python.

Usage:
    gunicorn "kareha.wsgi:make_app(board_dir='.', mode='imageboard')"
    python -m wsgiref.simple_server -m kareha.wsgi:make_app
"""
from __future__ import annotations

import re
import traceback
from html import escape as html_escape
from pathlib import Path
from typing import Any
import re as re2  # for catalog teaser stripping without shadowing

from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix

from .admin_actions import process_admin_action
from .config import load_config, make_config_object
from .core.posting import post_stuff, PostError
from .core.deletion import delete_post
from .core.admin import (
    check_admin_pass,
    get_all_threads_for_admin,
    admin_delete_post,
    create_admin_token,
    is_admin_cookie_authenticated,
    check_admin_login_form,
    ban_ip,
    ban_md5,
)
from .core.reports import submit_report, get_open_reports
from .core.storage import load_thread, save_thread
from .error_pages import (
    render_error_page,
    render_flash_error_page,
    redirect_to_error_page,
    wrap_with_error_pages,
)
from .http_helpers import apply_security_headers, get_client_ip, safe_user_error
from .utils import ensure_board_directories
from .runtime_store import check_rate_limit as shared_check_rate_limit
from . import config as config_module


def _check_post_rate_limit(board_dir: Path, ip: str, cfg: Any) -> bool:
    """Return True if under limit, False if rate limited (shared across workers)."""
    return shared_check_rate_limit(
        board_dir,
        cfg,
        "posts",
        ip,
        max_events=getattr(cfg, "RATE_LIMIT_POSTS_PER_MIN", 5),
        window_seconds=float(getattr(cfg, "RATE_LIMIT_WINDOW_SECONDS", 60)),
    )


def _check_report_rate_limit(board_dir: Path, ip: str, cfg: Any) -> bool:
    return shared_check_rate_limit(
        board_dir,
        cfg,
        "reports",
        ip,
        max_events=getattr(cfg, "REPORT_RATE_LIMIT_POSTS", 10),
        window_seconds=float(getattr(cfg, "REPORT_RATE_LIMIT_WINDOW_SECONDS", 300)),
    )


def _secure(resp: Response, cfg: Any) -> Response:
    return apply_security_headers(resp, cfg)


def make_app(board_dir: str | Path = ".", mode: str | None = None, base_path: str = "", **cfg_overrides: Any):
    """
    Factory that returns a WSGI application for a specific board.

    board_dir: directory containing config.py, res/, src/, thumb/, css/, include/, spam.txt

    mode: Optional override for the board type.
          - If provided, it takes precedence over BOARD_MODE in the board's config.py.
          - If None (or omitted), the value of BOARD_MODE from config.py is used (or "imageboard").
          - Aliases are accepted in either place: "image", "text", "message", "blog", etc.

    base_path: Optional URL prefix for this board when mounted under a subpath (e.g. "/board1").
               Used for generating links and handling requests when not behind a prefix-stripping
               dispatcher. When using DispatcherMiddleware or a proxy that sets SCRIPT_NAME,
               the app will prefer SCRIPT_NAME.

    The final canonical BOARD_MODE ("imageboard", "textboard", or "blog") ends up on the
    config object and drives image policy, front-page layout, catalog style, blog admin
    gates, BLOG_COMMENTS handling, etc.
    """
    board_dir = Path(board_dir).resolve()
    cfg_dict = load_config(board_dir / "config.py", mode=mode)
    cfg_dict.update(cfg_overrides)
    cfg = make_config_object(cfg_dict)

    # BOARD_MODE is now the single source of truth (set by load_config with hybrid logic:
    # explicit mode arg overrides config.py's BOARD_MODE, which overrides the default).
    # The value here is already canonical ("imageboard", "textboard", or "blog").
    board_mode = getattr(cfg, "BOARD_MODE", "imageboard")

    # tmpl_prefix is mostly legacy at this point; the main templates are under "image/"
    # with conditionals, and "message/" is kept for fallback/legacy textboard paths.
    if board_mode == "textboard":
        tmpl_prefix = "message"
    else:
        tmpl_prefix = "image"

    # Make the board's loaded config (including CAPPED_TRIPS from testboard/config.py) visible
    # to post_stuff() via the _get_cfg() fallback. Without this, posting always saw the
    # empty defaults dict even though load_config correctly read your CAPPED_TRIPS.
    from . import config as config_module
    config_module.current_config = cfg

    ensure_board_directories(board_dir, cfg)

    # Normalize base_path for subpath mounting (e.g. "/board1")
    base_path = (base_path or "").strip()
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    base_path = base_path.rstrip("/")
    if base_path == "":
        base_path = ""

    # Compute initial theme CSS from DEFAULT_STYLE (so changing the default in config affects new users / no-cookie case)
    default_style_name = getattr(cfg, "DEFAULT_STYLE", "Burichan")
    initial_theme_css = default_style_name.lower().replace(" ", "_") + ".css"

    # Set up Jinja2 environment (package templates + board include/ dir)
    template_dirs = [
        str(Path(__file__).parent / "templates"),
        str(board_dir / getattr(cfg, "INCLUDE_DIR", "include")),
    ]
    jinja_env = Environment(
        loader=FileSystemLoader(template_dirs),
        autoescape=select_autoescape(["html", "htm", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    @Request.application
    def app(request: Request) -> Response:
        task = request.args.get("task") or request.form.get("task")
        error = None
        is_admin = is_admin_cookie_authenticated(request, cfg)
        client_ip = get_client_ip(request, cfg)

        # Support subpath mounting via explicit base_path or SCRIPT_NAME (from DispatcherMiddleware etc.)
        script_root = request.environ.get("SCRIPT_NAME", "") or base_path or ""
        if script_root and not script_root.startswith("/"):
            script_root = "/" + script_root
        script_root = script_root.rstrip("/")

        # effective_path is the path relative to this board's mount point (for routing).
        # Robust against Caddy variations: handle /board/* (passes full /board/admin to backend)
        # vs handle_path /board/* (strips to /admin for backend), SCRIPT_NAME, explicit base_path,
        # double slashes, trailing slashes etc. We try all candidate prefixes.
        req_path = request.path or "/"
        candidates = []
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
        # Extra tolerance + collapse duplicate slashes (some proxies/Caddy configs can emit //)
        if base_path:
            bp = base_path.rstrip("/")
            if bp and bp in effective_path and not effective_path.startswith("/"):
                # attempt to recover inner path if prefix somehow partially remained
                idx = effective_path.find(bp)
                if idx != -1:
                    after = effective_path[idx + len(bp):]
                    if after.startswith("/") or after == "":
                        effective_path = after or "/"
        effective_path = "/" + (effective_path or "").lstrip("/")
        while "//" in effective_path:
            effective_path = effective_path.replace("//", "/")

        # Public CSRF token for posting forms (separate from admin_csrf; cookie-based for stateless "session")
        public_csrf = ""
        if hasattr(request, "cookies"):
            public_csrf = request.cookies.get("csrf_token", "")
        if not public_csrf:
            public_csrf = __import__("secrets").token_urlsafe(16)

        default_delpass = ""
        newly_created_delpass = False
        if hasattr(request, "cookies"):
            default_delpass = request.cookies.get("delpass", "")[:8]
        if not default_delpass:
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            default_delpass = "".join(secrets.choice(alphabet) for _ in range(8))
            newly_created_delpass = True

        # Normal request handling continues below...

        # === ADMIN INTERFACE ===
        # Uses cookie-based auth (preferred) to avoid leaking the password in URLs/logs/history.
        # Falls back to one-time ?admin= or form value only for the login step itself.
        # Extra defensive checks on raw_path + candidates so /ad/admin (or equivalent under base_path)
        # works reliably no matter what path transformation the fronting Caddy (handle vs handle_path)
        # applied before proxying to gunicorn.
        raw_path = req_path
        enter_admin = effective_path.startswith("/admin")
        if not enter_admin:
            for pfx in candidates + [base_path]:
                if pfx:
                    p = pfx.rstrip("/")
                    if (raw_path.startswith(p + "/admin") or raw_path == (p + "/admin") or
                            raw_path.startswith(p + "/admin/")):
                        enter_admin = True
                        break
        if not enter_admin and "/admin" in raw_path:
            if base_path or script_root:
                enter_admin = True

        if enter_admin:
            # Force a clean effective_path (strip any remaining prefix) so the inner
            # == "/admin", startswith("/admin/thread/"), logout etc all see the canonical form.
            for pfx in candidates + [base_path, script_root]:
                if pfx:
                    p = pfx.rstrip("/")
                    if effective_path.startswith(p):
                        effective_path = effective_path[len(p):] or "/"
            effective_path = "/" + (effective_path or "").lstrip("/")
            while "//" in effective_path:
                effective_path = effective_path.replace("//", "/")

            # Handle explicit login POST first (sets the cookie; password never in query strings)
            if request.method == "POST" and check_admin_login_form(request, cfg):
                provided = (request.form.get("admin") or "").strip()
                if check_admin_pass(provided, cfg):
                    token = create_admin_token(cfg)
                    csrf_token = __import__("secrets").token_urlsafe(16)
                    resp = Response(status=303, headers={"Location": script_root + "/admin"})
                    # Secure cookie handling (item 4)
                    admin_secure = getattr(cfg, "ADMIN_COOKIE_SECURE", False)
                    if not admin_secure:
                        scheme = getattr(request, "environ", {}).get("wsgi.url_scheme", "")
                        xfp = request.headers.get("X-Forwarded-Proto", "") if hasattr(request, "headers") else ""
                        if scheme == "https" or xfp == "https":
                            admin_secure = True

                    cookie_path = script_root + "/" if script_root else "/"
                    resp.set_cookie("admin_auth", token, httponly=True, secure=admin_secure, samesite="Lax", max_age=86400, path=cookie_path)
                    resp.set_cookie("admin_csrf", csrf_token, httponly=True, samesite="Lax", max_age=86400, path=cookie_path)
                    return _secure(resp, cfg)

            is_admin = is_admin_cookie_authenticated(request, cfg)

            if effective_path == "/admin/logout":
                resp = Response(status=303, headers={"Location": script_root + "/"})
                resp.set_cookie("admin_auth", "", expires=0, path=script_root + "/" if script_root else "/")
                resp.set_cookie("admin_csrf", "", expires=0, path=script_root + "/" if script_root else "/")
                return _secure(resp, cfg)

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
                return _secure(Response(login_html, mimetype="text/html"), cfg)

            csrf = request.cookies.get("admin_csrf", "")

            # POST moderation actions (dashboard or thread page) — never via GET query strings
            if request.method == "POST":
                action = (request.form.get("action") or "").strip()
                if action:
                    submitted_csrf = request.form.get("csrf", "")
                    if submitted_csrf != csrf:
                        return _secure(Response("CSRF validation failed", status=403), cfg)
                    ok, err = process_admin_action(
                        board_dir,
                        cfg,
                        action=action,
                        thread_id_str=request.form.get("thread", ""),
                        post_num_str=request.form.get("post", ""),
                        state_str=request.form.get("state", "1"),
                        report_index_str=request.form.get("index", ""),
                    )
                    if not ok:
                        return _secure(Response(err or "Action failed", status=400), cfg)
                    redirect_thread = request.form.get("thread", "")
                    if redirect_thread and action in (
                        "close", "permasage", "delete", "deletefile", "banmd5",
                    ):
                        loc = f"{script_root}/admin/thread/{redirect_thread}"
                    else:
                        loc = script_root + "/admin"
                    return _secure(Response(status=303, headers={"Location": loc}), cfg)

            # Thread list via Jinja template (item 2) + CSRF (item 1) + thread # in template
            if effective_path == "/admin" or effective_path == "/admin/":
                threads = get_all_threads_for_admin(board_dir, cfg)

                import time
                open_reports = get_open_reports(board_dir)
                for r in open_reports:
                    r["time_str"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("timestamp", 0)))

                try:
                    tmpl = jinja_env.get_template("admin/dashboard.html")
                    html = tmpl.render(
                        title=cfg.TITLE,
                        initial_theme_css=initial_theme_css,
                        open_reports=open_reports,
                        threads=threads,
                        csrf=csrf,
                        enumerate=enumerate,  # in case any template still uses it
                        script_root=script_root,
                    )
                except Exception as e:
                    # For debugging template errors, show the real exception
                    html = f"<h1>Admin Dashboard</h1><p>Admin template error: {e}</p><pre>{traceback.format_exc()}</pre>"
                return _secure(Response(html, mimetype="text/html"), cfg)

            # Per-thread mod page via Jinja template (item 2). Shows the IP-based unique poster_id.
            if effective_path.startswith("/admin/thread/"):
                try:
                    thread_id = int(effective_path.split("/admin/thread/")[1].split("?")[0])
                except Exception:
                    return _secure(Response("Bad thread id", status=400), cfg)

                res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
                thread = load_thread(res_dir, thread_id)
                if not thread:
                    return _secure(Response("Thread not found", status=404), cfg)

                # Handle mass actions from checkboxes (POST)
                if request.method == "POST":
                    mass_action = request.form.get("mass_action")
                    selected = request.form.getlist("selected_posts")
                    csrf_sub = request.form.get("csrf", "")
                    if mass_action and selected:
                        if csrf_sub != csrf:
                            return _secure(Response("CSRF validation failed", status=403), cfg)
                        res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
                        thread = load_thread(res_dir, thread_id)  # fresh load
                        if thread:
                            selected_nums = [int(s) for s in selected if s.isdigit()]
                            posts_to_act = [p for p in thread.posts if p.num in selected_nums]
                            if mass_action == "delete_posts":
                                for p in posts_to_act:
                                    admin_delete_post(board_dir, thread_id, p.num, file_only=False, cfg=cfg)
                            elif mass_action == "delete_files":
                                for p in posts_to_act:
                                    admin_delete_post(board_dir, thread_id, p.num, file_only=True, cfg=cfg)
                            elif mass_action == "ban_ips":
                                unique_ips = {p.ip for p in posts_to_act if p.ip}
                                for ip_addr in unique_ips:
                                    ban_ip(board_dir, ip_addr, reason=f"Mass ban from mod page thread {thread_id}", cfg=cfg)
                            elif mass_action == "ban_md5s":
                                for p in posts_to_act:
                                    if p.md5:
                                        ban_md5(board_dir, p.md5, reason=f"Mass ban from mod page thread {thread_id}", cfg=cfg)
                            save_thread(thread, res_dir)
                        return _secure(
                            Response(status=303, headers={"Location": f"{script_root}/admin/thread/{thread_id}"}),
                            cfg,
                        )

                try:
                    tmpl = jinja_env.get_template("admin/thread.html")
                    html = tmpl.render(
                        title=cfg.TITLE,
                        initial_theme_css=initial_theme_css,
                        thread_id=thread_id,
                        thread=thread,
                        posts=thread.posts,
                        closed=thread.closed,
                        permasage=thread.permasage,
                        post_count=len(thread.posts),
                        csrf=csrf,
                        enumerate=enumerate,
                        script_root=script_root,
                    )
                except Exception as e:
                    html = f"<h1>Mod #{thread_id}</h1><p>Admin thread template error: {e}</p><pre>{traceback.format_exc()}</pre>"
                return _secure(Response(html, mimetype="text/html"), cfg)

        # === DELETION (POST only — password never in URL/logs) ===
        if task == "delete" and request.method != "POST":
            return _secure(Response("Deletion requires POST.", status=405), cfg)

        if request.method == "POST" and task == "delete":
            try:
                raw = (request.form.get("delete") or "").strip()
                if "," not in raw:
                    raise ValueError("bad delete param")
                thread_id_str, post_num_str = raw.split(",", 1)
                tid = int(thread_id_str)
                pid = int(post_num_str)
                provided_pass = (request.form.get("password") or "").strip()
                file_only = request.form.get("fileonly") in ("1", "true", "yes", "on")

                secret = getattr(cfg, "SECRET", "")
                if not delete_post(
                    board_dir,
                    tid,
                    pid,
                    password=provided_pass,
                    file_only=file_only,
                    secret=secret,
                    cfg=cfg,
                ):
                    raise ValueError("bad deletion password")

                ref = request.referrer or script_root + "/"
                return _secure(Response(status=303, headers={"Location": ref}), cfg)
            except Exception as e:
                return redirect_to_error_page(
                    script_root,
                    safe_user_error(e, context="delete"),
                    cfg,
                )

        # === REPORT POST ===
        if task == "report":
            if request.method == "POST":
                try:
                    reason = (request.form.get("reason") or "").strip()
                    # Basic sanitization / limits for reports (they are shown to admins)
                    if not _check_report_rate_limit(board_dir, client_ip, cfg):
                        return _secure(Response("Too many reports. Please wait.", status=429), cfg)
                    if not reason:
                        return _secure(Response("Reason is required", status=400), cfg)
                    if len(reason) > 2000:
                        reason = reason[:2000]
                    # The reason will be stored raw and later escaped when rendered in admin UI.

                    # Support both single report (from link) and multiple (from checkboxes)
                    reports_to_submit = []

                    # From individual report link
                    if request.form.get("thread") and request.form.get("post"):
                        reports_to_submit.append((
                            int(request.form["thread"]),
                            int(request.form["post"])
                        ))

                    # From checkboxes on thread page (name="report")
                    for val in request.form.getlist("report"):
                        try:
                            t_id, p_num = val.split(",")
                            reports_to_submit.append((int(t_id), int(p_num)))
                        except:
                            continue

                    for t_id, p_num in reports_to_submit:
                        submit_report(board_dir, t_id, p_num, reason, client_ip)

                    return _secure(Response(
                        "<html><body><h2>Report(s) submitted. Thank you.</h2>"
                        "<p><a href='#' onclick='window.close();return false;'>Close window</a> "
                        "or <a href='#' onclick='history.back();return false;'>Go back</a></p></body></html>",
                        mimetype="text/html",
                    ), cfg)
                except Exception:
                    return _secure(Response("Report failed.", status=400), cfg)

            # Show report form (GET) - for individual reports via link
            thread_id = (request.args.get("thread") or "").strip()
            post_num = (request.args.get("post") or "").strip()
            if not thread_id or not post_num:
                return _secure(Response("Missing thread or post", status=400), cfg)

            # Escape even though they should be numeric (defense in depth)
            safe_tid = html_escape(thread_id)
            safe_pid = html_escape(post_num)

            form_html = f"""
            <html><body>
            <h2>Report Post #{safe_pid} in thread #{safe_tid}</h2>
            <form method="post" action="{script_root}/?task=report">
                <input type="hidden" name="thread" value="{safe_tid}">
                <input type="hidden" name="post" value="{safe_pid}">
                <p>Reason for report:</p>
                <textarea name="reason" rows="5" cols="50" required></textarea><br><br>
                <button type="submit" title="Submit Report" style="font-size:14px;padding:2px 5px;cursor:pointer;">🚩</button>
            </form>
            </body></html>
            """
            return _secure(Response(form_html, mimetype="text/html"), cfg)

        # === USER-FACING ERROR PAGE (flash redirect target) ===
        if effective_path.rstrip("/") == "/error":
            return render_flash_error_page(request, jinja_env, cfg, script_root)

        # === POSTING ===
        if request.method == "POST" and task == "post":
            tmp_path = None
            upload_name = None
            try:
                board_mode = getattr(cfg, "BOARD_MODE", "imageboard")
                blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if board_mode == "blog" else "enabled"
                is_reply = bool(request.form.get("thread"))

                # Blog: only admins may create new entries; comments follow BLOG_COMMENTS
                if board_mode == "blog":
                    if not is_reply and not is_admin:
                        raise PostError("Only administrators can create new blog entries.")
                    if is_reply and blog_comments == "disabled":
                        raise PostError("Comments are disabled on this blog.")

                # Rate limiting (quick win for public deploys)
                if not _check_post_rate_limit(board_dir, client_ip, cfg):
                    raise PostError("Rate limit exceeded. Please wait a minute before posting again.")

                # CSRF check for public posts (quick win)
                submitted_csrf = request.form.get("csrf", "")
                if public_csrf and submitted_csrf != public_csrf:
                    raise PostError("CSRF validation failed. Please refresh the page and try again.")

                # Auto-generate 8-char deletion password if none provided; tie to cookie for "session"
                del_password = request.form.get("password", "") or ""
                if not del_password:
                    import secrets
                    import string
                    alphabet = string.ascii_letters + string.digits
                    del_password = "".join(secrets.choice(alphabet) for _ in range(8))

                # Save uploaded file temporarily
                uploaded_file = request.files.get("file")
                if uploaded_file and uploaded_file.filename:
                    import tempfile
                    # SECURITY: Never trust the original filename for paths.
                    # Take only the basename and a very limited suffix.
                    orig = Path(uploaded_file.filename).name  # strips any directory components
                    suffix = Path(orig).suffix.lower()
                    # Enforce allowed extensions (general vs blog permissive)
                    allowed_exts = getattr(cfg, "BLOG_ALLOWED_EXTENSIONS", ()) if (board_mode == "blog" and is_admin) else getattr(cfg, "ALLOWED_EXTENSIONS", ())
                    if suffix and suffix not in allowed_exts:
                        # For non-blog or non-admin, reject disallowed; for blog admin allow broader but still sanitize
                        if not (board_mode == "blog" and is_admin):
                            raise PostError(f"Filetype {suffix} not allowed.")
                    # Allow only very safe characters in the suffix
                    safe_suffix = "".join(c for c in suffix if c.isalnum() or c in ".-_")[:12]
                    if not safe_suffix or safe_suffix == ".":
                        safe_suffix = ".bin"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=safe_suffix)
                    uploaded_file.save(tmp.name)
                    tmp_path = tmp.name
                    # Keep a sanitized version of the original name for display only (not for FS ops)
                    upload_name = orig[:200]  # cap length too

                # Enforce no images on blog comments when BLOG_COMMENTS=text_only (even if form is bypassed)
                if tmp_path and board_mode == "blog" and request.form.get("thread") and blog_comments == "text_only":
                    Path(tmp_path).unlink(missing_ok=True)
                    tmp_path = None
                    upload_name = None
                    raise PostError("Image posting not allowed in this context.")

                # Captcha check (skip for admin tripcode / capped posts)
                enable_captcha = getattr(cfg, "ENABLE_CAPTCHA", False)
                if enable_captcha:
                    name_field = request.form.get("field_a", "") or ""
                    tripkey = getattr(cfg, "TRIPKEY", "!")
                    is_admin_trip = False
                    if tripkey in name_field:
                        raw_part = name_field.split(tripkey, 1)[1]
                        raw_trip = f"{tripkey}{raw_part}"
                        if raw_trip in getattr(cfg, "CAPPED_TRIPS", {}):
                            is_admin_trip = True
                    if not is_admin_trip:
                        ctoken = request.form.get("captcha_token", "")
                        cans = request.form.get("captcha", "") or ""
                        from .captcha import validate_captcha
                        if not validate_captcha(
                            ctoken, cans, board_dir=board_dir, cfg=cfg
                        ):
                            raise PostError("Incorrect or expired captcha.")

                # For blog mode, default to Admin name (and capcode badge if configured) when using admin cookie
                force_capcode = ""
                effective_name = request.form.get("field_a", "")
                if board_mode == "blog" and is_admin:
                    effective_name = "Admin"
                    capped = getattr(cfg, "CAPPED_TRIPS", {}) or {}
                    if isinstance(capped, dict) and capped:
                        force_capcode = next(iter(capped.values()))

                post_num = post_stuff(
                    board_dir,
                    thread_id=int(request.form.get("thread")) if request.form.get("thread") else None,
                    name=effective_name,
                    link=request.form.get("field_b", ""),
                    title=request.form.get("title", ""),
                    comment=request.form.get("comment", ""),
                    markup=request.form.get("markup", "waka"),
                    password=del_password,  # deletion password (auto-generated 8 chars if empty; tied to cookie)
                    file_path=tmp_path,
                    upload_filename=upload_name,
                    ip=client_ip,
                    mode=mode,
                    honeypot_email=request.form.get("email", ""),
                    honeypot_url=request.form.get("url", ""),
                    force_capcode=force_capcode,
                )

                # Cleanup temp file
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)

                # Redirect to front or thread; set delpass cookie so it's "married" to user's session/cookie for future convenience
                if request.form.get("thread"):
                    loc = f"{script_root}/{request.form['thread']}/"
                else:
                    loc = script_root + "/"
                resp = Response(status=303, headers={"Location": loc})
                if del_password:
                    resp.set_cookie("delpass", del_password, httponly=True, samesite="Lax", max_age=86400*365, path=script_root + "/" if script_root else "/")
                return _secure(resp, cfg)

            except Exception as e:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
                return redirect_to_error_page(
                    script_root,
                    safe_user_error(e),
                    cfg,
                )

        # === FRONT PAGE ===
        if effective_path in ("/", "/index.html"):
            from .core.storage import list_threads as list_t, load_thread
            res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
            bmode = getattr(cfg, "BOARD_MODE", "imageboard")
            is_img = bmode == "imageboard"
            limit = getattr(cfg, "THREADS_DISPLAYED", 10)
            if bmode == "blog":
                limit = limit * 2  # show a few more entries on blog front
            lightweight = list_t(res_dir, sort_by="lasthit")[:limit]

            # Load full thread data 
            display_threads = []
            if is_img:
                # imageboard: classic abbreviated "OP + last few replies"
                replies_per_thread = getattr(cfg, "REPLIES_PER_THREAD", 5)
                for meta in lightweight:
                    thread = load_thread(res_dir, meta["thread"])
                    if not thread or not thread.posts:
                        continue
                    posts = thread.posts
                    op = posts[0]
                    all_replies = posts[1:] if len(posts) > 1 else []
                    shown_replies = all_replies[-replies_per_thread:]
                    omitted = max(0, len(all_replies) - len(shown_replies))
                    display_threads.append({
                        "thread": thread.thread,
                        "title": thread.title,
                        "op": op,
                        "replies": shown_replies,
                        "postcount": thread.postcount,
                        "omitted": omitted,
                        "has_image": bool(op.image),
                    })
            else:
                # textboard or blog: flat list of entries (OPs), no inline replies shown on front
                # (blog focuses on the post form + list of entries)
                for meta in lightweight:
                    thread = load_thread(res_dir, meta["thread"])
                    if not thread or not thread.posts:
                        continue
                    op = thread.posts[0]
                    display_threads.append({
                        "thread": thread.thread,
                        "title": thread.title,
                        "op": op,
                        "replies": [],  # flat
                        "postcount": thread.postcount,
                        "omitted": 0,
                        "has_image": bool(getattr(op, "image", None)),
                    })

            # All modes use the styled "image" templates (textboard forces no images; blog allows images on admin entries,
            # flat data, mode-aware labels + BLOG_COMMENTS; blog catalog is linear dated list).
            # The "message/" templates are kept only for legacy exact "message" mode or fallback.
            tmpl_prefix = "image"
            try:
                template = jinja_env.get_template(f"{tmpl_prefix}/front.html")
            except Exception:
                template = jinja_env.get_template("image/front.html")  # fallback

            # Captcha for forms (skip for admin-capped posts, which are handled in POST)
            enable_captcha = getattr(cfg, "ENABLE_CAPTCHA", False)
            captcha_token = None
            captcha_image = None
            if enable_captcha:
                from .captcha import create_captcha
                captcha_token, captcha_image = create_captcha(
                    difficulty=getattr(cfg, "CAPTCHA_DIFFICULTY", 0.6),
                    board_dir=board_dir,
                    cfg=cfg,
                )

            blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"

            html = template.render(
                title=cfg.TITLE,
                subtitle=getattr(cfg, "SUBTITLE", ""),
                anon_name=getattr(cfg, "S_ANONAME", "Anonymous"),
                require_title=getattr(cfg, "REQUIRE_THREAD_TITLE", False),
                allow_images=getattr(cfg, "ALLOW_IMAGE_THREADS", True),
                threads=display_threads,
                error=error,
                mode=bmode,
                blog_comments=blog_comments,
                initial_theme_css=initial_theme_css,
                default_style=default_style_name,
                enable_captcha=enable_captcha,
                captcha_token=captcha_token,
                captcha_image=captcha_image,
                is_admin=is_admin,
                csrf_token=public_csrf,
                default_delpass=default_delpass,
                script_root=script_root,
            )
            resp = Response(html, mimetype="text/html")
            if not request.cookies.get("csrf_token"):
                resp.set_cookie("csrf_token", public_csrf, httponly=True, samesite="Lax", max_age=86400*30, path=script_root + "/" if script_root else "/")
            if newly_created_delpass:
                resp.set_cookie("delpass", default_delpass, httponly=True, samesite="Lax", max_age=86400*365, path=script_root + "/" if script_root else "/")
            return _secure(resp, cfg)

        # === CATALOG VIEW ===
        # imageboard / textboard: classic 4chan-style grid (thumbnails or "No image" + short teasers, lasthit order)
        # blog: linear blog-style list with dates, titles, excerpts (newest first by creation)
        if effective_path.rstrip("/") in ("/catalog", "/catalog.html"):
            bmode = getattr(cfg, "BOARD_MODE", "imageboard")
            if bmode not in ("imageboard", "textboard", "blog"):
                return _secure(
                    Response("Catalog is only available in imageboard, textboard, and blog modes.", status=404),
                    cfg,
                )
            from .core.storage import list_threads as list_t, load_thread
            res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")

            display_limit = getattr(cfg, "THREADS_DISPLAYED", 10)
            if bmode == "blog":
                # Blog catalog: reverse chrono by thread creation (id), show more entries, longer excerpts
                lightweight = list_t(res_dir, sort_by="thread")[: max(50, display_limit * 5)]
            else:
                lightweight = list_t(res_dir, sort_by="lasthit")[: display_limit * 3]

            display_threads = []
            for meta in lightweight:
                thread = load_thread(res_dir, meta["thread"])
                if not thread or not thread.posts:
                    continue

                op = thread.posts[0]

                # Teaser / excerpt (strip tags for clean preview text)
                comment = op.comment_html or ""
                text_only = re2.sub(r'<[^>]+>', ' ', comment).strip()
                # imageboard keeps short; blog gets a meatier excerpt
                max_chars = 520 if bmode == "blog" else 180
                if len(text_only) > max_chars:
                    text_only = text_only[:max_chars].rsplit(" ", 1)[0] + "..."

                if bmode == "blog":
                    # For blog linear view prefer clean text excerpt
                    comment_preview = text_only
                else:
                    # Grid keeps a bit of html flavor (quotes etc)
                    if op.comment_html:
                        comment_preview = op.comment_html[:420] + ("..." if len(op.comment_html) > 420 else "")
                    else:
                        comment_preview = text_only

                # count images in thread for stats (imageboard only really cares)
                imagecount = sum(1 for p in thread.posts if getattr(p, "image", None))

                display_threads.append({
                    "thread": thread.thread,
                    "title": thread.title,
                    "op": op,
                    "postcount": thread.postcount,
                    "imagecount": imagecount,
                    "comment_preview": comment_preview,
                    "date": getattr(op, "date", ""),
                })

            tmpl_prefix = "image"
            try:
                template = jinja_env.get_template(f"{tmpl_prefix}/catalog.html")
            except Exception:
                template = jinja_env.get_template("image/catalog.html")  # fallback

            blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"

            html = template.render(
                title=cfg.TITLE,
                subtitle=getattr(cfg, "SUBTITLE", ""),
                threads=display_threads,
                error=error,
                mode=bmode,
                blog_comments=blog_comments,
                initial_theme_css=initial_theme_css,
                default_style=default_style_name,
                script_root=script_root,
            )
            return _secure(Response(html, mimetype="text/html"), cfg)

        # === THREAD VIEW ===
        # Match /12345/ or /12345
        m = re.match(r"^/(\d+)", effective_path)
        if m:
            thread_id = int(m.group(1))
            from .core.storage import load_thread
            res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
            thread = load_thread(res_dir, thread_id)
            if not thread:
                return _secure(Response("Thread not found", status=404), cfg)

            bmode = getattr(cfg, "BOARD_MODE", "imageboard")
            allow_images = getattr(cfg, "ALLOW_IMAGE_REPLIES", True)
            tmpl_prefix = "image"
            try:
                template = jinja_env.get_template(f"{tmpl_prefix}/thread.html")
            except Exception:
                template = jinja_env.get_template("image/thread.html")

            # Captcha for reply form (skipped for admin-capped posts on submit)
            enable_captcha = getattr(cfg, "ENABLE_CAPTCHA", False)
            captcha_token = None
            captcha_image = None
            if enable_captcha:
                from .captcha import create_captcha
                captcha_token, captcha_image = create_captcha(
                    difficulty=getattr(cfg, "CAPTCHA_DIFFICULTY", 0.6),
                    board_dir=board_dir,
                    cfg=cfg,
                )

            # For blog mode, control comment form based on BLOG_COMMENTS
            blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"
            if bmode == "blog" and blog_comments == "text_only":
                allow_images = False

            html = template.render(
                title=cfg.TITLE,
                subtitle=getattr(cfg, "SUBTITLE", ""),
                thread=thread,
                allow_images=allow_images,
                mode=bmode,
                initial_theme_css=initial_theme_css,
                default_style=default_style_name,
                enable_captcha=enable_captcha,
                captcha_token=captcha_token,
                captcha_image=captcha_image,
                is_admin=is_admin,
                blog_comments=blog_comments,
                csrf_token=public_csrf,
                default_delpass=default_delpass,
                script_root=script_root,
            )
            resp = Response(html, mimetype="text/html")
            if not request.cookies.get("csrf_token"):
                resp.set_cookie("csrf_token", public_csrf, httponly=True, samesite="Lax", max_age=86400*30, path=script_root + "/" if script_root else "/")
            if newly_created_delpass:
                resp.set_cookie("delpass", default_delpass, httponly=True, samesite="Lax", max_age=86400*365, path=script_root + "/" if script_root else "/")
            return _secure(resp, cfg)

        return render_error_page(
            jinja_env,
            cfg,
            status=404,
            heading="Page not found",
            message="The page you requested does not exist.",
            script_root=script_root,
        )

    # Use proper SharedDataMiddleware for serving board static files (src/, thumb/, css/, etc.)
    # This is much more reliable than manual handling inside the view.
    #
    # For Caddy (user's reverse proxy): Add security headers in Caddyfile, e.g.:
    #   header {
    #       Strict-Transport-Security "max-age=31536000;"
    #       X-Content-Type-Options "nosniff"
    #       Referrer-Policy "same-origin"
    #       # CSP can be tuned for your CSS/JS
    #   }
    #   Also use Caddy's rate limiting: rate_limit { ... } for posts etc.
    static_folders = {
        '/src': str(board_dir / getattr(cfg, 'IMG_DIR', 'src/').rstrip('/')),
        '/thumb': str(board_dir / getattr(cfg, 'THUMB_DIR', 'thumb/').rstrip('/')),
        '/css': str(board_dir / getattr(cfg, 'CSS_DIR', 'css/').rstrip('/')),
        '/icons': str(board_dir / 'icons'),  # if present
    }

    # Also allow serving kareha.js and other top-level static from board if present
    # Fallback to package static for things like default css/js if not overridden in board
    pkg_static = str(Path(__file__).parent / "static")

    wrapped = SharedDataMiddleware(app, {
        **static_folders,
        '/': pkg_static,  # fallback for kareha.js etc. if not in board
    })

    # Trust X-Forwarded-For / X-Forwarded-Proto from Caddy (TRUSTED_PROXY_COUNT hops, default 1)
    trusted = int(getattr(cfg, "TRUSTED_PROXY_COUNT", 0) or 0)
    if trusted > 0:
        wrapped = ProxyFix(wrapped, x_for=trusted, x_proto=1, x_host=0, x_prefix=1)

    # Catch-all HTML error pages for unhandled exceptions (logs full traceback server-side)
    wrapped = wrap_with_error_pages(
        wrapped,
        cfg=cfg,
        jinja_env=jinja_env,
        board_dir=board_dir,
        base_path=base_path,
    )

    # Attach for introspection (on the final wsgi callable)
    wrapped.cfg = cfg
    wrapped.board_dir = board_dir
    wrapped.mode = getattr(cfg, "BOARD_MODE", "imageboard")
    wrapped.jinja_env = jinja_env

    return wrapped


def main():
    """Quick development server."""
    import sys
    board = sys.argv[1] if len(sys.argv) > 1 else "."
    mode = sys.argv[2] if len(sys.argv) > 2 else None
    app = make_app(board, mode)
    shown = mode or "(from BOARD_MODE in config.py or default)"
    print(f"Running Kareha on http://127.0.0.1:8000 (mode={shown})")
    run_simple("127.0.0.1", 8000, app, use_reloader=True, use_debugger=False)


if __name__ == "__main__":
    main()
