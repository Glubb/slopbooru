"""Public board pages: front, catalog, thread."""
from __future__ import annotations

import re
from typing import Any

from werkzeug.wrappers import Response

from ..app_context import RequestState, attach_public_cookies
from ..core.storage import list_threads, load_thread
from ..error_pages import render_error_page

_PAGE_PATH_RE = re.compile(r"^/page/(\d+)/?$")


def parse_page_number(request: Any, effective_path: str) -> int:
    m = _PAGE_PATH_RE.match(effective_path or "")
    if m:
        return max(1, int(m.group(1)))
    raw = (getattr(request, "args", {}) or {}).get("page") or "1"
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def paginate(items: list, page: int, per_page: int) -> tuple[list, dict[str, Any]]:
    total = len(items)
    if per_page <= 0:
        per_page = total or 1
    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    slice_ = items[start:start + per_page]
    return slice_, {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def page_href(script_root: str, page: int) -> str:
    if page <= 1:
        return (script_root or "") + "/"
    return f"{script_root}/page/{page}"


def _captcha(state: RequestState) -> tuple[bool, str | None, str | None]:
    cfg = state.ctx.cfg
    enable = bool(getattr(cfg, "ENABLE_CAPTCHA", False))
    token = image = None
    if enable:
        from ..captcha import create_captcha
        token, image = create_captcha(
            difficulty=getattr(cfg, "CAPTCHA_DIFFICULTY", 0.6),
            board_dir=state.ctx.board_dir,
            cfg=cfg,
        )
    return enable, token, image


def _display_threads(
    state: RequestState,
    lightweight: list[dict],
    *,
    replies_per_thread: int = 0,
) -> list[dict]:
    cfg = state.ctx.cfg
    res_dir = state.ctx.board_dir / getattr(cfg, "RES_DIR", "res/")
    show_n = max(0, int(replies_per_thread or 0))
    out = []
    for meta in lightweight:
        thread = load_thread(res_dir, meta["thread"])
        if not thread or not thread.posts:
            continue
        op = thread.posts[0]
        if show_n > 0:
            all_replies = thread.posts[1:]
            shown = all_replies[-show_n:]
            omitted = max(0, len(all_replies) - len(shown))
        else:
            shown = []
            omitted = 0
        out.append({
            "thread": thread.thread,
            "title": thread.title,
            "op": op,
            "replies": shown,
            "postcount": thread.postcount,
            "omitted": omitted,
            "has_image": bool(getattr(op, "image", None)),
            "pinned": bool(getattr(thread, "pinned", False) or meta.get("pinned")),
        })
    return out


def render_front(state: RequestState) -> Response:
    ctx = state.ctx
    cfg = ctx.cfg
    bmode = getattr(cfg, "BOARD_MODE", "imageboard")
    res_dir = ctx.board_dir / getattr(cfg, "RES_DIR", "res/")
    listed = int(getattr(cfg, "THREADS_LISTED", 0) or 0)
    per_page = int(getattr(cfg, "THREADS_DISPLAYED", 10) or 10)
    generation = (getattr(cfg, "PAGE_GENERATION", "paged") or "paged").lower()

    all_meta = list_threads(res_dir, sort_by="lasthit")
    pinned = [m for m in all_meta if m.get("pinned")]
    unpinned = [m for m in all_meta if not m.get("pinned")]
    if listed > 0:
        unpinned = unpinned[:listed]
    all_meta = pinned + unpinned

    if generation != "paged":
        # single / monthly: one page, show up to THREADS_LISTED (or all if 0)
        page = 1
        page_items, pager = paginate(all_meta, 1, len(all_meta) or 1)
        pager["pages"] = 1
        pager["has_prev"] = False
        pager["has_next"] = False
    else:
        page = parse_page_number(state.request, state.effective_path)
        page_items, pager = paginate(all_meta, page, per_page)

    blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"
    if bmode == "imageboard":
        front_replies = int(getattr(cfg, "REPLIES_PER_THREAD", 3) or 0)
    elif bmode == "blog" and blog_comments != "disabled":
        front_replies = int(getattr(cfg, "BLOG_FRONT_COMMENTS", 3) or 0)
    else:
        front_replies = 0
    display_threads = _display_threads(state, page_items, replies_per_thread=front_replies)
    enable_captcha, captcha_token, captcha_image = _captcha(state)

    template = ctx.jinja_env.get_template("image/front.html")

    html = template.render(
        title=cfg.TITLE,
        subtitle=getattr(cfg, "SUBTITLE", ""),
        anon_name=getattr(cfg, "S_ANONAME", "Anonymous"),
        require_title=getattr(cfg, "REQUIRE_THREAD_TITLE", False),
        allow_images=getattr(cfg, "ALLOW_IMAGE_THREADS", True),
        threads=display_threads,
        error=state.error,
        mode=bmode,
        blog_comments=blog_comments,
        initial_theme_css=ctx.initial_theme_css,
        default_style=ctx.default_style_name,
        enable_captcha=enable_captcha,
        captcha_token=captcha_token,
        captcha_image=captcha_image,
        is_admin=state.is_admin,
        csrf_token=state.public_csrf,
        default_delpass=state.default_delpass,
        script_root=state.script_root,
        pager=pager,
        page_href=lambda n: page_href(state.script_root, n),
    )
    return attach_public_cookies(Response(html, mimetype="text/html"), state)


def render_catalog(state: RequestState) -> Response:
    ctx = state.ctx
    cfg = ctx.cfg
    bmode = getattr(cfg, "BOARD_MODE", "imageboard")
    if bmode not in ("imageboard", "textboard", "blog"):
        return render_error_page(
            ctx.jinja_env, cfg, status=404,
            heading="Not found",
            message="Catalog is only available in imageboard, textboard, and blog modes.",
            script_root=state.script_root,
        )

    res_dir = ctx.board_dir / getattr(cfg, "RES_DIR", "res/")
    display_limit = getattr(cfg, "THREADS_DISPLAYED", 10)
    sort_by = "thread" if bmode == "blog" else "lasthit"
    all_meta = list_threads(res_dir, sort_by=sort_by)
    pinned = [m for m in all_meta if m.get("pinned")]
    unpinned = [m for m in all_meta if not m.get("pinned")]
    cap = max(50, display_limit * 5) if bmode == "blog" else display_limit * 3
    lightweight = pinned + unpinned[:cap]

    display_threads = []
    for meta in lightweight:
        thread = load_thread(res_dir, meta["thread"])
        if not thread or not thread.posts:
            continue
        op = thread.posts[0]
        comment = op.comment_html or ""
        text_only = re.sub(r"<[^>]+>", " ", comment).strip()
        max_chars = 520 if bmode == "blog" else 180
        if len(text_only) > max_chars:
            text_only = text_only[:max_chars].rsplit(" ", 1)[0] + "..."
        if bmode == "blog":
            comment_preview = text_only
        elif op.comment_html:
            comment_preview = op.comment_html[:420] + ("..." if len(op.comment_html) > 420 else "")
        else:
            comment_preview = text_only
        imagecount = sum(1 for p in thread.posts if getattr(p, "image", None))
        display_threads.append({
            "thread": thread.thread,
            "title": thread.title,
            "op": op,
            "postcount": thread.postcount,
            "imagecount": imagecount,
            "comment_preview": comment_preview,
            "date": getattr(op, "date", ""),
            "pinned": bool(getattr(thread, "pinned", False)),
        })

    blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"
    template = ctx.jinja_env.get_template("image/catalog.html")
    html = template.render(
        title=cfg.TITLE,
        subtitle=getattr(cfg, "SUBTITLE", ""),
        threads=display_threads,
        error=state.error,
        mode=bmode,
        blog_comments=blog_comments,
        initial_theme_css=ctx.initial_theme_css,
        default_style=ctx.default_style_name,
        script_root=state.script_root,
    )
    from ..http_helpers import apply_security_headers
    return apply_security_headers(Response(html, mimetype="text/html"), cfg)


def render_thread(state: RequestState, thread_id: int) -> Response:
    ctx = state.ctx
    cfg = ctx.cfg
    res_dir = ctx.board_dir / getattr(cfg, "RES_DIR", "res/")
    thread = load_thread(res_dir, thread_id)
    if not thread:
        return render_error_page(
            ctx.jinja_env, cfg, status=404,
            heading="Thread not found",
            message="The thread you requested does not exist.",
            script_root=state.script_root,
        )

    bmode = getattr(cfg, "BOARD_MODE", "imageboard")
    allow_images = getattr(cfg, "ALLOW_IMAGE_REPLIES", True)
    enable_captcha, captcha_token, captcha_image = _captcha(state)
    blog_comments = getattr(cfg, "BLOG_COMMENTS", "enabled") if bmode == "blog" else "enabled"
    if bmode == "blog" and blog_comments == "text_only":
        allow_images = False

    report_captcha = bool(getattr(cfg, "ENABLE_REPORT_CAPTCHA", True))
    report_captcha_token = report_captcha_image = None
    if report_captcha:
        from ..captcha import create_captcha
        report_captcha_token, report_captcha_image = create_captcha(
            difficulty=getattr(cfg, "CAPTCHA_DIFFICULTY", 0.6),
            board_dir=ctx.board_dir,
            cfg=cfg,
        )

    template = ctx.jinja_env.get_template("image/thread.html")
    html = template.render(
        title=cfg.TITLE,
        subtitle=getattr(cfg, "SUBTITLE", ""),
        thread=thread,
        allow_images=allow_images,
        mode=bmode,
        initial_theme_css=ctx.initial_theme_css,
        default_style=ctx.default_style_name,
        enable_captcha=enable_captcha,
        captcha_token=captcha_token,
        captcha_image=captcha_image,
        enable_report_captcha=report_captcha,
        report_captcha_token=report_captcha_token,
        report_captcha_image=report_captcha_image,
        is_admin=state.is_admin,
        blog_comments=blog_comments,
        csrf_token=state.public_csrf,
        default_delpass=state.default_delpass,
        script_root=state.script_root,
    )
    return attach_public_cookies(Response(html, mimetype="text/html"), state)
