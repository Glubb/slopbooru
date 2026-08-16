"""Post, delete, and report request handlers."""
from __future__ import annotations

from pathlib import Path

from werkzeug.wrappers import Response

from ..app_context import RequestState, attach_public_cookies, cookie_path, secure
from ..core.deletion import delete_post
from ..core.posting import PostError, post_stuff
from ..core.reports import submit_report
from ..error_pages import redirect_to_error_page
from ..http_helpers import apply_security_headers, safe_user_error
from ..runtime_store import check_rate_limit as shared_check_rate_limit


def _check_post_rate_limit(board_dir: Path, ip: str, cfg) -> bool:
    return shared_check_rate_limit(
        board_dir, cfg, "posts", ip,
        max_events=getattr(cfg, "RATE_LIMIT_POSTS_PER_MIN", 5),
        window_seconds=float(getattr(cfg, "RATE_LIMIT_WINDOW_SECONDS", 60)),
    )


def _check_report_rate_limit(board_dir: Path, ip: str, cfg) -> bool:
    return shared_check_rate_limit(
        board_dir, cfg, "reports", ip,
        max_events=getattr(cfg, "REPORT_RATE_LIMIT_POSTS", 10),
        window_seconds=float(getattr(cfg, "REPORT_RATE_LIMIT_WINDOW_SECONDS", 300)),
    )


def handle_delete(state: RequestState) -> Response:
    ctx = state.ctx
    request = state.request
    if request.method != "POST":
        return secure(Response("Deletion requires POST.", status=405), ctx.cfg)
    try:
        raw = (request.form.get("delete") or "").strip()
        if "," not in raw:
            raise ValueError("bad delete param")
        thread_id_str, post_num_str = raw.split(",", 1)
        tid = int(thread_id_str)
        pid = int(post_num_str)
        provided_pass = (request.form.get("password") or "").strip()
        file_only = request.form.get("fileonly") in ("1", "true", "yes", "on")
        secret = getattr(ctx.cfg, "SECRET", "")
        if not delete_post(
            ctx.board_dir, tid, pid,
            password=provided_pass, file_only=file_only,
            secret=secret, cfg=ctx.cfg,
        ):
            raise ValueError("bad deletion password")
        ref = request.referrer or state.script_root + "/"
        return secure(Response(status=303, headers={"Location": ref}), ctx.cfg)
    except Exception as e:
        return redirect_to_error_page(
            state.script_root, safe_user_error(e, context="delete"), ctx.cfg,
        )


def _report_captcha_enabled(cfg) -> bool:
    return bool(getattr(cfg, "ENABLE_REPORT_CAPTCHA", True))


def _make_report_captcha(state: RequestState) -> tuple[str | None, str | None]:
    if not _report_captcha_enabled(state.ctx.cfg):
        return None, None
    from ..captcha import create_captcha
    return create_captcha(
        difficulty=getattr(state.ctx.cfg, "CAPTCHA_DIFFICULTY", 0.6),
        board_dir=state.ctx.board_dir,
        cfg=state.ctx.cfg,
    )


def _render_report_page(
    state: RequestState,
    *,
    thread_id: str = "",
    post_num: str = "",
    reason: str = "",
    error: str = "",
    submitted: bool = False,
) -> Response:
    ctx = state.ctx
    token = image = None
    if not submitted and _report_captcha_enabled(ctx.cfg):
        token, image = _make_report_captcha(state)
    html = ctx.jinja_env.get_template("report.html").render(
        title=getattr(ctx.cfg, "TITLE", "Board"),
        initial_theme_css=ctx.initial_theme_css,
        script_root=state.script_root,
        thread_id=thread_id,
        post_num=post_num,
        reason=reason,
        error=error,
        submitted=submitted,
        enable_captcha=_report_captcha_enabled(ctx.cfg),
        captcha_token=token,
        captcha_image=image,
        csrf_token=state.public_csrf,
    )
    return attach_public_cookies(Response(html, mimetype="text/html"), state)


def handle_report(state: RequestState) -> Response:
    ctx = state.ctx
    request = state.request

    if request.method == "POST":
        reason = (request.form.get("reason") or "").strip()
        thread_id = (request.form.get("thread") or "").strip()
        post_num = (request.form.get("post") or "").strip()
        try:
            if not _check_report_rate_limit(ctx.board_dir, state.client_ip, ctx.cfg):
                return _render_report_page(
                    state, thread_id=thread_id, post_num=post_num, reason=reason,
                    error="Too many reports. Please wait.",
                )
            submitted_csrf = request.form.get("csrf", "")
            if state.public_csrf and submitted_csrf != state.public_csrf:
                return _render_report_page(
                    state, thread_id=thread_id, post_num=post_num, reason=reason,
                    error="CSRF validation failed. Please refresh the page and try again.",
                )
            if not reason:
                return _render_report_page(
                    state, thread_id=thread_id, post_num=post_num,
                    error="Reason is required.",
                )
            if len(reason) > 2000:
                reason = reason[:2000]

            if _report_captcha_enabled(ctx.cfg):
                from ..captcha import validate_captcha
                if not validate_captcha(
                    request.form.get("captcha_token", ""),
                    request.form.get("captcha", "") or "",
                    board_dir=ctx.board_dir,
                    cfg=ctx.cfg,
                ):
                    return _render_report_page(
                        state, thread_id=thread_id, post_num=post_num, reason=reason,
                        error="Incorrect or expired captcha.",
                    )

            reports_to_submit = []
            if thread_id and post_num:
                reports_to_submit.append((int(thread_id), int(post_num)))
            for val in request.form.getlist("report"):
                try:
                    t_id, p_num = val.split(",")
                    reports_to_submit.append((int(t_id), int(p_num)))
                except ValueError:
                    continue

            if not reports_to_submit:
                return _render_report_page(
                    state, thread_id=thread_id, post_num=post_num, reason=reason,
                    error="No posts selected to report.",
                )

            for t_id, p_num in reports_to_submit:
                submit_report(ctx.board_dir, t_id, p_num, reason, state.client_ip)

            return _render_report_page(
                state,
                thread_id=thread_id or str(reports_to_submit[0][0]),
                post_num=post_num,
                submitted=True,
            )
        except Exception:
            return _render_report_page(
                state, thread_id=thread_id, post_num=post_num, reason=reason,
                error="Report failed.",
            )

    thread_id = (request.args.get("thread") or "").strip()
    post_num = (request.args.get("post") or "").strip()
    if not thread_id or not post_num:
        return _render_report_page(state, error="Missing thread or post.")
    if not thread_id.isdigit() or not post_num.isdigit():
        return _render_report_page(state, error="Invalid thread or post.")
    return _render_report_page(state, thread_id=thread_id, post_num=post_num)


