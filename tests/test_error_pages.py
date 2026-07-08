"""Tests for catch-all error page handling."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.wrappers import Request

from kareha.error_pages import (
    build_error_response,
    redirect_to_error_page,
    render_flash_error_page,
    user_error_status,
    wrap_with_error_pages,
    FLASH_ERROR_COOKIE,
    FLASH_STATUS_COOKIE,
)


class _Cfg:
    TITLE = "Test Board"
    DEFAULT_STYLE = "Burichan"
    SHOW_ERROR_DETAILS = True
    ERROR_LOG_FILE = ""


def _env():
    tpl = Path(__file__).resolve().parents[1] / "src" / "kareha" / "templates"
    return Environment(
        loader=FileSystemLoader(str(tpl)),
        autoescape=select_autoescape(["html"]),
    )


def test_render_error_page_hides_traceback_by_default():
    cfg = _Cfg()
    cfg.SHOW_ERROR_DETAILS = False
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "SCRIPT_NAME": ""}
    resp = build_error_response(
        environ,
        RuntimeError("secret internal detail"),
        cfg=cfg,
        jinja_env=_env(),
        board_dir=Path("."),
        base_path="",
    )
    body = resp.get_data(as_text=True)
    assert "secret internal detail" not in body
    assert "Something went wrong" in body
    assert resp.status_code == 500


def test_user_error_status_for_blog_admin():
    assert user_error_status("Only administrators can create new blog entries.") == 403
    assert user_error_status("Comments are disabled on this blog.") == 403


def test_redirect_to_error_page_uses_flash_cookie():
    cfg = _Cfg()
    resp = redirect_to_error_page(
        "/blog",
        "Only administrators can create new blog entries.",
        cfg,
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "/blog/error"
    assert FLASH_ERROR_COOKIE in resp.headers.get("Set-Cookie", "")


def test_render_flash_error_page_reads_cookie():
    cfg = _Cfg()

    class _Req:
        cookies = {
            FLASH_ERROR_COOKIE: "Comments are disabled on this blog.",
            FLASH_STATUS_COOKIE: "403",
        }

    resp = render_flash_error_page(_Req(), _env(), cfg, "/blog")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 403
    assert "Comments are disabled" in body
    assert "Not allowed" in body


def test_error_middleware_catches_exceptions():
    cfg = _Cfg()

    def boom(environ, start_response):
        raise ValueError("boom")

    wrapped = wrap_with_error_pages(
        boom,
        cfg=cfg,
        jinja_env=_env(),
        board_dir=Path("."),
        base_path="/board",
    )
    from werkzeug.test import Client

    client = Client(wrapped)
    resp = client.get("/")
    assert resp.status_code == 500
    assert "Something went wrong" in resp.get_data(as_text=True)