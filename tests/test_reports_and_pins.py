"""Report-page captcha/theme and pinned-thread behaviour."""
from __future__ import annotations

from werkzeug.test import Client

from kareha import config as config_module
from kareha.config import make_config_object
from kareha.config_defaults import get_defaults_dict
from kareha.core.admin import moderate_thread_action
from kareha.core.posting import post_stuff
from kareha.core.storage import list_threads, load_thread, save_thread
from kareha.runtime_store import captcha_put
from kareha.wsgi import make_app


def _csrf(client) -> str:
    cookie = client.get_cookie("csrf_token")
    return cookie.value if cookie else ""


def _write_cfg(board, **extra):
    lines = [
        'ADMIN_PASS = "test-admin-pass"',
        'SECRET = "test-secret-at-least-32-chars!!"',
        "MAX_POSTS = 0",
        "DUPLICATE_WINDOW = 0",
        "ENABLE_REPORT_CAPTCHA = True",
        "RATE_LIMIT_POSTS_PER_MIN = 1000",
        "REPORT_RATE_LIMIT_POSTS = 1000",
    ]
    for k, v in extra.items():
        lines.append(f"{k} = {v!r}" if isinstance(v, str) else f"{k} = {v}")
    (board / "config.py").write_text("\n".join(lines) + "\n")


def _set_runtime_cfg(board, **overrides):
    d = get_defaults_dict()
    d.update({
        "ADMIN_PASS": "test-admin-pass",
        "SECRET": "test-secret-at-least-32-chars!!",
        "MAX_POSTS": 0,
        "DUPLICATE_WINDOW": 0,
        "ENABLE_REPORT_CAPTCHA": True,
    })
    d.update(overrides)
    obj = make_config_object(d)
    config_module.current_config = obj
    (board / "res").mkdir(exist_ok=True)
    return obj


def test_report_page_uses_theme_and_captcha(tmp_path):
    _write_cfg(tmp_path)
    cfg = _set_runtime_cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="report me")
    app = make_app(tmp_path, mode="imageboard")
    client = Client(app)
    resp = client.get(f"/?task=report&thread={tid}&post={tid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert f"/css/{cfg.DEFAULT_STYLE.lower().replace(' ', '_')}.css" in body or "/css/" in body
    assert 'id="reportform"' in body
    assert 'name="captcha"' in body
    assert "data:image/png;base64," in body
    assert f"No.{tid}" in body


def test_report_requires_captcha(tmp_path):
    _write_cfg(tmp_path)
    _set_runtime_cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="report me")
    app = make_app(tmp_path, mode="imageboard")
    client = Client(app)
    client.get(f"/?task=report&thread={tid}&post={tid}")
    resp = client.post(
        "/?task=report",
        data={
            "thread": str(tid),
            "post": str(tid),
            "reason": "spam",
            "csrf": _csrf(client),
            "captcha": "WRONG",
            "captcha_token": "nope",
        },
    )
    body = resp.get_data(as_text=True)
    assert "Incorrect or expired captcha" in body
    assert "Report(s) submitted" not in body


def test_report_succeeds_with_valid_captcha(tmp_path):
    _write_cfg(tmp_path)
    cfg = _set_runtime_cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="report me")
    app = make_app(tmp_path, mode="imageboard")
    client = Client(app)
    get_resp = client.get(f"/?task=report&thread={tid}&post={tid}")
    captcha_put(tmp_path, cfg, "goodtok", "ABCDE", 120)
    resp = client.post(
        "/?task=report",
        data={
            "thread": str(tid),
            "post": str(tid),
            "reason": "illegal content",
            "csrf": _csrf(client),
            "captcha": "ABCDE",
            "captcha_token": "goodtok",
        },
    )
    body = resp.get_data(as_text=True)
    assert get_resp.status_code == 200
    assert "Report(s) submitted" in body
    reports = (tmp_path / "reports.json").read_text(encoding="utf-8")
    assert "illegal content" in reports


def test_pinned_thread_sorts_first(tmp_path):
    cfg = _set_runtime_cfg(tmp_path)
    older = post_stuff(tmp_path, comment="older bump")
    newer = post_stuff(tmp_path, comment="newer bump")
    assert moderate_thread_action(tmp_path, older, "pin", True, cfg)
    order = [m["thread"] for m in list_threads(tmp_path / "res")]
    assert order[0] == older
    assert newer in order


def test_pinned_thread_survives_trim(tmp_path):
    cfg = _set_runtime_cfg(tmp_path, MAX_THREADS=1)
    pinned = post_stuff(tmp_path, comment="keep me forever")
    moderate_thread_action(tmp_path, pinned, "pin", True, cfg)
    post_stuff(tmp_path, comment="normal one")
    post_stuff(tmp_path, comment="normal two")
    ids = {m["thread"] for m in list_threads(tmp_path / "res")}
    assert pinned in ids
    assert len(ids) == 2  # 1 pin + MAX_THREADS unpinned


def test_pinned_thread_skips_autoclose(tmp_path):
    cfg = _set_runtime_cfg(tmp_path, AUTOCLOSE_POSTS=2)
    tid = post_stuff(tmp_path, comment="sticky op")
    thread = load_thread(tmp_path / "res", tid)
    thread.pinned = True
    save_thread(thread, tmp_path / "res")
    post_stuff(tmp_path, thread_id=tid, comment="second")
    post_stuff(tmp_path, thread_id=tid, comment="third still allowed")
    thread = load_thread(tmp_path / "res", tid)
    assert thread.pinned
    assert not thread.closed
    assert thread.postcount == 3
