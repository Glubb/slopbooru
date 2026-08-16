"""Blog mode BLOG_COMMENTS config and front-page comment preview."""
import textwrap

from werkzeug.test import Client

from kareha import config as config_module
from kareha.config import load_config, make_config_object
from kareha.config_defaults import get_defaults_dict
from kareha.core.posting import post_stuff
from kareha.wsgi import make_app


def test_blog_comments_normalized_from_config(tmp_path):
    cfg_file = tmp_path / "config.py"
    cfg_file.write_text(textwrap.dedent("""
        ADMIN_PASS = "testpass123"
        SECRET = "x" * 32
        BOARD_MODE = "blog"
        BLOG_COMMENTS = "disabled"
    """))
    cfg = load_config(cfg_file, mode="blog")
    assert cfg["BLOG_COMMENTS"] == "disabled"


def test_blog_comments_aliases_off(tmp_path):
    cfg_file = tmp_path / "config.py"
    cfg_file.write_text(textwrap.dedent("""
        ADMIN_PASS = "testpass123"
        SECRET = "x" * 32
        BOARD_MODE = "blog"
        BLOG_COMMENTS = "off"
    """))
    cfg = load_config(cfg_file, mode="blog")
    assert cfg["BLOG_COMMENTS"] == "disabled"


def _blog_board(tmp_path, **extra):
    lines = [
        'ADMIN_PASS = "test-admin-pass"',
        'SECRET = "test-secret-at-least-32-chars!!"',
        'BOARD_MODE = "blog"',
        "MAX_POSTS = 0",
        "DUPLICATE_WINDOW = 0",
        "ENABLE_REPORT_CAPTCHA = False",
        "RATE_LIMIT_POSTS_PER_MIN = 1000",
    ]
    for k, v in extra.items():
        lines.append(f"{k} = {v!r}" if isinstance(v, str) else f"{k} = {v}")
    (tmp_path / "config.py").write_text("\n".join(lines) + "\n")
    d = get_defaults_dict()
    d.update({
        "ADMIN_PASS": "test-admin-pass",
        "SECRET": "test-secret-at-least-32-chars!!",
        "BOARD_MODE": "blog",
        "MAX_POSTS": 0,
        "DUPLICATE_WINDOW": 0,
    })
    d.update(extra)
    config_module.current_config = make_config_object(d)
    (tmp_path / "res").mkdir(exist_ok=True)
    return make_app(tmp_path, mode="blog")


def test_blog_front_shows_last_three_comments_by_default(tmp_path):
    app = _blog_board(tmp_path)
    tid = post_stuff(tmp_path, comment="entry body", title="Hello", name="Admin")
    for i in range(1, 5):
        post_stuff(tmp_path, thread_id=tid, comment=f"comment number {i} unique")
    body = Client(app).get("/").get_data(as_text=True)
    assert "comment number 1 unique" not in body
    assert "comment number 2 unique" in body
    assert "comment number 3 unique" in body
    assert "comment number 4 unique" in body
    assert "1 comment omitted" in body


def test_blog_front_comments_setting(tmp_path):
    app = _blog_board(tmp_path, BLOG_FRONT_COMMENTS=1)
    tid = post_stuff(tmp_path, comment="entry body", title="Hello", name="Admin")
    post_stuff(tmp_path, thread_id=tid, comment="first unique comment")
    post_stuff(tmp_path, thread_id=tid, comment="second unique comment")
    body = Client(app).get("/").get_data(as_text=True)
    assert "first unique comment" not in body
    assert "second unique comment" in body
    assert "1 comment omitted" in body


def test_blog_front_hides_comments_when_disabled(tmp_path):
    app = _blog_board(tmp_path, BLOG_COMMENTS="disabled")
    tid = post_stuff(tmp_path, comment="entry body", title="Hello", name="Admin")
    post_stuff(tmp_path, thread_id=tid, comment="should not appear on index")
    body = Client(app).get("/").get_data(as_text=True)
    assert "should not appear on index" not in body