def handle_post(state: RequestState) -> Response:
    ctx = state.ctx
    cfg = ctx.cfg
    request = state.request
    tmp_path = None
    upload_name = None
    try:
        board_mode = getattr(cfg, "BOARD_MODE", "imageboard")
        blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if board_mode == "blog" else "enabled"
        is_reply = bool(request.form.get("thread"))

        if board_mode == "blog":
            if not is_reply and not state.is_admin:
                raise PostError("Only administrators can create new blog entries.")
            if is_reply and blog_comments == "disabled":
                raise PostError("Comments are disabled on this blog.")

        if not _check_post_rate_limit(ctx.board_dir, state.client_ip, cfg):
            raise PostError("Rate limit exceeded. Please wait a minute before posting again.")

        submitted_csrf = request.form.get("csrf", "")
        if state.public_csrf and submitted_csrf != state.public_csrf:
            raise PostError("CSRF validation failed. Please refresh the page and try again.")

        del_password = request.form.get("password", "") or ""
        if not del_password:
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            del_password = "".join(secrets.choice(alphabet) for _ in range(8))

        uploaded_file = request.files.get("file")
        if uploaded_file and uploaded_file.filename:
            import tempfile
            orig = Path(uploaded_file.filename).name
            suffix = Path(orig).suffix.lower()
            allowed_exts = (
                getattr(cfg, "BLOG_ALLOWED_EXTENSIONS", ())
                if (board_mode == "blog" and state.is_admin)
                else getattr(cfg, "ALLOWED_EXTENSIONS", ())
            )
            if suffix and suffix not in allowed_exts:
                if not (board_mode == "blog" and state.is_admin):
                    raise PostError(f"Filetype {suffix} not allowed.")
            safe_suffix = "".join(c for c in suffix if c.isalnum() or c in ".-_")[:12]
            if not safe_suffix or safe_suffix == ".":
                safe_suffix = ".bin"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=safe_suffix)
            uploaded_file.save(tmp.name)
            tmp_path = tmp.name
            upload_name = orig[:200]

        if tmp_path and board_mode == "blog" and request.form.get("thread") and blog_comments == "text_only":
            Path(tmp_path).unlink(missing_ok=True)
            tmp_path = None
            upload_name = None
            raise PostError("Image posting not allowed in this context.")

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
                from ..captcha import validate_captcha
                if not validate_captcha(
                    request.form.get("captcha_token", ""),
                    request.form.get("captcha", "") or "",
                    board_dir=ctx.board_dir,
                    cfg=cfg,
                ):
                    raise PostError("Incorrect or expired captcha.")

        force_capcode = ""
        effective_name = request.form.get("field_a", "")
        if board_mode == "blog" and state.is_admin:
            effective_name = "Admin"
            capped = getattr(cfg, "CAPPED_TRIPS", {}) or {}
            if isinstance(capped, dict) and capped:
                force_capcode = next(iter(capped.values()))

        post_stuff(
            ctx.board_dir,
            thread_id=int(request.form.get("thread")) if request.form.get("thread") else None,
            name=effective_name,
            link=request.form.get("field_b", ""),
            title=request.form.get("title", ""),
            comment=request.form.get("comment", ""),
            markup=request.form.get("markup", "waka"),
            password=del_password,
            file_path=tmp_path,
            upload_filename=upload_name,
            ip=state.client_ip,
            mode=getattr(cfg, "BOARD_MODE", None),
            honeypot_email=request.form.get("email", ""),
            honeypot_url=request.form.get("url", ""),
            force_capcode=force_capcode,
        )

        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

        if request.form.get("thread"):
            loc = f"{state.script_root}/{request.form['thread']}/"
        else:
            loc = state.script_root + "/"
        resp = Response(status=303, headers={"Location": loc})
        if del_password:
            resp.set_cookie(
                "delpass", del_password, httponly=True, samesite="Lax",
                max_age=86400 * 365, path=cookie_path(state.script_root),
            )
        return apply_security_headers(resp, cfg)

    except Exception as e:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return redirect_to_error_page(state.script_root, safe_user_error(e), cfg)
