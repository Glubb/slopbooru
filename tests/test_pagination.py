"""Front-page pagination helpers and route smoke tests."""
from werkzeug.test import Client

from kareha.config import make_config_object
from kareha.config_defaults import get_defaults_dict
from kareha.views.board import page_href, paginate, parse_page_number
from kareha.wsgi import make_app


class _Req:
    def __init__(self, page=None):
        self.args = {} if page is None else {"page": page}


def test_parse_page_number_from_path_and_query():
    assert parse_page_number(_Req(), "/page/3") == 3
    assert parse_page_number(_Req("4"), "/") == 4
    assert parse_page_number(_Req("nope"), "/") == 1
    assert parse_page_number(_Req("0"), "/") == 1


def test_paginate_slices_and_flags():
    items = list(range(25))
    page, pager = paginate(items, 2, 10)
    assert page == list(range(10, 20))
    assert pager["page"] == 2
    assert pager["pages"] == 3
    assert pager["has_prev"]
    assert pager["has_next"]
    last, last_pager = paginate(items, 3, 10)
    assert last == list(range(20, 25))
    assert not last_pager["has_next"]


def test_page_href():
    assert page_href("", 1) == "/"
    assert page_href("/ad", 1) == "/ad/"
    assert page_href("/ad", 2) == "/ad/page/2"


def test_front_page_route_and_page_two(tmp_path):
    cfg = tmp_path / "config.py"
    cfg.write_text(
        'ADMIN_PASS = "test-admin-pass"\n'
        'SECRET = "test-secret-at-least-32-chars!!"\n'
        'THREADS_DISPLAYED = 2\n'
        'THREADS_LISTED = 40\n'
        'PAGE_GENERATION = "paged"\n'
        'MAX_POSTS = 0\n'
        'DUPLICATE_WINDOW = 0\n'
    )
    from kareha import config as config_module
    from kareha.core.posting import post_stuff

    app = make_app(tmp_path, mode="imageboard")
    d = get_defaults_dict()
    d.update({
        "ADMIN_PASS": "test-admin-pass",
        "SECRET": "test-secret-at-least-32-chars!!",
        "MAX_POSTS": 0,
        "THREADS_DISPLAYED": 2,
        "DUPLICATE_WINDOW": 0,
    })
    config_module.current_config = make_config_object(d)

    for i in range(5):
        post_stuff(tmp_path, comment=f"unique body number {i} xyz", title=f"T{i}")

    client = Client(app)
    r1 = client.get("/")
    assert r1.status_code == 200
    body = r1.get_data(as_text=True)
    assert "T4" in body
    assert "/page/2" in body

    r2 = client.get("/page/2")
    assert r2.status_code == 200
    body2 = r2.get_data(as_text=True)
    assert "[2]" in body2 or "thread" in body2
