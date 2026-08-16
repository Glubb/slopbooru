"""
WSGI entry point for Kareha Python.

Usage:
    gunicorn "kareha.wsgi:make_app(board_dir='.', mode='imageboard')"
    python -m wsgiref.simple_server -m kareha.wsgi:make_app
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix

from .app_context import AppContext, build_request_state, looks_like_admin_path
from .config import load_config, make_config_object
from .error_pages import render_error_page, render_flash_error_page, wrap_with_error_pages
from .utils import ensure_board_directories
from .views.actions import handle_delete, handle_post, handle_report
from .views.admin import handle_admin
from .views.board import render_catalog, render_front, render_thread
from . import config as config_module

_THREAD_PATH_RE = re.compile(r"^/(\d+)")
_PAGE_PATH_RE = re.compile(r"^/page/\d+/?$")


def make_app(board_dir: str | Path = ".", mode: str | None = None, base_path: str = "", **cfg_overrides: Any):
    """
    Factory that returns a WSGI application for a specific board.

    board_dir: directory containing config.py, res/, src/, thumb/, css/, include/, spam.txt

    mode: Optional override for the board type. Wins over BOARD_MODE in config.py.

    base_path: Optional URL prefix when mounted under a subpath (e.g. "/board1").
    """
    board_dir = Path(board_dir).resolve()
    cfg_dict = load_config(board_dir / "config.py", mode=mode)
    cfg_dict.update(cfg_overrides)
    cfg = make_config_object(cfg_dict)
    board_mode = getattr(cfg, "BOARD_MODE", "imageboard")

    config_module.current_config = cfg
    ensure_board_directories(board_dir, cfg)

    base_path = (base_path or "").strip()
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    base_path = base_path.rstrip("/")

    default_style_name = getattr(cfg, "DEFAULT_STYLE", "Burichan")
    initial_theme_css = default_style_name.lower().replace(" ", "_") + ".css"

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

    ctx = AppContext(
        board_dir=board_dir,
        cfg=cfg,
        jinja_env=jinja_env,
        board_mode=board_mode,
        base_path=base_path,
        default_style_name=default_style_name,
        initial_theme_css=initial_theme_css,
    )

    @Request.application
    def app(request: Request) -> Response:
        state = build_request_state(request, ctx)
        task = request.args.get("task") or request.form.get("task")

        if looks_like_admin_path(state):
            return handle_admin(state)

        if task == "delete":
            return handle_delete(state)

        if task == "report":
            return handle_report(state)

        if state.effective_path.rstrip("/") == "/error":
            return render_flash_error_page(request, jinja_env, cfg, state.script_root)

        if request.method == "POST" and task == "post":
            return handle_post(state)

        if state.effective_path in ("/", "/index.html") or _PAGE_PATH_RE.match(state.effective_path):
            return render_front(state)

        if state.effective_path.rstrip("/") in ("/catalog", "/catalog.html"):
            return render_catalog(state)

        m = _THREAD_PATH_RE.match(state.effective_path)
        if m:
            return render_thread(state, int(m.group(1)))

        return render_error_page(
            jinja_env,
            cfg,
            status=404,
            heading="Page not found",
            message="The page you requested does not exist.",
            script_root=state.script_root,
        )

    static_folders = {
        "/src": str(board_dir / getattr(cfg, "IMG_DIR", "src/").rstrip("/")),
        "/thumb": str(board_dir / getattr(cfg, "THUMB_DIR", "thumb/").rstrip("/")),
        "/css": str(board_dir / getattr(cfg, "CSS_DIR", "css/").rstrip("/")),
        "/icons": str(board_dir / "icons"),
    }
    pkg_static = str(Path(__file__).parent / "static")
    wrapped = SharedDataMiddleware(app, {
        **static_folders,
        "/": pkg_static,
    })

    trusted = int(getattr(cfg, "TRUSTED_PROXY_COUNT", 0) or 0)
    if trusted > 0:
        wrapped = ProxyFix(wrapped, x_for=trusted, x_proto=1, x_host=0, x_prefix=1)

    wrapped = wrap_with_error_pages(
        wrapped,
        cfg=cfg,
        jinja_env=jinja_env,
        board_dir=board_dir,
        base_path=base_path,
    )

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
